"""Cadastro de template na plataforma e envio para aprovação na Meta.

Confere as regras da Meta no cadastro (nome, corpo, categoria, idioma fixo em
pt_BR) e o payload enviado na aprovação: exemplos das variáveis em
example.body_text e imagem do cabeçalho em example.header_handle (Resumable
Upload). Executado com asserts simples sem pytest, encerrando com 'OK'.
"""

import base64
import json
import os
import tempfile

from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres:t@localhost:15432/agy_cadtpl")
os.environ["JWT_SECRET"] = "segredo-de-teste-cadastro-template-123456"
os.environ["ADMIN_PASSWORD"] = "senha-admin-cadastro-template-987"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp()
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()

import httpx
from fastapi.testclient import TestClient

from app import crypto, models
from app.config import settings
from app.database import SessionLocal
from app.main import _run_migrations, app
from app.meta_client import MetaClient
from app.security import hash_password

WABA = "5550001"
CHAMADAS: list[dict] = []


def meta_falsa(request: httpx.Request) -> httpx.Response:
    caminho = request.url.path.split("/", 2)[-1]
    CHAMADAS.append(
        {"metodo": request.method, "caminho": caminho, "auth": request.headers.get("authorization", ""),
         "offset": request.headers.get("file_offset"), "params": dict(request.url.params), "corpo": request.content}
    )
    if caminho == "app":
        return httpx.Response(200, json={"id": "APP42"})
    if caminho == "APP42/uploads":
        return httpx.Response(200, json={"id": "upload:SESSAO1"})
    if caminho == "upload:SESSAO1":
        return httpx.Response(200, json={"h": "4::HANDLE"})
    if caminho == f"{WABA}/message_templates" and request.method == "POST":
        return httpx.Response(200, json={"id": f"TPL{len(CHAMADAS)}", "status": "PENDING", "category": "UTILITY"})
    return httpx.Response(404, json={"error": {"message": f"rota simulada inexistente: {caminho}"}})


MetaClient.default_transport = httpx.MockTransport(meta_falsa)
client = TestClient(app)
_run_migrations()

db = SessionLocal()
admin = db.query(models.User).filter(models.User.email == settings.admin_email).first()
if admin:
    admin.password_hash = hash_password("senha-admin-cadastro-template-987")
else:
    db.add(models.User(email=settings.admin_email, password_hash=hash_password("senha-admin-cadastro-template-987")))
token = models.MetaToken(nome="Teste", token_cifrado=crypto.cifrar("TOKEN_TESTE"), ultimos4="ESTE", waba_id=WABA)
db.add(token)
db.flush()
db.add(models.WhatsappNumber(waba_id=WABA, phone_number_id="PN1", display_phone_number="+55 11 4000-0001",
                             meta_token_id=token.id))
db.commit()
db.close()

login = client.post("/auth/login", json={"email": settings.admin_email, "password": "senha-admin-cadastro-template-987"})
assert login.status_code == 200, login.text
h = {"Authorization": f"Bearer {login.json()['access_token']}"}


def criar(**campos):
    payload = {
        "name": "Cobrança",
        "meta_template_name": "cobranca_atraso",
        "category": "UTILITY",
        "body_text": "Olá {{1}}, sua parcela de R$ {{2}} venceu.",
        "variables": [
            {"position": 1, "internal_name": "variavel_1", "exemplo": "Maria", "campo_sugerido": "nome"},
            {"position": 2, "internal_name": "variavel_2", "exemplo": "189,90"},
        ],
        **campos,
    }
    return client.post("/templates", json=payload, headers=h)


# Nome fora da regra da Meta, categoria fora do cadastro e corpo inválido: 422 sem chegar na Meta
assert criar(meta_template_name="Cobrança Atraso").status_code == 422
assert criar(meta_template_name="a" * 513).status_code == 422
assert criar(category="AUTHENTICATION").status_code == 422
assert criar(body_text="{{1}}, sua parcela venceu.", variables=[{"position": 1, "internal_name": "variavel_1"}]).status_code == 422
assert criar(body_text="Olá, sua parcela venceu {{1}}", variables=[{"position": 1, "internal_name": "variavel_1"}]).status_code == 422
assert criar(body_text="Olá {{1}} e {{3}}.", variables=[{"position": 1, "internal_name": "variavel_1"},
                                                       {"position": 3, "internal_name": "variavel_3"}]).status_code == 422
assert criar(body_text="Olá " + "x" * 1030 + ".", variables=[]).status_code == 422
assert criar(variables=[{"position": 1, "internal_name": "variavel_1"}]).status_code == 422
assert criar(variables=[{"position": 1, "internal_name": "variavel_1", "campo_sugerido": "inexistente"},
                        {"position": 2, "internal_name": "variavel_2"}]).status_code == 422
assert CHAMADAS == []

# Idioma é sempre pt_BR, mesmo que alguém mande outro; salva rascunho com exemplo e campo
resp = criar(language="en_US")
assert resp.status_code == 201, resp.text
rascunho = resp.json()
assert rascunho["language"] == "pt_BR" and rascunho["status"] == "draft" and rascunho["meta_template_id"] is None
assert [(v["exemplo"], v["campo_sugerido"]) for v in rascunho["variables"]] == [("Maria", "nome"), ("189,90", None)]
assert CHAMADAS == []

# Mesmo nome na mesma WABA: 409
assert criar().status_code == 409

# Envio para aprovação: exemplos em example.body_text (lista dentro de lista)
resp = client.post(f"/templates/{rascunho['id']}/enviar-para-aprovacao", headers=h)
assert resp.status_code == 200, resp.text
assert resp.json()["status"] == "pending" and resp.json()["meta_template_id"]
enviado = json.loads(CHAMADAS[-1]["corpo"])
assert enviado["name"] == "cobranca_atraso" and enviado["language"] == "pt_BR" and enviado["category"] == "UTILITY"
assert enviado["components"] == [
    {"type": "BODY", "text": "Olá {{1}}, sua parcela de R$ {{2}} venceu.", "example": {"body_text": [["Maria", "189,90"]]}}
]
assert client.post(f"/templates/{rascunho['id']}/enviar-para-aprovacao", headers=h).status_code == 400

# Sem exemplo de alguma variável: não envia
sem_exemplo = criar(meta_template_name="sem_exemplo", variables=[
    {"position": 1, "internal_name": "variavel_1", "exemplo": "Maria"}, {"position": 2, "internal_name": "variavel_2", "exemplo": " "},
]).json()
assert sem_exemplo["variables"][1]["exemplo"] is None
total = len(CHAMADAS)
resp = client.post(f"/templates/{sem_exemplo['id']}/enviar-para-aprovacao", headers=h)
assert resp.status_code == 400 and "exemplo" in resp.json()["detail"]
assert len(CHAMADAS) == total

# Cabeçalho de imagem: sem imagem não envia; com imagem sobe pela Resumable Upload e manda o handle
com_imagem = criar(meta_template_name="com_imagem", header_type="image", body_text="Oi, sua fatura chegou.", variables=[]).json()
resp = client.post(f"/templates/{com_imagem['id']}/enviar-para-aprovacao", headers=h)
assert resp.status_code == 400 and "imagem" in resp.json()["detail"]
assert len(CHAMADAS) == total

png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==")
resp = client.post(f"/templates/{com_imagem['id']}/image", files={"file": ("a.png", png, "image/png")}, headers=h)
assert resp.status_code == 200, resp.text
resp = client.post(f"/templates/{com_imagem['id']}/enviar-para-aprovacao", headers=h)
assert resp.status_code == 200, resp.text
app_id, sessao, upload, cadastro = CHAMADAS[total:]
assert app_id["caminho"] == "app"
assert sessao["caminho"] == "APP42/uploads" and sessao["params"]["file_type"] == "image/png"
assert sessao["params"]["file_length"] == str(len(upload["corpo"]))
assert upload["caminho"] == "upload:SESSAO1" and upload["auth"] == "OAuth TOKEN_TESTE" and upload["offset"] == "0"
assert json.loads(cadastro["corpo"])["components"] == [
    {"type": "HEADER", "format": "IMAGE", "example": {"header_handle": ["4::HANDLE"]}},
    {"type": "BODY", "text": "Oi, sua fatura chegou."},
]

print("OK")
