"""Elegibilidade na origem da base de cobrança (seta_client.buscar_base_cobranca).

Roda a SQL de verdade num Postgres que imita as duas tabelas do SETA que ela lê
(`financeiro_titulos` e `pessoas`, só com as colunas usadas), com datas
relativas a hoje em Brasília. Cobre as duas regras:
- cliente cuja dívida aberta é só seguro (DESCRICAO_SEGURO) não volta;
- cliente com atraso real só volta se o principal vencido (sem multa/juros)
  for >= VALOR_MINIMO_ATRASO; lembrete (sem atraso ainda) não é cortado.

Executa com asserts simples, sem pytest. Imprime 'OK' ao final.
"""

import os
import tempfile
from datetime import timedelta
from decimal import Decimal

from cryptography.fernet import Fernet

DB_URL = "postgresql+psycopg://postgres:t@localhost:15432/test_seta_base"
os.environ.setdefault("DATABASE_URL", DB_URL)
os.environ.setdefault("JWT_SECRET", "test-secret-chave-longa-para-nao-ser-rejeitada-123")
os.environ.setdefault("ADMIN_PASSWORD", "TestAdmin123!")
os.environ.setdefault("MEDIA_DIR", tempfile.mkdtemp())
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from unittest.mock import patch

from sqlalchemy import create_engine, text

from app import seta_client
from app.cobranca_regras import PARAMETROS_JUROS_PADRAO
from app.seta_client import DESCRICAO_SEGURO, VALOR_MINIMO_ATRASO
from app.timezone import hoje_br

assert VALOR_MINIMO_ATRASO == Decimal("30.00")

# mesmo fuso das conexões reais com o SETA: o current_date da SQL é o de Brasília
engine = create_engine(DB_URL, connect_args={"options": "-c TimeZone=America/Sao_Paulo"})

with engine.begin() as conn:
    conn.execute(text("DROP TABLE IF EXISTS financeiro_titulos, pessoas"))
    conn.execute(text("""
        CREATE TABLE pessoas (
            codigo char(8) PRIMARY KEY, nome char(60), telefone1 char(20), telefone2 char(20),
            telefone3 char(20), telefone4 char(20), cpfcnpj char(18), status char(1),
            empresa char(3), faturamento numeric, credito numeric, nascimento date,
            cadastro date, scpcresultado text, cliente boolean, funcionario boolean
        )"""))
    conn.execute(text("""
        CREATE TABLE financeiro_titulos (
            pessoa char(8), valor numeric, vencimento date, empresa char(3), portador char(3),
            rp char(1), status char(1), tipo char(1), descricao char(40)
        )"""))

hoje = hoje_br()
SEGURO = DESCRICAO_SEGURO
NORMAL = "CREDIARIO"
_proximo = [0]


def cliente(titulos: list[tuple[str, str | None, int]]) -> str:
    """Cria um cliente com títulos em aberto (valor, descrição, dias de atraso;
    negativo = ainda a vencer) e devolve o código."""

    _proximo[0] += 1
    codigo = f"{_proximo[0]:08d}"
    with engine.begin() as conn:
        conn.execute(
            text("""INSERT INTO pessoas (codigo, nome, status, cliente, funcionario, cpfcnpj)
                    VALUES (:c, :n, 'A', true, false, :cpf)"""),
            {"c": codigo, "n": f"Cliente {codigo}", "cpf": f"{_proximo[0]:011d}"},
        )
        for valor, descricao, dias in titulos:
            conn.execute(
                text("""INSERT INTO financeiro_titulos
                        (pessoa, valor, vencimento, empresa, portador, rp, status, tipo, descricao)
                        VALUES (:p, :v, :venc, '001', '001', 'R', 'A', '4', :d)"""),
                {"p": codigo, "v": Decimal(valor), "venc": hoje - timedelta(days=dias), "d": descricao},
            )
    return codigo


def buscar(**kw) -> dict[str, dict]:
    kw.setdefault("faixas", [(-1, None)])  # de "vence amanhã" em diante
    with patch.object(seta_client, "engine_ou_erro", return_value=engine):
        return {r["codigo"]: r for r in seta_client.buscar_base_cobranca(**kw)}


# --- clientes dos cenários ---------------------------------------------------

so_seguro_50 = cliente([("50.00", SEGURO, 10)])
so_seguro_100 = cliente([("100.00", SEGURO, 10)])
dois_seguros = cliente([("40.00", SEGURO, 30), ("40.00", SEGURO, 10)])
seguro_a_vencer = cliente([("50.00", SEGURO, -1)])  # lembrete, mas só seguro
seguro_com_normal = cliente([("10.00", SEGURO, 10), ("100.00", NORMAL, 10)])
sem_seguro = cliente([("100.00", NORMAL, 10)])
abaixo_29_99 = cliente([("29.99", NORMAL, 40)])  # com juros passaria de 30
exato_30 = cliente([("30.00", NORMAL, 10)])
acima_30_01 = cliente([("30.01", NORMAL, 10)])
soma_29_99 = cliente([("10.00", NORMAL, 10), ("19.99", NORMAL, 8)])
soma_30 = cliente([("10.00", NORMAL, 10), ("20.00", NORMAL, 8)])
lembrete_amanha = cliente([("20.00", NORMAL, -1)])
lembrete_hoje = cliente([("5.00", NORMAL, 0)])
seguro_vencido_normal_futura = cliente([("50.00", SEGURO, 10), ("100.00", NORMAL, -5)])
seguro_pequeno_normal_futura = cliente([("10.00", SEGURO, 10), ("100.00", NORMAL, -5)])
descricao_nula = cliente([("100.00", None, 10)])
seguro_com_espacos = cliente([("100.00", SEGURO + "   ", 10)])

# premissa do cenário "original < 30 mas com juros passa de 30"
j = PARAMETROS_JUROS_PADRAO
com_juros = round(Decimal("29.99") + Decimal("29.99") * j.juros_dia * 40 + Decimal("29.99") * j.multa, 2)
assert com_juros > VALOR_MINIMO_ATRASO, com_juros

base = buscar()

# 1, 2, 12 e lembrete só de seguro: dívida exclusivamente de seguro nunca volta,
# nem acima de R$ 30 (a regra do seguro vem antes do valor mínimo)
for codigo in (so_seguro_50, so_seguro_100, dois_seguros, seguro_a_vencer, seguro_com_espacos):
    assert codigo not in base, f"só seguro não deve voltar: {codigo}"
print("  só seguro (1 ou 2 parcelas, vencido ou a vencer): fora")

# 3: seguro + parcela normal volta e o seguro continua compondo os valores
r = base[seguro_com_normal]
assert r["qtd_titulos"] == 2 and r["qtd_titulos_nao_seguro"] == 1
assert r["valor_em_aberto"] == Decimal("110.00") and r["valor_atraso_original"] == Decimal("110.00")
assert r["qtd_parcelas_cobranca"] == 2
print("  seguro + parcela normal: volta, seguro nos valores")

# 4: sem seguro, comportamento de sempre
assert sem_seguro in base and base[sem_seguro]["qtd_titulos_nao_seguro"] == 1
print("  sem seguro: volta")

# 5: R$ 29,99 original fica de fora mesmo com juros acima de R$ 30
assert abaixo_29_99 not in base
print(f"  R$ 29,99 (com juros R$ {com_juros}): fora")

# 6 e 7: limite inclusivo
assert exato_30 in base and base[exato_30]["valor_atraso_original"] == Decimal("30.00")
assert acima_30_01 in base
print("  R$ 30,00 e R$ 30,01: voltam")

# 8 e 9: soma das parcelas vencidas, não cada uma
assert soma_29_99 not in base
assert soma_30 in base and base[soma_30]["valor_atraso_original"] == Decimal("30.00")
print("  10 + 19,99 fora; 10 + 20 volta")

# 10: lembrete (ainda sem atraso) não passa pelo valor mínimo
for codigo in (lembrete_amanha, lembrete_hoje):
    assert codigo in base and base[codigo]["valor_atraso_original"] == 0
print("  lembrete sem atraso real (R$ 20 amanhã, R$ 5 hoje): volta")

# 11: seguro vencido + normal a vencer não é "só seguro"; o valor mínimo vale sobre o vencido
assert seguro_vencido_normal_futura in base
assert base[seguro_vencido_normal_futura]["qtd_titulos_nao_seguro"] == 1
assert base[seguro_vencido_normal_futura]["valor_atraso_original"] == Decimal("50.00")
assert seguro_pequeno_normal_futura not in base  # vencido original R$ 10
print("  seguro vencido + normal a vencer: volta se o vencido >= 30")

# descrição nula não é seguro
assert descricao_nula in base and base[descricao_nula]["qtd_titulos_nao_seguro"] == 1
print("  descrição nula conta como título normal")

# outros caminhos da mesma consulta: restrição por códigos (remarketing) e por dias exatos
alvo = buscar(codigos=[so_seguro_50, sem_seguro, abaixo_29_99, exato_30])
assert set(alvo) == {sem_seguro, exato_30}, set(alvo)
exato = buscar(faixas=[], dias_exatos=[-1])
assert set(exato) == {lembrete_amanha}, set(exato)  # seguro_a_vencer (também -1) fica de fora
print("  por códigos e por dias exatos: mesmas regras")

print("\nOK")
