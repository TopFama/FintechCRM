"""Validação das funcionalidades de tokens da Meta e Chatwoot inbox ID (Tarefa D+H).

Executado com asserts simples sem pytest, encerrando com 'OK'.
"""

import os
import tempfile
from datetime import datetime, timedelta

from cryptography.fernet import Fernet

# Configura variáveis de ambiente antes de carregar o app
os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres:t@localhost:15432/agy_k")
os.environ["JWT_SECRET"] = "super-secret-key-for-meta-tokens-test-12345"
os.environ["ADMIN_PASSWORD"] = "test-admin-password-xyz-987"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp()
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()

import httpx
from fastapi.testclient import TestClient

from app import crypto, models
from app.config import settings
from app.database import SessionLocal
from app.main import app
from app.meta_client import MetaAPIError, MetaClient, MetaTokenConfigError, token_da_waba


# 1. Configuração do MockTransport para simular a Meta Graph API
def mock_meta_handler(request: httpx.Request) -> httpx.Response:
    auth_header = request.headers.get("authorization", "")
    token = auth_header.replace("Bearer ", "").strip()

    if request.url.path.endswith("/message_templates"):
        waba = request.url.path.split("/")[-2]
        return httpx.Response(
            200,
            json={"data": [{"id": f"TPL_{waba}", "name": f"cobranca_{waba}", "language": "pt_BR", "category": "UTILITY",
                            "status": "APPROVED", "components": [{"type": "BODY", "text": "Olá {{1}}, parcela de {{2}}"}]}]},
        )

    if request.url.path.endswith("/phone_numbers"):
        waba = request.url.path.split("/")[-2]
        if token == "TOKEN_INVALIDO_META" or waba == "999":
            return httpx.Response(
                400,
                json={"error": {"message": "Unsupported get request. Object does not exist", "type": "GraphMethodException"}},
            )
        return httpx.Response(
            200,
            json={
                "data": [
                    {"id": "PNID_1", "display_phone_number": "+55 63 99999-0001", "verified_name": "TopFama Palmas",
                     "quality_rating": "GREEN", "status": "CONNECTED"},
                    {"id": "PNID_2", "display_phone_number": "+55 63 99999-0002", "verified_name": "TopFama Araguaína",
                     "quality_rating": "YELLOW", "status": "CONNECTED"},
                ]
            },
        )

    if "/me" in str(request.url):
        if token == "TOKEN_INVALIDO_META":
            return httpx.Response(
                400,
                json={
                    "error": {
                        "message": "Invalid OAuth access token - Cannot parse access token",
                        "type": "OAuthException",
                        "code": 190,
                    }
                },
            )
        return httpx.Response(200, json={"id": "9988776655", "name": "TopFama WhatsApp Oficial"})

    return httpx.Response(404, json={"error": {"message": "Not Found"}})


MetaClient.default_transport = httpx.MockTransport(mock_meta_handler)

client = TestClient(app)

from app.security import hash_password

# Em banco novo as tabelas só existem depois das migrations; a limpeza abaixo depende delas.
from app.main import _run_migrations  # noqa: E402

_run_migrations()

db = SessionLocal()
try:
    # Limpa números e tokens criados por execuções anteriores de teste
    test_phones = [
        "phone_inativo_test", "phone_inexistente_test", "phone_bad_inbox",
        "phone_ok_test_100", "phone_waba_antigo", "phone_waba_novo"
    ]
    db.query(models.WhatsappNumber).filter(
        models.WhatsappNumber.phone_number_id.in_(test_phones)
    ).delete(synchronize_session=False)
    db.query(models.MetaToken).delete(synchronize_session=False)

    admin_user = db.query(models.User).filter(models.User.email == settings.admin_email).first()
    if admin_user:
        admin_user.password_hash = hash_password("test-admin-password-xyz-987")
    else:
        admin_user = models.User(email=settings.admin_email, password_hash=hash_password("test-admin-password-xyz-987"))
        db.add(admin_user)
    db.commit()
finally:
    db.close()

# 2. Login para obter token de autenticação
login_resp = client.post(
    "/auth/login",
    json={"email": "admin@topfama.com.br", "password": "test-admin-password-xyz-987"},
)
assert login_resp.status_code == 200, f"Falha no login: {login_resp.text}"
auth_token = login_resp.json()["access_token"]
headers = {"Authorization": f"Bearer {auth_token}"}

# 3. Teste: 401 sem autenticação
resp_401 = client.get("/meta-tokens")
assert resp_401.status_code == 401, f"Esperado 401 sem login, recebido {resp_401.status_code}"

resp_401_post = client.post("/meta-tokens", json={"nome": "X", "token": "Y"})
assert resp_401_post.status_code == 401

resp_401_patch = client.patch("/meta-tokens/fake-id", json={"nome": "X"})
assert resp_401_patch.status_code == 401

resp_401_delete = client.delete("/meta-tokens/fake-id")
assert resp_401_delete.status_code == 401

resp_401_test = client.post("/meta-tokens/fake-id/testar")
assert resp_401_test.status_code == 401

# 4. Teste: Validação de campos vazios ao criar token (400)
resp_empty_nome = client.post("/meta-tokens", json={"nome": "   ", "token": "token123", "waba_id": "1111"}, headers=headers)
assert resp_empty_nome.status_code == 400, f"Esperado 400 para nome vazio, obtido {resp_empty_nome.status_code}"

resp_empty_token = client.post("/meta-tokens", json={"nome": "Token 1", "token": "   ", "waba_id": "1111"}, headers=headers)
assert resp_empty_token.status_code == 400, f"Esperado 400 para token vazio, obtido {resp_empty_token.status_code}"

# 5. Teste: Criação bem-sucedida e segredo nunca exposto na API e no banco
secret_token_sp = "EAAX_topfama_segredo_token_sp_4321"
resp_create_1 = client.post(
    "/meta-tokens",
    json={"nome": "Token Cobrança SP", "token": secret_token_sp, "waba_id": "1111"},
    headers=headers,
)
assert resp_create_1.status_code == 201, f"Erro ao criar token: {resp_create_1.text}"
token_1 = resp_create_1.json()
token_1_id = token_1["id"]
assert token_1["nome"] == "Token Cobrança SP"
assert token_1["ultimos4"] == "4321"
assert token_1["ativo"] is True
assert token_1["numeros_vinculados"] == 0

# Garantir que o valor em texto puro do token NÃO está na resposta
assert secret_token_sp not in resp_create_1.text
assert "token_cifrado" not in token_1
assert "token" not in token_1

# Garantir que no banco de dados está apenas cifrado, nunca em texto puro
db = SessionLocal()
try:
    db_token = db.get(models.MetaToken, token_1_id)
    assert db_token is not None
    assert secret_token_sp not in db_token.token_cifrado
    assert crypto.decifrar(db_token.token_cifrado) == secret_token_sp
finally:
    db.close()

# 6. Teste: 409 Duplicata do mesmo valor de token
resp_dup = client.post(
    "/meta-tokens",
    json={"nome": "Outro Nome Mesmo Token", "token": secret_token_sp, "waba_id": "1111"},
    headers=headers,
)
assert resp_dup.status_code == 409, f"Esperado 409 para token duplicado, obtido {resp_dup.status_code}"

resp_dup_strip = client.post(
    "/meta-tokens",
    json={"nome": "Outro Nome Com Espaços", "token": f"  {secret_token_sp}  ", "waba_id": "1111"},
    headers=headers,
)
assert resp_dup_strip.status_code == 409

# 7. Teste: Listar tokens
secret_token_rj = "EAAX_topfama_segredo_token_rj_9876"
resp_create_2 = client.post(
    "/meta-tokens",
    json={"nome": "Token Cobrança RJ", "token": secret_token_rj, "waba_id": "1111"},
    headers=headers,
)
assert resp_create_2.status_code == 201
token_2_id = resp_create_2.json()["id"]

resp_list = client.get("/meta-tokens", headers=headers)
assert resp_list.status_code == 200
tokens_list = resp_list.json()
assert len(tokens_list) >= 2
assert secret_token_sp not in resp_list.text
assert secret_token_rj not in resp_list.text

# 8. Teste: PATCH /meta-tokens/{id}
resp_patch = client.patch(
    f"/meta-tokens/{token_1_id}",
    json={"nome": "Token Cobrança SP Atualizado", "ativo": False},
    headers=headers,
)
assert resp_patch.status_code == 200
assert resp_patch.json()["nome"] == "Token Cobrança SP Atualizado"
assert resp_patch.json()["ativo"] is False

# Reativar token 1
resp_reactivate = client.patch(
    f"/meta-tokens/{token_1_id}",
    json={"ativo": True},
    headers=headers,
)
assert resp_reactivate.status_code == 200
assert resp_reactivate.json()["ativo"] is True

# 9. Teste: Números - rejeitar token inativo e token inexistente (400)
# Desativa token 2 para testar rejeição
client.patch(f"/meta-tokens/{token_2_id}", json={"ativo": False}, headers=headers)

resp_num_inactive_token = client.post(
    "/numbers",
    json={
        "waba_id": "waba_teste_sp",
        "phone_number_id": "phone_inativo_test",
        "display_phone_number": "+55 11 91111-0000",
        "label": "Número Invalido",
        "meta_token_id": token_2_id,
    },
    headers=headers,
)
assert resp_num_inactive_token.status_code == 400, f"Esperado 400 para token inativo: {resp_num_inactive_token.text}"

resp_num_nonexistent_token = client.post(
    "/numbers",
    json={
        "waba_id": "waba_teste_sp",
        "phone_number_id": "phone_inexistente_test",
        "display_phone_number": "+55 11 91111-0001",
        "meta_token_id": "id-que-nao-existe",
    },
    headers=headers,
)
assert resp_num_nonexistent_token.status_code == 400

# Chatwoot inbox negativo ou zero deve ser 400
resp_num_negative_inbox = client.post(
    "/numbers",
    json={
        "waba_id": "waba_teste_sp",
        "phone_number_id": "phone_bad_inbox",
        "display_phone_number": "+55 11 91111-0002",
        "chatwoot_inbox_id": 0,
    },
    headers=headers,
)
assert resp_num_negative_inbox.status_code == 400

# 10. Teste: Criação de número com token e chatwoot_inbox_id
resp_num_ok = client.post(
    "/numbers",
    json={
        "waba_id": "waba_teste_sp",
        "phone_number_id": "phone_ok_test_100",
        "display_phone_number": "+55 11 91111-1000",
        "label": "Linha SP 1",
        "meta_token_id": token_1_id,
        "chatwoot_inbox_id": 15,
    },
    headers=headers,
)
assert resp_num_ok.status_code == 201, f"Falha na criação do número: {resp_num_ok.text}"
num_created = resp_num_ok.json()
number_id = num_created["id"]
assert num_created["meta_token_id"] == token_1_id
assert num_created["meta_token_nome"] == "Token Cobrança SP Atualizado"
assert num_created["chatwoot_inbox_id"] == 15

# Verificar que numeros_vinculados do token agora é 1
resp_get_tokens = client.get("/meta-tokens", headers=headers)
token_1_after = next(t for t in resp_get_tokens.json() if t["id"] == token_1_id)
assert token_1_after["numeros_vinculados"] == 1

# 11. Teste: DELETE /meta-tokens/{id} bloqueado com 409 quando em uso
resp_del_conflict = client.delete(f"/meta-tokens/{token_1_id}", headers=headers)
assert resp_del_conflict.status_code == 409
assert "usado por 1 número(s)" in resp_del_conflict.json()["detail"]

# 12. Teste: PATCH /numbers/{id} com null para limpar meta_token_id e chatwoot_inbox_id
resp_patch_num_null = client.patch(
    f"/numbers/{number_id}",
    json={"meta_token_id": None, "chatwoot_inbox_id": None, "label": "Linha Sem Token"},
    headers=headers,
)
assert resp_patch_num_null.status_code == 200
num_patched = resp_patch_num_null.json()
assert num_patched["meta_token_id"] is None
assert num_patched["meta_token_nome"] is None
assert num_patched["chatwoot_inbox_id"] is None
assert num_patched["label"] == "Linha Sem Token"

# Agora o token 1 tem 0 números vinculados e pode ser excluído
resp_del_ok = client.delete(f"/meta-tokens/{token_1_id}", headers=headers)
assert resp_del_ok.status_code == 204

# 13. Teste: token_da_waba (regra do mais antigo, fallback .env e erro)
db = SessionLocal()
try:
    waba_spec = "waba_desempate_test"
    # Cria dois tokens ativos
    tok_antigo = models.MetaToken(
        nome="Token Antigo",
        token_cifrado=crypto.cifrar("TOKEN_ANTIGO_111"),
        ultimos4="1111",
        ativo=True,
    )
    tok_novo = models.MetaToken(
        nome="Token Novo",
        token_cifrado=crypto.cifrar("TOKEN_NOVO_222"),
        ultimos4="2222",
        ativo=True,
    )
    db.add_all([tok_antigo, tok_novo])
    db.commit()

    # Cria número 1 mais antigo vinculado a tok_antigo
    num_antigo = models.WhatsappNumber(
        waba_id=waba_spec,
        phone_number_id="phone_waba_antigo",
        display_phone_number="+55 11 98888-0001",
        meta_token_id=tok_antigo.id,
        active=True,
        created_at=datetime.utcnow() - timedelta(days=5),
    )
    # Cria número 2 mais recente vinculado a tok_novo
    num_novo = models.WhatsappNumber(
        waba_id=waba_spec,
        phone_number_id="phone_waba_novo",
        display_phone_number="+55 11 98888-0002",
        meta_token_id=tok_novo.id,
        active=True,
        created_at=datetime.utcnow() - timedelta(days=1),
    )
    db.add_all([num_antigo, num_novo])
    db.commit()

    # Regra de desempate: deve retornar o token do número mais antigo
    token_selecionado = token_da_waba(db, waba_spec)
    assert token_selecionado == "TOKEN_ANTIGO_111", f"Esperado TOKEN_ANTIGO_111, obteve {token_selecionado}"

    # Se o número mais antigo for inativado, deve escolher o próximo
    num_antigo.active = False
    db.commit()
    token_apos_inativar_num = token_da_waba(db, waba_spec)
    assert token_apos_inativar_num == "TOKEN_NOVO_222"

    # Se o token do segundo número for inativado, não há mais token ativo -> MetaTokenConfigError (sem fallback de env)
    tok_novo.ativo = False
    db.commit()

    error_raised = False
    try:
        token_da_waba(db, waba_spec)
    except MetaTokenConfigError as e:
        error_raised = True
        assert f"Nenhum token da Meta cadastrado para a WABA {waba_spec}: cadastre um em Configurações" in str(e)
    assert error_raised, "Esperava MetaTokenConfigError quando nenhum token está configurado"

finally:
    db.close()

# 14. Teste: POST /meta-tokens/{id}/testar (Meta OK vs Meta Erro)
# Cria token para teste de sucesso
resp_test_tok_ok = client.post(
    "/meta-tokens",
    json={"nome": "Token Valido Teste", "token": "EAAX_TOKEN_VALIDO_123", "waba_id": "1111"},
    headers=headers,
)
tok_ok_id = resp_test_tok_ok.json()["id"]

resp_test_call_ok = client.post(f"/meta-tokens/{tok_ok_id}/testar", headers=headers)
assert resp_test_call_ok.status_code == 200
body_ok = resp_test_call_ok.json()
assert body_ok["ok"] is True
assert "TopFama WhatsApp Oficial" in body_ok["detalhe"]
assert "EAAX" not in body_ok["detalhe"]

# Token que a Meta passou a recusar depois de cadastrado (o cadastro pela API já
# recusaria): inserido direto no banco
db = SessionLocal()
tok_err = models.MetaToken(nome="Token Invalido Teste", token_cifrado=crypto.cifrar("TOKEN_INVALIDO_META"), ultimos4="META", ativo=True)
db.add(tok_err)
db.commit()
tok_err_id = tok_err.id
db.close()

resp_test_call_err = client.post(f"/meta-tokens/{tok_err_id}/testar", headers=headers)
assert resp_test_call_err.status_code == 200
body_err = resp_test_call_err.json()
assert body_err["ok"] is False
assert "OAuthException" in body_err["detalhe"] or "Invalid OAuth" in body_err["detalhe"]
assert "TOKEN_INVALIDO" not in body_err["detalhe"]
assert "número(s) na WABA 1111" in body_ok["detalhe"]

# 15. WABA obrigatória e validada na Meta antes de gravar
assert client.post("/meta-tokens", json={"nome": "Sem WABA", "token": "EAAX_SEM_WABA"}, headers=headers).status_code == 422
r = client.post("/meta-tokens", json={"nome": "WABA letras", "token": "EAAX_W", "waba_id": "abc"}, headers=headers)
assert r.status_code == 400 and "WABA" in r.json()["detail"]
r = client.post("/meta-tokens", json={"nome": "WABA errada", "token": "EAAX_WABA_ERRADA", "waba_id": "999"}, headers=headers)
assert r.status_code == 400 and "Meta recusou" in r.json()["detail"], r.json()
db = SessionLocal()
assert db.query(models.MetaToken).filter(models.MetaToken.nome == "WABA errada").count() == 0
db.close()
assert "EAAX_WABA_ERRADA" not in r.text

# 16. Puxar os números da WABA com o token e importar
r = client.get(f"/meta-tokens/{tok_ok_id}/numeros-meta", headers=headers)
assert r.status_code == 200, r.text
nums = {n["phone_number_id"]: n for n in r.json()}
assert set(nums) == {"PNID_1", "PNID_2"} and not any(n["cadastrado"] for n in nums.values())
assert nums["PNID_1"]["verified_name"] == "TopFama Palmas"
r = client.post(f"/meta-tokens/{tok_ok_id}/importar-numeros", json={"phone_number_ids": ["PNID_1", "PNID_2", "PNID_1"]}, headers=headers)
assert r.json() == {"importados": 2, "vinculados": 0, "ignorados": 0}, r.json()
r = client.post(f"/meta-tokens/{tok_ok_id}/importar-numeros", json={"phone_number_ids": ["PNID_1"]}, headers=headers)
assert r.json() == {"importados": 0, "vinculados": 0, "ignorados": 0}
nums = {n["phone_number_id"]: n for n in client.get(f"/meta-tokens/{tok_ok_id}/numeros-meta", headers=headers).json()}
assert all(n["cadastrado"] and n["vinculado_a_este_token"] for n in nums.values())
numero = next(n for n in client.get("/numbers", headers=headers).json() if n["phone_number_id"] == "PNID_1")
assert numero["waba_id"] == "1111" and numero["meta_token_id"] == tok_ok_id and numero["label"] == "TopFama Palmas"
r = client.post(f"/meta-tokens/{tok_ok_id}/importar-numeros", json={"phone_number_ids": ["PNID_X"]}, headers=headers)
assert r.status_code == 400 and "PNID_X" in r.json()["detail"]
r = client.get(f"/meta-tokens/{tok_err_id}/numeros-meta", headers=headers)
assert r.status_code == 400 and "WABA" in r.json()["detail"]  # token antigo sem WABA
assert client.get("/meta-tokens/nao-existe/numeros-meta", headers=headers).status_code == 404

# 17. Sincronização de templates com números importados
# (regressão: um número antigo inativo e sem token abortava a sincronização inteira)
db = SessionLocal()
db.add(models.WhatsappNumber(waba_id="1234567890", phone_number_id="PNID_ANTIGO", display_phone_number="+55 63 90000-0000",
                             label="Teste", active=False))
db.commit()
db.close()
# WABA só com token (nenhum número): usa o token cadastrado para ela em Configurações
r = client.post("/meta-tokens", json={"nome": "Token só WABA", "token": "EAAX_SO_WABA_2222", "waba_id": "2222"}, headers=headers)
assert r.status_code == 201, r.text
r = client.post("/templates/meta/sync", headers=headers)
assert r.status_code == 200, r.text
por_nome = {t["meta_template_name"]: t for t in r.json()}
assert por_nome["cobranca_1111"]["waba_id"] == "1111" and por_nome["cobranca_1111"]["status"] == "approved"
assert "cobranca_2222" in por_nome, "WABA só com token deveria sincronizar"
assert "cobranca_1234567890" not in por_nome, "número inativo não deve ser sincronizado"
assert [v["position"] for v in por_nome["cobranca_1111"]["variables"]] == [1, 2]
# sem token nenhum utilizável: erro explicando cada WABA, nunca 500
db = SessionLocal()
db.query(models.MetaToken).update({"ativo": False})
db.commit()
db.close()
r = client.post("/templates/meta/sync", headers=headers)
assert r.status_code == 400 and "Nenhuma WABA sincronizou" in r.json()["detail"], r.text

print("OK")
