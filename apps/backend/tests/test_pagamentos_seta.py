"""Cópia local das baixas do SETA (services/pagamentos_seta.py): cliente novo
é lido desde a primeira cobrança, tela aberta não relê quem já foi copiado,
rodada do worker relê só a sobreposição e tira título estornado.

SQLite em memória com as tabelas criadas direto do models (só neste teste) e
o SETA simulado. Executa com asserts simples, sem pytest.
"""

import os
import tempfile
from datetime import date, datetime, timedelta
from decimal import Decimal

from cryptography.fernet import Fernet

os.environ.setdefault("JWT_SECRET", "segredo-de-teste-pagamentos-seta-123456")
os.environ.setdefault("ADMIN_PASSWORD", "senha-admin-teste-pagamentos-seta")
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())
os.environ.setdefault("MEDIA_DIR", tempfile.mkdtemp())
os.environ.setdefault("DATABASE_URL", "sqlite://")

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models, seta_client
from app.database import Base
from app.services import pagamentos_seta, pagamentos_service
from app.timezone import hoje_br

engine = create_engine("sqlite://")
Base.metadata.create_all(engine, tables=[
    models.Lead.__table__, models.PagamentoSeta.__table__, models.PagamentoSetaCliente.__table__,
])
db = sessionmaker(bind=engine)()

hoje = hoje_br()
cobranca = hoje - timedelta(days=20)


def lead(codigo: str, dia: date) -> models.Lead:
    # 15h UTC = 12h em Brasília: mesmo dia nos dois fusos
    return models.Lead(
        codigo_cliente=codigo, nome="X", cluster="TOP", faixa=f"F{dia}", dias_atraso=10,
        vencimento_mais_antigo=dia, status="cobrado", cobrado_em=datetime.combine(dia, datetime.min.time()) + timedelta(hours=15),
    )


db.add_all([lead("00000001", cobranca), lead("00000002", cobranca)])
db.commit()

# SETA simulado: título → (cliente, pagamento, valor, rp)
seta = {
    "T1": ("00000001", cobranca + timedelta(days=2), Decimal("100"), "R"),
    "T2": ("00000001", cobranca - timedelta(days=5), Decimal("50"), "R"),  # antes da cobrança: não entra
    "T3": ("00000002", hoje - timedelta(days=1), Decimal("0"), "P"),  # quitou algo sem valor a receber
}
leituras: list[list[tuple[str, date]]] = []


def baixas_de_clientes(clientes):
    leituras.append(list(clientes))
    desde = dict(clientes)
    return [
        {"titulo_codigo": t, "codigo_cliente": c, "pagamento": p, "valor": v, "rp": rp, "pago_em": (resto or [None])[0]}
        for t, (c, p, v, rp, *resto) in seta.items()
        if c in desde and p >= desde[c]
    ]


seta_client.baixas_de_clientes = baixas_de_clientes
pares = [("00000001", cobranca), ("00000002", cobranca)]

# 1. Primeira tela: lê os dois clientes desde a primeira cobrança
pagou = pagamentos_seta.pagamentos_pos_cobranca(db, pares, dias_janela=7)
assert pagou == {("00000001", cobranca): cobranca + timedelta(days=2)}, pagou
assert leituras == [[("00000001", cobranca), ("00000002", cobranca)]], leituras
valores = pagamentos_seta.valores_pagos_pos_cobranca(db, pares)
assert valores[("00000001", cobranca)]["valor_pago"] == Decimal("100")
assert ("00000002", cobranca) not in valores  # sem valor a receber
assert ("00000002", cobranca) in pagamentos_seta.pagamentos_pos_cobranca(db, pares)  # mas conta como pagou
assert len(leituras) == 1, "tela aberta de novo não pode voltar ao SETA"

# 2. Rodada do worker: relê só a partir da marca d'água menos a sobreposição
seta["T4"] = ("00000001", hoje, Decimal("30"), "R")
del seta["T3"]  # estorno
pagamentos_seta.sincronizar(db)
inicio = hoje - timedelta(days=pagamentos_seta.SOBREPOSICAO_DIAS)
assert leituras[-1] == [("00000001", inicio), ("00000002", inicio)], leituras[-1]
valores = pagamentos_seta.valores_pagos_pos_cobranca(db, pares)
assert valores[("00000001", cobranca)]["valor_pago"] == Decimal("130"), valores
assert ("00000002", cobranca) not in pagamentos_seta.pagamentos_pos_cobranca(db, pares), "estorno tem que sumir"

# 3. Cliente cobrado depois: só ele é lido na próxima tela
db.add(lead("00000003", hoje))
db.commit()
seta["T5"] = ("00000003", hoje, Decimal("80"), "R")
v = pagamentos_seta.valores_pagos_pos_cobranca(db, [("00000003", hoje)])
assert leituras[-1] == [("00000003", hoje)], leituras[-1]
assert v[("00000003", hoje)]["valor_pago"] == Decimal("80")

# 4. Rodada do worker só com alguém usando o CRM
pagamentos_seta._ultima_atividade = None
pagamentos_seta._ultima_rodada = None
assert not pagamentos_seta.rodada_devida(1800), "ninguém usando: não lê o SETA"
pagamentos_seta.registrar_atividade()
assert pagamentos_seta.rodada_devida(1800), "usuário chegou e nunca rodou: roda"
pagamentos_seta.sincronizar(db)
assert not pagamentos_seta.rodada_devida(1800), "acabou de rodar: espera o intervalo"
pagamentos_seta._ultima_rodada -= 1801
assert pagamentos_seta.rodada_devida(1800)
pagamentos_seta._ultima_atividade -= pagamentos_seta.ATIVIDADE_JANELA_SEGUNDOS + 1
assert not pagamentos_seta.rodada_devida(1800), "usuário saiu há mais de 15 min: para"

# 5. Pago no dia da cobrança: horário do caixa decide; sem horário continua contando.
# Cobrança às 12h de Brasília (lead() grava 15h UTC).
meio_dia = datetime.combine(hoje, datetime.min.time()) + timedelta(hours=12)
db.add_all([lead("00000004", hoje), lead("00000005", hoje), lead("00000006", hoje)])
db.commit()
seta["T6"] = ("00000004", hoje, Decimal("40"), "R", meio_dia - timedelta(hours=2))  # antes da mensagem
seta["T7"] = ("00000005", hoje, Decimal("50"), "R", meio_dia + timedelta(hours=2))  # depois
seta["T8"] = ("00000006", hoje, Decimal("60"), "R")  # fora do caixa: sem horário
pares_hoje = [("00000004", hoje), ("00000005", hoje), ("00000006", hoje)]
pagou = pagamentos_seta.pagamentos_pos_cobranca(db, pares_hoje)
assert ("00000004", hoje) not in pagou, "pagou antes da mensagem sair não conta"
assert ("00000005", hoje) in pagou and ("00000006", hoje) in pagou, pagou
valores = pagamentos_seta.valores_pagos_pos_cobranca(db, pares_hoje)
assert set(valores) == {("00000005", hoje), ("00000006", hoje)}, valores

# 5. Clientes cobrados por faixa (coluna do Dashboard): clientes distintos na
# mesma base do "Pagaram após cobrança" (lead cobrado no período, pela faixa do lead)
dia_cob = hoje - timedelta(days=3)


def lead_faixa(codigo: str, faixa: str, venc_dias: int, status: str = "cobrado", dia: date = dia_cob) -> models.Lead:
    return models.Lead(
        codigo_cliente=codigo, nome="X", cluster="TOP", faixa=faixa, dias_atraso=10,
        vencimento_mais_antigo=dia - timedelta(days=venc_dias), status=status,
        cobrado_em=datetime.combine(dia, datetime.min.time()) + timedelta(hours=15),
    )


db.add_all([
    lead_faixa("00000020", "FA", 10),
    lead_faixa("00000020", "FA", 40),  # mesmo cliente, outra parcela: conta uma vez
    lead_faixa("00000020", "FB", 70),  # mesmo cliente em outra faixa: conta nas duas
    lead_faixa("00000021", "FA", 10),
    lead_faixa("00000022", "FA", 10, status="novo"),  # não cobrado: fora
    lead_faixa("00000023", "FA", 10, dia=dia_cob - timedelta(days=30)),  # cobrado fora do período: fora
])
db.commit()
cobrados = pagamentos_service.clientes_cobrados_por_faixa(db, cobrado_de=dia_cob, cobrado_ate=dia_cob)
assert cobrados == {"FA": 2, "FB": 1}, cobrados
# Sem período: conta todo cobrado da faixa
assert pagamentos_service.clientes_cobrados_por_faixa(db, cobrado_de=None, cobrado_ate=None)["FA"] == 3

print("OK")
