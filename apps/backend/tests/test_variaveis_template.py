"""Script de teste para o módulo de fontes de variáveis de templates (TASK G).

Executa com asserts simples, sem pytest. Encerra imprimindo 'OK'.
"""

import io
import os
import tempfile
from datetime import date
from decimal import Decimal

import openpyxl
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient

# Garante variáveis de ambiente para inicialização e conexão com agy_vars
TEST_DB_URL = "postgresql+psycopg://postgres:t@localhost:15432/agy_vars"
os.environ["DATABASE_URL"] = TEST_DB_URL
os.environ["JWT_SECRET"] = "segredo-de-teste-longo-o-suficiente-123456"
os.environ["ADMIN_PASSWORD"] = "senha-admin-teste-12345"
temp_media_dir = tempfile.mkdtemp()
os.environ["MEDIA_DIR"] = temp_media_dir

import os as _os
from cryptography.fernet import Fernet as _Fernet

_os.environ.setdefault("ENCRYPTION_KEY", _Fernet.generate_key().decode())  # o backend não sobe sem ela
import app.variaveis_template as vt
from app.main import BACKEND_DIR, app
from app.models import FaixaVariableMapping, QueueItem
from app.schemas import FaixaVariableMappingIn

# ==============================================================================
# 1. TESTES PUROS (app/variaveis_template.py)
# ==============================================================================

# 1.1 Expressão básica com substituição
assert (
    vt.renderizar_expressao(
        "{codigo} - {nome}",
        {"codigo": "00123456", "nome": "MARIA DA SILVA"},
    )
    == "00123456 - MARIA DA SILVA"
)

# 1.2 Resolução case-insensitive e whitespace-insensitive
assert vt.renderizar_expressao("{ NOME }", {"nome": "MARIA DA SILVA"}) == "MARIA DA SILVA"
assert vt.renderizar_expressao("{Nome}", {"nome": "MARIA DA SILVA"}) == "MARIA DA SILVA"
assert vt.renderizar_expressao("{Primeiro Nome}", {"primeiro_nome": "Maria"}) == "Maria"

# 1.3 Placeholder desconhecido
try:
    vt.renderizar_expressao("{desconhecido}", {"nome": "Maria"}, estrito=True)
    assert False, "Deveria ter lançado PlaceholderDesconhecido"
except vt.PlaceholderDesconhecido as exc:
    assert "desconhecido" in str(exc)

assert vt.renderizar_expressao("{desconhecido}", {"nome": "Maria"}, estrito=False) == ""

# 1.4 Normalização de espaços em branco para a Meta
assert vt.normalizar_para_meta("A\n\n  B\t C") == "A B C"

# 1.5 Formatação de moeda pt-BR sem dependência de locale
assert vt.formatar_moeda(Decimal("1234.5")) == "1.234,50"
assert vt.formatar_moeda("0") == "0,00"
assert vt.formatar_moeda(Decimal("1234567.891")) == "1.234.567,89"

# 1.6 Formatação de data
assert vt.formatar_data(date(2026, 9, 21)) == "21/09/2026"

# 1.7 contexto_cliente retorna as 14 chaves do catálogo como str
ctx = vt.contexto_cliente(
    {
        "codigo": "123456",
        "nome": "Maria da Silva Santos",
        "cpfcnpj": "5998224725",
        "celular": "5511999998888",
        "cluster": "ESPECIAL",
        "faixa": "11 A 20",
        "dias_atraso": 15,
        "qtd_parcelas_cobranca": 2,
        "valor_atraso": Decimal("1234.56"),
        "valor_em_aberto": Decimal("1200.00"),
        "vencimento_mais_antigo": date(2026, 9, 21),
    }
)
assert len(ctx) == 14
assert all(isinstance(v, str) for v in ctx.values())
assert ctx["codigo"] == "00123456"
assert ctx["primeiro_nome"] == "Maria"
assert ctx["cpf"] == "059.982.247-25"
assert ctx["valor_atraso"] == "1.234,56"
assert "valor_cobrar" not in ctx
assert ctx["valor_em_aberto"] == "1.200,00"
assert ctx["vencimento"] == "21/09/2026"

# 1.8 Validação de sintaxe
for invalido in ["{a", "a}", "{}", "{{a}}", "sem placeholder"]:
    erro = vt.validar_sintaxe(invalido)
    assert erro is not None, f"Esperava erro para sintaxe {invalido!r}"

assert vt.validar_sintaxe("{a} - {b}") is None

# 1.9 resolver_variaveis com os 3 tipos em uma única chamada
fontes = [
    vt.FonteVariavel("v_col", "coluna", "Nome Coluna"),
    vt.FonteVariavel("v_campo", "campo_cliente", "codigo"),
    vt.FonteVariavel("v_expr", "expressao", "{codigo} - {nome}"),
]
ctx_fontes = {"Nome Coluna": "Valor Coluna", "codigo": "00123456", "nome": "Maria"}
res_fontes = vt.resolver_variaveis(fontes, ctx_fontes)
assert res_fontes == {
    "v_col": "Valor Coluna",
    "v_campo": "00123456",
    "v_expr": "00123456 - Maria",
}


# ==============================================================================
# 2. TESTE DE MIGRATION (Alembic)
# ==============================================================================

alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))

# Garante estado na revisão anterior para provar o preenchimento de linhas legadas
command.upgrade(alembic_cfg, "d3dec284035d")

import psycopg

with psycopg.connect("postgresql://postgres:t@localhost:15432/agy_vars") as conn:
    with conn.cursor() as cur:
        # Cria dados pré-existentes na revisão antiga
        cur.execute(
            """
            INSERT INTO templates (id, name, meta_template_name, language, category, header_type, body_text, status, created_at, updated_at)
            VALUES ('t-mig-test', 'T Mig', 't_mig', 'pt_BR', 'UTILITY', 'none', 'msg {{1}}', 'approved', NOW(), NOW())
            ON CONFLICT (id) DO NOTHING;
            """
        )
        cur.execute(
            """
            INSERT INTO template_variables (id, template_id, position, internal_name)
            VALUES ('tv-mig-test', 't-mig-test', 1, 'var1')
            ON CONFLICT (id) DO NOTHING;
            """
        )
        cur.execute(
            """
            INSERT INTO faixas (id, name, template_id, active, last_number_index, upload_field_mapping, created_at)
            VALUES ('f-mig-test', 'Faixa Mig', 't-mig-test', true, 0, '{}'::json, NOW())
            ON CONFLICT (id) DO NOTHING;
            """
        )
        cur.execute(
            """
            INSERT INTO faixa_variable_mappings (id, faixa_id, template_variable_id, column_name)
            VALUES ('fvm-mig-test', 'f-mig-test', 'tv-mig-test', 'ColunaLegada')
            ON CONFLICT (id) DO UPDATE SET column_name = 'ColunaLegada';
            """
        )
    conn.commit()

# Upgrade para a nova migration
command.upgrade(alembic_cfg, "head")

# Verifica se a linha existente recebeu fonte_tipo='coluna'
with psycopg.connect("postgresql://postgres:t@localhost:15432/agy_vars") as conn:
    with conn.cursor() as cur:
        cur.execute("SELECT fonte_tipo, column_name, expressao FROM faixa_variable_mappings WHERE id = 'fvm-mig-test'")
        row = cur.fetchone()
        assert row is not None
        assert row[0] == "coluna", f"Esperava fonte_tipo='coluna', obteve {row[0]!r}"
        assert row[1] == "ColunaLegada"
        assert row[2] is None

# Ciclo downgrade base -> upgrade head
command.downgrade(alembic_cfg, "base")
command.upgrade(alembic_cfg, "head")

# Checagem de ausência de diffs entre models.py e o schema atual do banco
command.check(alembic_cfg)


# ==============================================================================
# 3. TESTES DE INTEGRAÇÃO (TestClient + endpoints da API)
# ==============================================================================

with TestClient(app) as client:
    # 3.1 Endpoint de catálogo: 401 sem login
    resp = client.get("/templates/variaveis/campos")
    assert resp.status_code == 401

    # Login
    login_resp = client.post(
        "/auth/login",
        json={"email": "admin@topfama.com.br", "password": "senha-admin-teste-12345"},
    )
    assert login_resp.status_code == 200
    token = login_resp.json()["access_token"]
    auth_headers = {"Authorization": f"Bearer {token}"}

    # 3.2 Endpoint de catálogo: 200 com login, campos e exemplos presentes, não sombreado
    resp = client.get("/templates/variaveis/campos", headers=auth_headers)
    assert resp.status_code == 200
    campos_out = resp.json()
    assert len(campos_out) == 14
    campos_dict = {item["campo"]: item for item in campos_out}
    assert "codigo" in campos_dict
    assert campos_dict["codigo"]["rotulo"] == "Código SETA"
    assert campos_dict["codigo"]["exemplo"] == "00123456"
    assert "valor_cobrar" not in campos_dict
    assert campos_dict["valor_atraso"]["exemplo"] == "1.100,00"

    # Cria número de WhatsApp para as faixas
    num_resp = client.post(
        "/numbers",
        json={
            "waba_id": "waba_integ_test",
            "phone_number_id": "phone_integ_test",
            "display_phone_number": "5511999998888",
            "label": "Numero Teste",
        },
        headers=auth_headers,
    )
    assert num_resp.status_code == 201
    number_id = num_resp.json()["id"]

    # Cria template com 2 variáveis
    tmpl_resp = client.post(
        "/templates",
        json={
            "name": "Template Integ",
            "meta_template_name": "tmpl_integ_vars",
            "category": "UTILITY",
            "body_text": "Olá {{1}}, seu valor é {{2}}.",
            "variables": [
                {"position": 1, "internal_name": "codigo_e_nome"},
                {"position": 2, "internal_name": "valor_cobrar"},
            ],
        },
        headers=auth_headers,
    )
    assert tmpl_resp.status_code == 201
    tmpl = tmpl_resp.json()
    v1_id = tmpl["variables"][0]["id"]
    v2_id = tmpl["variables"][1]["id"]

    # Faixa só aceita template aprovado pela Meta; aqui não há sync, aprova direto no banco
    from app.database import SessionLocal
    from app.models import Template, TemplateStatus

    with SessionLocal() as db_aprov:
        db_aprov.get(Template, tmpl["id"]).status = TemplateStatus.approved
        db_aprov.commit()

    # 3.3 Criação de faixa: fonte_tipo inválido deve retornar erro (422 / 400)
    resp_inv = client.post(
        "/faixas",
        json={
            "name": "Faixa Invalida",
            "template_id": tmpl["id"],
            "whatsapp_number_ids": [number_id],
            "variable_mappings": [
                {"template_variable_id": v1_id, "fonte_tipo": "invalido", "column_name": "x"},
                {"template_variable_id": v2_id, "fonte_tipo": "coluna", "column_name": "y"},
            ],
        },
        headers=auth_headers,
    )
    assert resp_inv.status_code in (400, 422)

    # 3.4 Criação de faixa com cada fonte_tipo válido
    # a) coluna (estilo tradicional)
    resp_col = client.post(
        "/faixas",
        json={
            "name": "Faixa Coluna",
            "template_id": tmpl["id"],
            "whatsapp_number_ids": [number_id],
            "variable_mappings": [
                {"template_variable_id": v1_id, "fonte_tipo": "coluna", "column_name": "ColA"},
                {"template_variable_id": v2_id, "fonte_tipo": "coluna", "column_name": "ColB"},
            ],
        },
        headers=auth_headers,
    )
    assert resp_col.status_code == 201
    mappings_col = {m["template_variable_id"]: m for m in resp_col.json()["variable_mappings"]}
    assert mappings_col[v1_id]["fonte_tipo"] == "coluna"
    assert mappings_col[v1_id]["column_name"] == "ColA"

    # b) campo_cliente
    resp_campo = client.post(
        "/faixas",
        json={
            "name": "Faixa Campo",
            "template_id": tmpl["id"],
            "whatsapp_number_ids": [number_id],
            "variable_mappings": [
                {"template_variable_id": v1_id, "fonte_tipo": "campo_cliente", "column_name": "codigo"},
                {"template_variable_id": v2_id, "fonte_tipo": "campo_cliente", "column_name": "valor_atraso"},
            ],
        },
        headers=auth_headers,
    )
    assert resp_campo.status_code == 201
    mappings_campo = {m["template_variable_id"]: m for m in resp_campo.json()["variable_mappings"]}
    assert mappings_campo[v1_id]["fonte_tipo"] == "campo_cliente"
    assert mappings_campo[v1_id]["column_name"] == "codigo"

    # c) expressao
    resp_expr = client.post(
        "/faixas",
        json={
            "name": "Faixa Expressao",
            "template_id": tmpl["id"],
            "whatsapp_number_ids": [number_id],
            "variable_mappings": [
                {"template_variable_id": v1_id, "fonte_tipo": "expressao", "expressao": "{codigo} - {nome}"},
                {"template_variable_id": v2_id, "fonte_tipo": "coluna", "column_name": "Valor"},
            ],
        },
        headers=auth_headers,
    )
    assert resp_expr.status_code == 201
    mappings_expr = {m["template_variable_id"]: m for m in resp_expr.json()["variable_mappings"]}
    assert mappings_expr[v1_id]["fonte_tipo"] == "expressao"
    assert mappings_expr[v1_id]["expressao"] == "{codigo} - {nome}"
    assert mappings_expr[v1_id]["column_name"] is None

    # 3.5 Testes de upload de planilha (.xlsx construído em memória com openpyxl)
    def criar_xlsx_bytes(linhas: list[list]) -> bytes:
        wb = openpyxl.Workbook()
        ws = wb.active
        for linha in linhas:
            ws.append(linha)
        buf = io.BytesIO()
        wb.save(buf)
        return buf.getvalue()

    planilha_bytes = criar_xlsx_bytes(
        [
            ["Codigo", "Nome", "CPF", "Celular", "Valor", "Saldo"],
            ["123456", "Maria da Silva", "52998224725", "11999998888", "100.00", "250.00"],
        ]
    )

    # Cria faixa dedicada para teste de upload
    faixa_up_resp = client.post(
        "/faixas",
        json={
            "name": "Faixa Para Upload",
            "template_id": tmpl["id"],
            "whatsapp_number_ids": [number_id],
            "variable_mappings": [
                {"template_variable_id": v1_id, "fonte_tipo": "coluna", "column_name": "Nome"},
                {"template_variable_id": v2_id, "fonte_tipo": "coluna", "column_name": "Saldo"},
            ],
        },
        headers=auth_headers,
    )
    faixa_up_id = faixa_up_resp.json()["id"]

    # a) Expressão apontando para coluna inexistente -> HTTP 400 nomeando variável e coluna
    mapping_col_errada = (
        '{"celular":"Celular","codigo_cliente":"Codigo","nome":"Nome","cpf":"CPF","valor":"Valor",'
        f'"variables":{{"{v2_id}":"Saldo"}},"expressoes":{{"{v1_id}":"{{Codigo}} - {{ColunaFantasma}}"}}'
        "}"
    )
    upload_err_resp = client.post(
        f"/faixas/{faixa_up_id}/uploads",
        files={"file": ("base.xlsx", planilha_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapping": mapping_col_errada},
        headers=auth_headers,
    )
    assert upload_err_resp.status_code == 400
    assert "ColunaFantasma" in upload_err_resp.json()["detail"]
    assert "codigo_e_nome" in upload_err_resp.json()["detail"]

    # b) Upload com expressão {Codigo} - {Nome} -> gravado em QueueItem.variables_json
    mapping_com_expr = (
        '{"celular":"Celular","codigo_cliente":"Codigo","nome":"Nome","cpf":"CPF","valor":"Valor",'
        f'"variables":{{"{v2_id}":"Saldo"}},"expressoes":{{"{v1_id}":"{{Codigo}} - {{Nome}}"}}'
        "}"
    )
    upload_ok_resp = client.post(
        f"/faixas/{faixa_up_id}/uploads",
        files={"file": ("base.xlsx", planilha_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapping": mapping_com_expr},
        headers=auth_headers,
    )
    assert upload_ok_resp.status_code == 200
    assert upload_ok_resp.json()["accepted_count"] == 1

    queue_resp = client.get(f"/faixas/{faixa_up_id}/queue", headers=auth_headers)
    assert queue_resp.status_code == 200
    queue_items = queue_resp.json()
    assert len(queue_items) >= 1

    # Busca o item inserido diretamente no banco para validar o variables_json
    with psycopg.connect("postgresql://postgres:t@localhost:15432/agy_vars") as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT variables_json FROM cobranca_fila WHERE faixa_id = %s", (faixa_up_id,))
            q_row = cur.fetchone()
            assert q_row is not None
            vars_json = q_row[0]
            assert vars_json["codigo_e_nome"] == "123456 - Maria da Silva"
            assert vars_json["valor_cobrar"] == "250.00"

    # c) Upload no formato antigo (apenas variables, sem expressoes) continua funcionando
    faixa_antiga_resp = client.post(
        "/faixas",
        json={
            "name": "Faixa Formato Antigo",
            "template_id": tmpl["id"],
            "whatsapp_number_ids": [number_id],
            "variable_mappings": [
                {"template_variable_id": v1_id, "fonte_tipo": "coluna", "column_name": "Nome"},
                {"template_variable_id": v2_id, "fonte_tipo": "coluna", "column_name": "Saldo"},
            ],
        },
        headers=auth_headers,
    )
    faixa_antiga_id = faixa_antiga_resp.json()["id"]

    planilha_antiga_bytes = criar_xlsx_bytes(
        [
            ["Codigo", "Nome", "CPF", "Celular", "Valor", "Saldo"],
            ["654321", "Joao da Silva", "52998224725", "11988887777", "50.00", "75.00"],
        ]
    )
    mapping_antigo = (
        '{"celular":"Celular","codigo_cliente":"Codigo","nome":"Nome","cpf":"CPF","valor":"Valor",'
        f'"variables":{{"{v1_id}":"Nome","{v2_id}":"Saldo"}}'
        "}"
    )
    upload_antigo_resp = client.post(
        f"/faixas/{faixa_antiga_id}/uploads",
        files={"file": ("base_antiga.xlsx", planilha_antiga_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        data={"mapping": mapping_antigo},
        headers=auth_headers,
    )
    assert upload_antigo_resp.status_code == 200
    assert upload_antigo_resp.json()["accepted_count"] == 1

    with psycopg.connect("postgresql://postgres:t@localhost:15432/agy_vars") as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT variables_json FROM cobranca_fila WHERE faixa_id = %s", (faixa_antiga_id,))
            q_row = cur.fetchone()
            assert q_row is not None
            vars_json = q_row[0]
            assert vars_json["codigo_e_nome"] == "Joao"  # nome sempre reduzido ao primeiro nome
            assert vars_json["valor_cobrar"] == "75.00"

print("OK")
