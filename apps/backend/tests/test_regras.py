"""Script de validação das regras de cobrança em banco.

Roda com:
    PYTHONPATH=. "C:/Users/TopFama/Documents/ProjetosDEV/FintechCRM/apps/backend/.venv/Scripts/python.exe" tests/test_regras.py

Imprime 'OK' ao final se tudo passar.
"""

import os
import sys
import tempfile
import uuid
from decimal import Decimal
from unittest.mock import patch

from cryptography.fernet import Fernet

# --- Configuração mínima de ambiente para o app subir ---
DB_URL = "postgresql+psycopg://postgres:t@localhost:15432/agy_regras"
os.environ.setdefault("DATABASE_URL", DB_URL)
os.environ.setdefault("JWT_SECRET", "test-secret-chave-longa-para-nao-ser-rejeitada-123")
os.environ.setdefault("ADMIN_PASSWORD", "TestAdmin123!")
os.environ.setdefault("MEDIA_DIR", tempfile.mkdtemp())
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())  # o backend não sobe sem ela

# --- 1. Migration: ciclo upgrade → downgrade → upgrade → check ---

print("=== 1. Migration ===")

from alembic import command
from alembic.config import Config
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
alembic_cfg.set_main_option("sqlalchemy.url", DB_URL)

# downgrade para garantir estado limpo
command.downgrade(alembic_cfg, "base")
print("  downgrade base: OK")

command.upgrade(alembic_cfg, "head")
print("  upgrade head (1): OK")

command.downgrade(alembic_cfg, "base")
print("  downgrade base (2): OK")

command.upgrade(alembic_cfg, "head")
print("  upgrade head (2): OK")

# alembic check (sem diff)
from io import StringIO
from contextlib import redirect_stdout

buf = StringIO()
try:
    with redirect_stdout(buf):
        command.check(alembic_cfg)
    print("  alembic check: OK")
except SystemExit as e:
    if e.code != 0:
        output = buf.getvalue()
        print(f"  alembic check FALHOU: {output}")
        sys.exit(1)
    print("  alembic check: OK")

# Agora carregar_regras deve retornar igual a REGRAS_PADRAO
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

engine = create_engine(DB_URL)
Session = sessionmaker(bind=engine)

from app.regras_db import carregar_regras
from app.cobranca_regras import REGRAS_PADRAO

with Session() as db:
    regras = carregar_regras(db)

assert regras.clusters == REGRAS_PADRAO.clusters, f"clusters divergem:\n{regras.clusters}\n!=\n{REGRAS_PADRAO.clusters}"
assert regras.faixas == REGRAS_PADRAO.faixas, f"faixas divergem:\n{regras.faixas}\n!=\n{REGRAS_PADRAO.faixas}"
assert regras.whatsapp == REGRAS_PADRAO.whatsapp, f"whatsapp diverge"
assert regras.juros == REGRAS_PADRAO.juros, f"juros divergem: {regras.juros} != {REGRAS_PADRAO.juros}"
print("  carregar_regras == REGRAS_PADRAO: OK")

# --- 2. Testes puros do objeto Regras ---

print("=== 2. Regras puras ===")

r = REGRAS_PADRAO

# Fronteiras de cluster
assert r.cluster_por_valor_pago(Decimal("399.99")) == "ESPECIAL"
assert r.cluster_por_valor_pago(Decimal("400")) == "POTENCIAL"
assert r.cluster_por_valor_pago(Decimal("999.99")) == "POTENCIAL"
assert r.cluster_por_valor_pago(Decimal("1000")) == "EM POTENCIAL"
assert r.cluster_por_valor_pago(Decimal("1499")) == "EM POTENCIAL"
assert r.cluster_por_valor_pago(Decimal("1500")) == "ALTO POTENCIAL"
assert r.cluster_por_valor_pago(Decimal("2999")) == "ALTO POTENCIAL"
assert r.cluster_por_valor_pago(Decimal("3000")) == "BEST SELLER"
assert r.cluster_por_valor_pago(Decimal("6999.99")) == "BEST SELLER"
assert r.cluster_por_valor_pago(Decimal("7000")) == "HEAVY USER"
assert r.cluster_por_valor_pago(None) == "ESPECIAL"
assert r.cluster_por_valor_pago(0) == "ESPECIAL"
print("  cluster_por_valor_pago: OK")

# faixa_por_dias
assert r.faixa_por_dias(-5) is None
assert r.faixa_por_dias(-2) is None
assert r.faixa_por_dias(-1) == "-1"
assert r.faixa_por_dias(0) == "-1"
assert r.faixa_por_dias(1) == "-1"
assert r.faixa_por_dias(2) == "2"
assert r.faixa_por_dias(3) == "3 A 10"
assert r.faixa_por_dias(10) == "3 A 10"
assert r.faixa_por_dias(11) == "11 A 20"
assert r.faixa_por_dias(20) == "11 A 20"
assert r.faixa_por_dias(21) == "21 A 30"
assert r.faixa_por_dias(40) == "31 A 40"
assert r.faixa_por_dias(41) == "41 A 60"
assert r.faixa_por_dias(60) == "41 A 60"
assert r.faixa_por_dias(61) == "61 A 80"
assert r.faixa_por_dias(100) == "81 A 100"
assert r.faixa_por_dias(101) == "101 A 120"
assert r.faixa_por_dias(150) == "141 A 150"
assert r.faixa_por_dias(151) == "151+"
assert r.faixa_por_dias(9999) == "151+"
print("  faixa_por_dias: OK")

# entra_no_whatsapp
assert not r.entra_no_whatsapp("HEAVY USER", "2")
assert r.entra_no_whatsapp("ESPECIAL", "2")
assert not r.entra_no_whatsapp("ESPECIAL", "3 A 10")
assert not r.entra_no_whatsapp("ESPECIAL", None)
print("  entra_no_whatsapp: OK")

# --- 3. Testes de API com TestClient ---

print("=== 3. API (TestClient) ===")

from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app, raise_server_exceptions=True)
client.__enter__()

# Login de admin
resp = client.post("/auth/login", json={
    "email": "admin@topfama.com.br",
    "password": os.environ["ADMIN_PASSWORD"]
})
assert resp.status_code == 200, f"login falhou: {resp.text}"
token = resp.json()["access_token"]
headers = {"Authorization": f"Bearer {token}"}
print("  login: OK")

# GET /config/cobranca bate com o seed
resp = client.get("/config/cobranca", headers=headers)
assert resp.status_code == 200, f"GET config falhou: {resp.text}"
cfg = resp.json()
assert len(cfg["clusters"]) == 6
assert len(cfg["faixas"]) == 13
assert cfg["parametros"]["juros_mes_percentual"] == "15.99"
print("  GET /config/cobranca: OK")

# PUT /clusters: criar VIP (20000) sem id, renomear ESPECIAL e remover HEAVY USER
cluster_ids = {c["nome"]: c["id"] for c in cfg["clusters"]}
novo_corpo = [
    {"id": cluster_ids["ESPECIAL"], "nome": "ESPECIAL VIP", "valor_min": "0"},
    {"id": cluster_ids["POTENCIAL"], "nome": "POTENCIAL", "valor_min": "400"},
    {"id": cluster_ids["EM POTENCIAL"], "nome": "EM POTENCIAL", "valor_min": "1000"},
    {"id": cluster_ids["ALTO POTENCIAL"], "nome": "ALTO POTENCIAL", "valor_min": "1500"},
    {"id": cluster_ids["BEST SELLER"], "nome": "BEST SELLER", "valor_min": "3000"},
    # HEAVY USER omitido → removido
    {"nome": "VIP", "valor_min": "20000"},
]
resp = client.put("/config/cobranca/clusters", json=novo_corpo, headers=headers)
assert resp.status_code == 200, f"PUT clusters falhou: {resp.text}"
cfg2 = resp.json()
nomes_novos = [c["nome"] for c in cfg2["clusters"]]
assert "HEAVY USER" not in nomes_novos
assert "VIP" in nomes_novos
assert "ESPECIAL VIP" in nomes_novos
# células da matriz do HEAVY USER devem sumir
resp_m = client.get("/config/cobranca", headers=headers)
matriz = resp_m.json()["matriz"]
heavy_id = cluster_ids["HEAVY USER"]
assert all(c["cluster_id"] != heavy_id for c in matriz), "células de HEAVY USER não foram removidas"
resp_cr = client.get("/cobranca/regras", headers=headers)
assert resp_cr.status_code == 200
cr = resp_cr.json()
assert "VIP" in cr["clusters"]
assert "ESPECIAL VIP" in cr["clusters"]
assert "HEAVY USER" not in cr["clusters"]
print("  PUT /clusters (criar/renomear/remover): OK")

# Validações 400 do PUT clusters
# nome repetido ignorando caixa
resp = client.put("/config/cobranca/clusters", json=[
    {"nome": "A", "valor_min": "0"},
    {"nome": "a", "valor_min": "100"},
], headers=headers)
assert resp.status_code == 400, f"deveria ser 400: {resp.text}"

# menor valor_min != 0
resp = client.put("/config/cobranca/clusters", json=[
    {"nome": "A", "valor_min": "100"},
], headers=headers)
assert resp.status_code == 400

# valor_min repetido
resp = client.put("/config/cobranca/clusters", json=[
    {"nome": "A", "valor_min": "0"},
    {"nome": "B", "valor_min": "0"},
], headers=headers)
assert resp.status_code == 400

# lista vazia
resp = client.put("/config/cobranca/clusters", json=[], headers=headers)
assert resp.status_code == 400
print("  Validações PUT /clusters: OK")

# Restaurar clusters para continuar os testes
resp = client.put("/config/cobranca/clusters", json=[
    {"nome": "ESPECIAL", "valor_min": "0"},
    {"nome": "POTENCIAL", "valor_min": "400"},
    {"nome": "EM POTENCIAL", "valor_min": "1000"},
    {"nome": "ALTO POTENCIAL", "valor_min": "1500"},
    {"nome": "BEST SELLER", "valor_min": "3000"},
    {"nome": "HEAVY USER", "valor_min": "7000"},
], headers=headers)
assert resp.status_code == 200

# PUT /faixas com sobreposição → 400
cfg_atual = client.get("/config/cobranca", headers=headers).json()
faixa_ids = {f["nome"]: f["id"] for f in cfg_atual["faixas"]}
resp = client.put("/config/cobranca/faixas", json=[
    {"nome": "-1", "dia_min": -1, "dia_max": 5},
    {"nome": "2", "dia_min": 3, "dia_max": 10},  # sobreposição com -1
], headers=headers)
assert resp.status_code == 400, f"deveria ser 400 por sobreposição: {resp.text}"
print("  PUT /faixas sobreposição -> 400: OK")

# PUT /faixas válido: 3 A 10 → 3 A 4 + nova 5 A 10
faixas_sem_3a10 = [f for f in cfg_atual["faixas"] if f["nome"] != "3 A 10"]
novas_faixas = faixas_sem_3a10 + [
    {"nome": "3 A 4", "dia_min": 3, "dia_max": 4},
    {"nome": "5 A 10", "dia_min": 5, "dia_max": 10},
]
# Removemos id de faixas novas para criar
resp = client.put("/config/cobranca/faixas", json=novas_faixas, headers=headers)
assert resp.status_code == 200, f"PUT faixas válido falhou: {resp.text}"
cfg3 = resp.json()
nomes_faixas = [f["nome"] for f in cfg3["faixas"]]
assert "3 A 10" not in nomes_faixas
assert "3 A 4" in nomes_faixas
assert "5 A 10" in nomes_faixas
resp_cr = client.get("/cobranca/regras", headers=headers)
assert resp_cr.status_code == 200
cr = resp_cr.json()
assert "3 A 10" not in cr["faixas"]
assert "3 A 4" in cr["faixas"]
assert "5 A 10" in cr["faixas"]
assert cr["primeiro_dia"]["3 A 4"] == 3
assert cr["primeiro_dia"]["5 A 10"] == 5
print("  PUT /faixas ajuste válido: OK")

# Restaurar faixas
resp = client.put("/config/cobranca/faixas", json=[
    {"nome": "-1", "dia_min": -1, "dia_max": 1},
    {"nome": "2", "dia_min": 2, "dia_max": 2},
    {"nome": "3 A 10", "dia_min": 3, "dia_max": 10},
    {"nome": "11 A 20", "dia_min": 11, "dia_max": 20},
    {"nome": "21 A 30", "dia_min": 21, "dia_max": 30},
    {"nome": "31 A 40", "dia_min": 31, "dia_max": 40},
    {"nome": "41 A 60", "dia_min": 41, "dia_max": 60},
    {"nome": "61 A 80", "dia_min": 61, "dia_max": 80},
    {"nome": "81 A 100", "dia_min": 81, "dia_max": 100},
    {"nome": "101 A 120", "dia_min": 101, "dia_max": 120},
    {"nome": "121 A 140", "dia_min": 121, "dia_max": 140},
    {"nome": "141 A 150", "dia_min": 141, "dia_max": 150},
    {"nome": "151+", "dia_min": 151, "dia_max": None},
], headers=headers)
assert resp.status_code == 200

# PUT /matriz com id inexistente → 404
resp = client.put("/config/cobranca/matriz", json=[
    {"cluster_id": "inexistente-uuid", "faixa_id": "tambem-invalido"}
], headers=headers)
assert resp.status_code == 404, f"deveria ser 404: {resp.text}"
print("  PUT /matriz id inexistente -> 404: OK")

# PUT /matriz válido
cfg_v = client.get("/config/cobranca", headers=headers).json()
c_ids = {c["nome"]: c["id"] for c in cfg_v["clusters"]}
f_ids = {f["nome"]: f["id"] for f in cfg_v["faixas"]}
nova_matriz = [
    {"cluster_id": c_ids["ESPECIAL"], "faixa_id": f_ids["-1"]},
    {"cluster_id": c_ids["ESPECIAL"], "faixa_id": f_ids["151+"]},
]
resp = client.put("/config/cobranca/matriz", json=nova_matriz, headers=headers)
assert resp.status_code == 200
assert len(resp.json()["matriz"]) == 2
resp_cr = client.get("/cobranca/regras", headers=headers)
assert resp_cr.status_code == 200
cr = resp_cr.json()
assert cr["faixas_whatsapp"].get("ESPECIAL") == ["-1", "151+"]
print("  PUT /matriz válido: OK")

# PUT /parametros fora dos limites → 400
resp = client.put("/config/cobranca/parametros", json={
    "juros_mes_percentual": "2000",  # > 1000
    "multa_percentual": "2",
    "dias_min_juros": 3,
}, headers=headers)
assert resp.status_code == 400
print("  PUT /parametros fora do limite -> 400: OK")

# PUT /parametros válido
resp = client.put("/config/cobranca/parametros", json={
    "juros_mes_percentual": "10.00",
    "multa_percentual": "1.5",
    "dias_min_juros": 5,
}, headers=headers)
assert resp.status_code == 200
assert resp.json()["parametros"]["juros_mes_percentual"] == "10.00"
print("  PUT /parametros válido: OK")

# Sem token → 401
resp = client.get("/config/cobranca")
assert resp.status_code == 401
print("  Sem token -> 401: OK")

# GET /cobranca/regras reflete o novo estado
# Após as mudanças acima, restaurar estado padrão e verificar
resp = client.put("/config/cobranca/parametros", json={
    "juros_mes_percentual": "15.99",
    "multa_percentual": "2",
    "dias_min_juros": 3,
}, headers=headers)
assert resp.status_code == 200

# Restaurar matriz padrão
cfg_v2 = client.get("/config/cobranca", headers=headers).json()
c_ids2 = {c["nome"]: c["id"] for c in cfg_v2["clusters"]}
f_ids2 = {f["nome"]: f["id"] for f in cfg_v2["faixas"]}
base_alto = ["-1", "11 A 20", "31 A 40", "81 A 100", "101 A 120", "121 A 140", "141 A 150", "151+"]
base_potencial = ["-1", "2", "11 A 20", "31 A 40", "61 A 80", "81 A 100", "101 A 120", "121 A 140", "141 A 150", "151+"]
matriz_padrao_input = {
    "ESPECIAL": ["-1", "2", "11 A 20", "21 A 30", "61 A 80", "101 A 120", "121 A 140", "141 A 150", "151+"],
    "POTENCIAL": base_potencial,
    "EM POTENCIAL": base_potencial,
    "ALTO POTENCIAL": base_alto,
    "BEST SELLER": base_alto,
    "HEAVY USER": base_alto,
}
nova_m = []
for cn, fns in matriz_padrao_input.items():
    if cn not in c_ids2:
        continue
    for fn in fns:
        if fn in f_ids2:
            nova_m.append({"cluster_id": c_ids2[cn], "faixa_id": f_ids2[fn]})
resp = client.put("/config/cobranca/matriz", json=nova_m, headers=headers)
assert resp.status_code == 200

# GET /cobranca/regras deve ter ESPECIAL nas faixas
resp_cr = client.get("/cobranca/regras", headers=headers)
assert resp_cr.status_code == 200
cr = resp_cr.json()
assert "ESPECIAL" in cr["clusters"]
assert "151+" in cr["faixas"]
assert "2" in cr["faixas_whatsapp"].get("ESPECIAL", [])
print("  GET /cobranca/regras reflete estado atual: OK")

# --- 4. Serviço cobranca_base com seta_client substituído ---

print("=== 4. Serviço cobranca_base (mock do SETA) ===")

from app import cache, cobranca_base

# A base do SETA passa pelo cache Redis em segundo plano (status processing →
# ready); aqui calcula na hora, sem Redis.
cache.buscar_ou_iniciar = lambda chave, calcular: {"status": "ready", "data": calcular()}

CLIENTES_FALSOS = [
    {
        "pessoa": "00000001",
        "codigo": "00000001",
        "nome": "CLIENTE TESTE",
        "telefone1": "",
        "telefone2": "5563999990001",
        "telefone3": "",
        "cpfcnpj": "12345678901",
        "status": "A",
        "loja_cadastro": "01",
        "salario": Decimal("1000"),
        "limite_rotativo": Decimal("500"),
        "nascimento": None,
        "cadastro": None,
        "valor_pago": Decimal("350"),  # < 400 → ESPECIAL
        "qtd_compras": 3,
        "ultima_compra": None,
        "dias_atraso": 21,  # faixa "21 A 30"
        "qtd_titulos": 1,
        "valor_em_aberto": Decimal("150"),
        "qtd_parcelas_cobranca": 1,
        "valor_cobrar": Decimal("155"),
        "valor_atraso_original": Decimal("150"),
        "valor_atraso_juros": Decimal("155"),
        "vencimento_mais_antigo": None,
        "lojas": "01",
        "portadores": "001",
        "spc_restricao": "nao",
    }
]


def _seta_falso(**kwargs):
    """Simula buscar_base_cobranca do SETA."""
    return list(CLIENTES_FALSOS)


with Session() as db:
    with patch("app.cobranca_base.seta_client.buscar_base_cobranca", side_effect=_seta_falso):
        resultado = cobranca_base.buscar_base(db, somente_regra_whatsapp=False)["data"]

assert len(resultado) == 1
assert resultado[0]["cluster"] == "ESPECIAL"
assert resultado[0]["faixa"] == "21 A 30"
print("  (a) cluster/faixa vêm do banco (default): OK")

# (a) muda valor_min de ESPECIAL no banco e recarrega → classificação muda
cfg_antes = client.get("/config/cobranca", headers=headers).json()
cid_especial = next(c["id"] for c in cfg_antes["clusters"] if c["nome"] == "ESPECIAL")
# Alterar ESPECIAL para começar em 500 (cliente com valor_pago=350 ficaria sem cluster se valor_min=0 de ESPECIAL sumir)
# Na prática não podemos tirar valor_min=0 (validação proibiria), então mudamos apenas para verificar que
# a classificação usa o banco. Vamos trocar POTENCIAL para 300 e verificar o resultado.
novos_clusters_a = [c for c in cfg_antes["clusters"]]
for nc in novos_clusters_a:
    if nc["nome"] == "POTENCIAL":
        nc["valor_min"] = "300"  # reduz de 400 para 300
resp = client.put("/config/cobranca/clusters", json=novos_clusters_a, headers=headers)
assert resp.status_code == 200

with Session() as db:
    with patch("app.cobranca_base.seta_client.buscar_base_cobranca", side_effect=_seta_falso):
        resultado2 = cobranca_base.buscar_base(db, somente_regra_whatsapp=False)["data"]

# valor_pago=350 >= 300 → agora é POTENCIAL
assert resultado2[0]["cluster"] == "POTENCIAL", f"esperado POTENCIAL, got {resultado2[0]['cluster']}"
print("  (a) cluster muda com valor_min no banco: OK")

# Restaurar clusters
resp = client.put("/config/cobranca/clusters", json=[
    {"nome": "ESPECIAL", "valor_min": "0"},
    {"nome": "POTENCIAL", "valor_min": "400"},
    {"nome": "EM POTENCIAL", "valor_min": "1000"},
    {"nome": "ALTO POTENCIAL", "valor_min": "1500"},
    {"nome": "BEST SELLER", "valor_min": "3000"},
    {"nome": "HEAVY USER", "valor_min": "7000"},
], headers=headers)
assert resp.status_code == 200
# Restaurar matriz
cfg_r2 = client.get("/config/cobranca", headers=headers).json()
c_ids_r = {c["nome"]: c["id"] for c in cfg_r2["clusters"]}
f_ids_r = {f["nome"]: f["id"] for f in cfg_r2["faixas"]}
nova_m2 = []
for cn, fns in matriz_padrao_input.items():
    if cn not in c_ids_r:
        continue
    for fn in fns:
        if fn in f_ids_r:
            nova_m2.append({"cluster_id": c_ids_r[cn], "faixa_id": f_ids_r[fn]})
resp = client.put("/config/cobranca/matriz", json=nova_m2, headers=headers)
assert resp.status_code == 200

# (b) somente_regra_whatsapp filtra pela matriz do banco
# ESPECIAL + "21 A 30" NÃO está na matriz WhatsApp (só ESPECIAL recebe em certas faixas)
# Verifica que somente_regra_whatsapp=True filtra o cliente
with Session() as db:
    with patch("app.cobranca_base.seta_client.buscar_base_cobranca", side_effect=_seta_falso):
        resultado3 = cobranca_base.buscar_base(db, somente_regra_whatsapp=True)["data"]

# ESPECIAL + "21 A 30" está na matriz (segundo TAREFA.md)
assert any(c["cluster"] == "ESPECIAL" and c["faixa"] == "21 A 30" for c in resultado3), (
    "ESPECIAL/21 A 30 deveria entrar no WhatsApp"
)
print("  (b) somente_regra_whatsapp filtra pela matriz: OK")

# (c) faixas e dias_exatos acompanham as faixas do banco
# Criar nova faixa "200 A 250" no banco e verificar que cobranca_base a usa
cfg_faixas_atuais = client.get("/config/cobranca", headers=headers).json()["faixas"]
cfg_faixas_com_nova = []
for f in cfg_faixas_atuais:
    if f["nome"] == "151+":
        cfg_faixas_com_nova.append({**f, "dia_max": 199})
    else:
        cfg_faixas_com_nova.append(f)
cfg_faixas_com_nova.append({"nome": "200 A 250", "dia_min": 200, "dia_max": 250})
resp = client.put("/config/cobranca/faixas", json=cfg_faixas_com_nova, headers=headers)
assert resp.status_code == 200, f"PUT faixas com nova falhou: {resp.text}"

CLIENTES_NOVA_FAIXA = [{**CLIENTES_FALSOS[0], "dias_atraso": 220}]

def _seta_nova_faixa(**kwargs):
    faixas_param = kwargs.get("faixas", [])
    # verifica que a nova faixa (200, 250) foi passada
    assert any(dmin == 200 for dmin, _ in faixas_param), f"Faixa 200 A 250 não foi passada ao SETA: {faixas_param}"
    return CLIENTES_NOVA_FAIXA

with Session() as db:
    with patch("app.cobranca_base.seta_client.buscar_base_cobranca", side_effect=_seta_nova_faixa):
        resultado4 = cobranca_base.buscar_base(db, somente_regra_whatsapp=False)["data"]

assert resultado4[0]["faixa"] == "200 A 250"

def _seta_primeiro_dia(**kwargs):
    dias = kwargs.get("dias_exatos", [])
    assert 200 in dias, f"200 não está em dias_exatos: {dias}"
    return CLIENTES_NOVA_FAIXA

with Session() as db:
    with patch("app.cobranca_base.seta_client.buscar_base_cobranca", side_effect=_seta_primeiro_dia):
        cobranca_base.buscar_base(db, somente_regra_whatsapp=False, apenas_primeiro_dia=True)

print("  (c) faixas e dias_exatos acompanham banco (nova faixa): OK")

# (d) juros enviado ao SETA é o do banco
resp = client.put("/config/cobranca/parametros", json={
    "juros_mes_percentual": "5.00",
    "multa_percentual": "1.0",
    "dias_min_juros": 1,
}, headers=headers)
assert resp.status_code == 200

juros_recebido = {}

def _seta_juros(**kwargs):
    juros_recebido["juros"] = kwargs.get("juros")
    return []

with Session() as db:
    with patch("app.cobranca_base.seta_client.buscar_base_cobranca", side_effect=_seta_juros):
        cobranca_base.buscar_base(db, somente_regra_whatsapp=False)

assert juros_recebido["juros"] is not None
assert juros_recebido["juros"].juros_mes_percentual == Decimal("5.00")
assert juros_recebido["juros"].dias_min == 1
print("  (d) juros do banco enviado ao SETA: OK")

# Restaurar parâmetros
resp = client.put("/config/cobranca/parametros", json={
    "juros_mes_percentual": "15.99",
    "multa_percentual": "2",
    "dias_min_juros": 3,
}, headers=headers)
assert resp.status_code == 200

# Restaurar faixas (sem a 200 A 250)
resp = client.put("/config/cobranca/faixas", json=[
    {"nome": "-1", "dia_min": -1, "dia_max": 1},
    {"nome": "2", "dia_min": 2, "dia_max": 2},
    {"nome": "3 A 10", "dia_min": 3, "dia_max": 10},
    {"nome": "11 A 20", "dia_min": 11, "dia_max": 20},
    {"nome": "21 A 30", "dia_min": 21, "dia_max": 30},
    {"nome": "31 A 40", "dia_min": 31, "dia_max": 40},
    {"nome": "41 A 60", "dia_min": 41, "dia_max": 60},
    {"nome": "61 A 80", "dia_min": 61, "dia_max": 80},
    {"nome": "81 A 100", "dia_min": 81, "dia_max": 100},
    {"nome": "101 A 120", "dia_min": 101, "dia_max": 120},
    {"nome": "121 A 140", "dia_min": 121, "dia_max": 140},
    {"nome": "141 A 150", "dia_min": 141, "dia_max": 150},
    {"nome": "151+", "dia_min": 151, "dia_max": None},
], headers=headers)
assert resp.status_code == 200

client.__exit__(None, None, None)

# --- 5. Relatório: montar_matriz com faixa/cluster novo ---

print("=== 5. Relatório ===")

from app.cobranca_regras import Cluster, FaixaAtraso, Regras, ParametrosJuros
from app import cobranca_relatorio

faixas_extra = REGRAS_PADRAO.faixas + (FaixaAtraso("NOVA FAIXA", 200, 250),)
clusters_extra = REGRAS_PADRAO.clusters + (Cluster("NOVO CLUSTER", Decimal("50000")),)

regras_extra_faixa = Regras(
    clusters=REGRAS_PADRAO.clusters,
    faixas=faixas_extra,
    whatsapp=REGRAS_PADRAO.whatsapp,
    juros=REGRAS_PADRAO.juros,
)
regras_extra_cluster = Regras(
    clusters=clusters_extra,
    faixas=REGRAS_PADRAO.faixas,
    whatsapp=REGRAS_PADRAO.whatsapp,
    juros=REGRAS_PADRAO.juros,
)

clientes_teste = [
    {"cluster": "ESPECIAL", "faixa": "NOVA FAIXA", "spc_restricao": "nao"},
    {"cluster": "NOVO CLUSTER", "faixa": "151+", "spc_restricao": "nao"},
]

matriz_nova_faixa = cobranca_relatorio.montar_matriz(clientes_teste, regras_extra_faixa)
assert "NOVA FAIXA" in matriz_nova_faixa["celulas"]["ESPECIAL"], "NOVA FAIXA deveria aparecer como coluna"
assert "NOVA FAIXA" in matriz_nova_faixa["total_por_faixa"]
print("  montar_matriz com nova faixa como coluna: OK")

matriz_novo_cluster = cobranca_relatorio.montar_matriz(clientes_teste, regras_extra_cluster)
assert "NOVO CLUSTER" in matriz_novo_cluster["celulas"], "NOVO CLUSTER deveria aparecer como linha"
print("  montar_matriz com novo cluster como linha: OK")

print("\n===================================")
print("OK")
