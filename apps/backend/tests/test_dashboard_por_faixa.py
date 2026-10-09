"""Tabela "Por faixa" do Dashboard (GET /dashboard/summary): clientes cobrados
= clientes distintos com mensagem enviada no período, na faixa da coluna
Enviado; Frequência e "Pagaram após cobrança" na mesma base.

Executa com assert simples, sem pytest. Encerra imprimindo 'OK'.
"""

import os
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = "postgresql+psycopg://postgres:t@localhost:15432/agy_dash"
os.environ["JWT_SECRET"] = "segredo-de-teste-dashboard-123456"
os.environ["ADMIN_PASSWORD"] = "senha-admin-teste-dashboard"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp()
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from fastapi.testclient import TestClient

from app import consultas_fila, models
from app.database import SessionLocal
from app.main import app
from app.services import custo_whatsapp, pagamentos_service
from app.timezone import hoje_br, inicio_do_dia_utc

with TestClient(app):  # sobe o schema e cria o admin
    pass

# Sem `with`: não sobe o worker, que mexeria na fila no meio do teste
client = TestClient(app)
res = client.post("/auth/login", json={"email": "admin@topfama.com.br", "password": os.environ["ADMIN_PASSWORD"]})
assert res.status_code == 200, res.text
auth = {"Authorization": f"Bearer {res.json()['access_token']}"}

db = SessionLocal()
fa, fb, campanha = models.Faixa(name="FA"), models.Faixa(name="FB"), models.Faixa(name="CAMPANHA X", tipo="campanha")
fc = models.Faixa(name="FC")  # só lead marcado como cobrado à mão, sem fila
fr = models.Faixa(name="FR")  # reenvio a lead já cobrado ontem
fh = models.Faixa(name="FH")  # limite de horário do dia
db.add_all([fa, fb, campanha, fc, fr, fh])
db.flush()

agora = datetime.utcnow()
hoje = hoje_br()
ontem = agora - timedelta(days=1)
dia_h = hoje - timedelta(days=10)
S = models.QueueStatus


def item(faixa: models.Faixa, codigo: str, status: models.QueueStatus, faixa_atraso: str | None = None, sent_at=agora,
         valor: str | None = None):
    return models.QueueItem(
        faixa_id=faixa.id, codigo_cliente=codigo, celular="5511999999999", celular_original="11999999999",
        status=status, sent_at=sent_at if status == S.sent else None, created_at=agora, faixa_atraso=faixa_atraso,
        valor=valor,
    )


def lead(codigo: str, faixa: str, venc_dias: int = 10, cobrado_em=agora):
    return models.Lead(
        codigo_cliente=codigo, nome="X", cluster="TOP", faixa=faixa, dias_atraso=10,
        vencimento_mais_antigo=hoje - timedelta(days=venc_dias), status="cobrado", cobrado_em=cobrado_em,
    )


db.add_all([
    item(fa, "1", S.sent), item(fa, "1", S.sent),  # cliente 1: duas mensagens hoje
    item(fa, "2", S.sent),
    item(campanha, "2", S.sent, faixa_atraso="FA"),  # campanha conta na faixa de atraso do cliente
    item(campanha, "6", S.sent, faixa_atraso="FA"),  # só pela campanha: cobrado em FA
    item(fa, "3", S.error), item(fa, "10", S.invalid_phone),  # sem mensagem enviada: fora
    item(fa, "9", S.sent),  # lead cobrado dias atrás, mensagem hoje: conta hoje
    item(fb, "4", S.sent), item(fb, "5", S.pending),
    item(fb, "1", S.sent),  # cliente 1 também em FB: um em cada faixa, um no total
    item(fa, "1", S.sent, sent_at=agora - timedelta(days=5)),  # fora do período
    item(fr, "R", S.sent, sent_at=ontem), item(fr, "R", S.sent, valor="1.500,00"),
    # 23:59 e 00:01 de Brasília em volta da virada de dia_h
    item(fh, "H1", S.sent, sent_at=inicio_do_dia_utc(dia_h + timedelta(days=1)) - timedelta(minutes=1)),
    item(fh, "H2", S.sent, sent_at=inicio_do_dia_utc(dia_h + timedelta(days=1)) + timedelta(minutes=1)),
    lead("1", "FA"), lead("1", "FA", venc_dias=40),
    lead("2", "FA"), lead("4", "FB"),
    lead("7", "FA"),  # marcado como cobrado à mão: sem mensagem, não conta
    lead("9", "FA", cobrado_em=agora - timedelta(days=5)),
    lead("8", "FC"),
    lead("R", "FR", cobrado_em=ontem),  # o reenvio de hoje não muda o cobrado_em
])
db.commit()


def resumo(de, ate, pagaram=(), custo_por_envio=None):
    # Sem WABA cadastrada o custo da Meta fica indisponível (None)
    custo = (custo_por_envio, None)
    with patch("app.services.pagamentos_service.clientes_que_pagaram", return_value=list(pagaram)) as pagos, \
            patch("app.routers.dashboard.custo_whatsapp.custo_por_envio", return_value=custo):
        res = client.get(f"/dashboard/summary?de={de.isoformat()}&ate={ate.isoformat()}", headers=auth)
    assert res.status_code == 200, res.text
    assert pagos.call_args.kwargs["base"] == "envios", pagos.call_args
    return res.json()


pagaram = [
    {"codigo_cliente": "1", "faixa": "FA", "valor_pago": Decimal("10")},
    # mesmo cliente com duas linhas (dias diferentes): a linha traz o mesmo pagamento
    {"codigo_cliente": "1", "faixa": "FA", "valor_pago": Decimal("10")},
    # cobrado em duas faixas no mesmo dia: conta nas duas linhas, uma vez no total
    {"codigo_cliente": "4", "faixa": "FA, FB", "valor_pago": Decimal("25")},
]
dados = resumo(hoje, hoje, pagaram)
por_faixa = {r["faixa"]: r for r in dados["por_faixa"]}
assert set(por_faixa) == {"FA", "FB", "FR"}, por_faixa  # FC só tem lead marcado à mão

f = por_faixa["FA"]
assert f["sent"] == 6 and f["error"] == 1 and f["invalid_phone"] == 1, f
assert f["clientes_cobrados"] == 4, f  # 1, 2, 6 e 9; o 7 (à mão), o 3 e o 10 (sem envio) ficam fora
assert f["enviados_cobrados"] == f["sent"] and f["clientes_com_envio"] == 4, f
assert f["pagaram"] == 2 and f["valor_pago"] == "35.00", f

f = por_faixa["FB"]
assert f["sent"] == 2 and f["pending"] == 1, f
assert f["clientes_cobrados"] == 2 and f["enviados_cobrados"] == 2 and f["clientes_com_envio"] == 2, f
assert f["pagaram"] == 1 and f["valor_pago"] == "25.00", f

# Reenvio hoje a lead cobrado ontem: conta hoje (antes ficava 0)
f = por_faixa["FR"]
assert f["sent"] == 1 and f["clientes_cobrados"] == 1 and f["enviados_cobrados"] == 1, f

# Total: cada cliente e cada pagamento uma vez (cliente 1 em FA e FB); num dia
# sem cliente repetido, cobranças = clientes cobrados
total = dados["total_por_faixa"]
assert total == {
    "clientes_cobrados": 6,  # 1, 2, 6, 9, 4 e R
    "enviados_cobrados": 9,
    "clientes_com_envio": 6,
    "pagaram": 2,  # 1 e 4
    "valor_pago": "35.00",
    "custo_whatsapp": None,  # custo da Meta indisponível: ROAS "—"
}, total
assert all(r["custo_whatsapp"] is None for r in dados["por_faixa"]), dados
assert dados["total_enviados"] == total["enviados_cobrados"], dados

# Ontem e hoje: o cliente R recebeu duas mensagens, é um cliente (Frequência 2,0)
dia_ontem = hoje - timedelta(days=1)
dados = resumo(dia_ontem, hoje, custo_por_envio={dia_ontem: Decimal("0.20"), hoje: Decimal("0.10")})
por_faixa = {r["faixa"]: r for r in dados["por_faixa"]}
f = por_faixa["FR"]
assert f["sent"] == 2 and f["enviados_cobrados"] == 2 and f["clientes_cobrados"] == 1, f
# Custo da faixa (base do ROAS) = custo por envio de cada dia × envios da faixa no dia
assert f["custo_whatsapp"] == "0.30", f  # um envio ontem (0,20) e um hoje (0,10)
assert por_faixa["FA"]["custo_whatsapp"] == "0.60" and por_faixa["FB"]["custo_whatsapp"] == "0.20", por_faixa
assert dados["total_por_faixa"]["custo_whatsapp"] == "1.10", dados["total_por_faixa"]

# Rateio do custo da Meta: custo do dia ÷ mensagens enviadas no dia (todas as faixas);
# dia sem envio fica de fora
assert consultas_fila.envios_por_dia(db, dia_h, dia_h) == {(dia_h, "FH"): 1}  # 23:59 de Brasília conta no dia
assert consultas_fila.envios_por_dia(db, hoje, hoje)[(hoje, "FA")] == 6
dia_sem_envio = hoje - timedelta(days=3)
with patch.object(custo_whatsapp, "gasto_diario_brl", return_value=({hoje: Decimal("1.80"), dia_sem_envio: Decimal("5")}, None)):
    por_envio, _motivo = custo_whatsapp.custo_por_envio(db, dia_sem_envio, hoje)
assert por_envio == {hoje: Decimal("0.20"), dia_ontem: Decimal("0")}, por_envio  # hoje: 9 envios
with patch.object(custo_whatsapp, "gasto_diario_brl", return_value=(None, "Meta fora")):
    assert custo_whatsapp.custo_por_envio(db, hoje, hoje) == (None, "Meta fora")

# Limite do dia em Brasília: 23:59 conta, 00:01 do dia seguinte não
f = {r["faixa"]: r for r in resumo(dia_h, dia_h)["por_faixa"]}["FH"]
assert f["sent"] == 1 and f["clientes_cobrados"] == 1, f

# Pagaram com base=envios: data da cobrança = primeiro envio do período na
# faixa; quem pagou antes dele não entra
db.add_all([
    models.PagamentoSeta(titulo_codigo="P1", codigo_cliente="R", pagamento=hoje, valor=Decimal("30"), rp="R"),
    models.PagamentoSeta(titulo_codigo="P2", codigo_cliente="4", pagamento=hoje - timedelta(days=1), valor=Decimal("40"), rp="R"),
])
db.commit()
linhas = pagamentos_service.clientes_que_pagaram(db, cobrado_de=hoje, cobrado_ate=hoje, buscar_novos=False, base="envios")
assert [(l["codigo_cliente"], l["faixa"], l["data_cobranca"]) for l in linhas] == [("R", "FR", hoje)], linhas
assert linhas[0]["valor_pago"] == Decimal("30.00") and linhas[0]["valor_cobrado"] == Decimal("1500.00"), linhas
# Pela data do lead (relatório pelo menu), o R foi cobrado ontem
assert [l["data_cobranca"] for l in pagamentos_service.clientes_que_pagaram(
    db, cobrado_de=hoje - timedelta(days=1), cobrado_ate=hoje - timedelta(days=1), buscar_novos=False
) if l["codigo_cliente"] == "R"] == [hoje - timedelta(days=1)]
assert pagamentos_service.clientes_que_pagaram(
    db, cobrado_de=hoje, cobrado_ate=hoje, faixa=["FA"], buscar_novos=False, base="envios"
) == []

# Ordem das colunas: salva na conta do usuário; vazia volta à ordem padrão
url = "/dashboard/colunas-por-faixa"
assert client.get(url, headers=auth).json() == {"colunas": []}
ordem = ["valor_pago", "pending", "representatividade"]
res = client.put(url, json={"colunas": ordem}, headers=auth)
assert res.status_code == 200 and res.json() == {"colunas": ordem}, res.text
assert client.get(url, headers=auth).json() == {"colunas": ordem}
db.expire_all()
assert db.query(models.User).filter_by(email="admin@topfama.com.br").one().colunas_por_faixa == ordem
assert client.put(url, json={"colunas": ["x" * 41]}, headers=auth).status_code == 422
assert client.put(url, json={"colunas": [""]}, headers=auth).status_code == 422
assert client.put(url, json={"colunas": []}, headers=auth).status_code == 200
assert client.get(url, headers=auth).json() == {"colunas": []}

db.close()
print("OK")
