"""Sincronização de templates no Chatwoot quando o template vira aprovado.

Confere que o Sincronizar e o Atualizar status pedem o sync_templates ao
Chatwoot uma vez por caixa de entrada dos números ativos da WABA, só na
transição para aprovado (sync repetido não pede de novo), que sem Chatwoot
configurado nada é pedido e que a recusa do Chatwoot (token sem admin) vira
aviso sem desfazer a aprovação. Executado com asserts simples sem pytest,
encerrando com 'OK'.
"""

import os
import tempfile

from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres:t@localhost:15432/agy_syncchatwoot")
os.environ["JWT_SECRET"] = "segredo-de-teste-sync-chatwoot-123456"
os.environ["ADMIN_PASSWORD"] = "senha-admin-sync-chatwoot-987"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp()
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()

import httpx
from fastapi.testclient import TestClient

from app import crypto, models
from app.chatwoot_client import ChatwootClient
from app.config import settings
from app.database import SessionLocal
from app.main import _run_migrations, app
from app.meta_client import MetaClient
from app.security import hash_password

WABA = "8880001"
OUTRA_WABA = "8880002"
REMOTO = {"id": "TPLSYNC", "name": "aviso_pagamento", "language": "pt_BR", "category": "UTILITY", "status": "PENDING",
          "components": [{"type": "BODY", "text": "Oi {{1}}"}]}


def meta_falsa(request: httpx.Request) -> httpx.Response:
    caminho = request.url.path.split("/", 2)[-1]
    if caminho == f"{WABA}/message_templates":
        return httpx.Response(200, json={"data": [REMOTO]})
    if caminho == f"{OUTRA_WABA}/message_templates":
        return httpx.Response(200, json={"data": []})
    if caminho == "TPLSYNC":
        return httpx.Response(200, json=REMOTO)
    return httpx.Response(404, json={"error": {"message": f"rota simulada inexistente: {caminho}"}})


PEDIDOS: list[str] = []
RESPOSTA_CHATWOOT = {"status": 200}


def chatwoot_falso(request: httpx.Request) -> httpx.Response:
    PEDIDOS.append(f"{request.method} {request.url.path}")
    assert request.headers["api_access_token"] == "TOKEN_ADMIN", request.headers
    if RESPOSTA_CHATWOOT["status"] != 200:
        return httpx.Response(RESPOSTA_CHATWOOT["status"], json={"error": "You are not authorized to do this action"})
    return httpx.Response(200)


MetaClient.default_transport = httpx.MockTransport(meta_falsa)
ChatwootClient.default_transport = httpx.MockTransport(chatwoot_falso)
client = TestClient(app)
_run_migrations()

db = SessionLocal()
admin = db.query(models.User).filter(models.User.email == settings.admin_email).first()
if admin:
    admin.password_hash = hash_password("senha-admin-sync-chatwoot-987")
else:
    db.add(models.User(email=settings.admin_email, password_hash=hash_password("senha-admin-sync-chatwoot-987")))
for waba in (WABA, OUTRA_WABA):
    token = models.MetaToken(nome=f"Token {waba}", token_cifrado=crypto.cifrar("TOKEN_TESTE"), ultimos4="ESTE", waba_id=waba)
    db.add(token)
    db.flush()
    if waba == WABA:
        # Dois números na mesma caixa, outro em caixa própria, um sem caixa e um inativo
        for pn, caixa, ativo in (("PN1", 11, True), ("PN2", 11, True), ("PN3", 12, True), ("PN4", None, True), ("PN5", 13, False)):
            db.add(models.WhatsappNumber(waba_id=waba, phone_number_id=pn, display_phone_number=pn, meta_token_id=token.id,
                                         chatwoot_inbox_id=caixa, active=ativo))
    else:
        db.add(models.WhatsappNumber(waba_id=waba, phone_number_id="PN9", display_phone_number="PN9", meta_token_id=token.id,
                                     chatwoot_inbox_id=19))
db.commit()
db.close()

login = client.post("/auth/login", json={"email": settings.admin_email, "password": "senha-admin-sync-chatwoot-987"})
assert login.status_code == 200, login.text
h = {"Authorization": f"Bearer {login.json()['access_token']}"}


def sincronizar() -> dict:
    r = client.post("/templates/meta/sync", headers=h)
    assert r.status_code == 200, r.text
    return next(t for t in r.json() if t["meta_template_name"] == "aviso_pagamento")


SYNC = ["POST /api/v1/accounts/1/inboxes/11/sync_templates", "POST /api/v1/accounts/1/inboxes/12/sync_templates"]

# 1. Sem Chatwoot configurado: aprova sem pedir nada
REMOTO["status"] = "APPROVED"
t = sincronizar()
assert t["status"] == "approved" and t["aviso_chatwoot"] is None, t
assert PEDIDOS == []

db = SessionLocal()
db.add(models.ConfiguracaoChatwoot(base_url="https://chat.exemplo.test", account_id="1",
                                   api_access_token_cifrado=crypto.cifrar("TOKEN_ADMIN")))
db.commit()
db.close()

# 2. Pendente: nada a pedir; virou aprovado no Sincronizar: uma vez por caixa da WABA
REMOTO["status"] = "PENDING"
assert sincronizar()["status"] == "pending"
assert PEDIDOS == []
REMOTO["status"] = "APPROVED"
t = sincronizar()
assert t["aviso_chatwoot"] is None, t
assert PEDIDOS == SYNC, PEDIDOS

# 3. Continua aprovado: sync e Atualizar status não pedem de novo
PEDIDOS.clear()
sincronizar()
r = client.post(f"/templates/{t['id']}/refresh-status", headers=h)
assert r.status_code == 200, r.text
assert PEDIDOS == []

# 4. Reanálise (pendente) e aprovado de novo pelo Atualizar status: pede de novo
REMOTO["status"] = "PENDING"
client.post(f"/templates/{t['id']}/refresh-status", headers=h)
REMOTO["status"] = "APPROVED"
r = client.post(f"/templates/{t['id']}/refresh-status", headers=h)
assert r.status_code == 200 and r.json()["aviso_chatwoot"] is None, r.text
assert PEDIDOS == SYNC, PEDIDOS

# 5. Token sem permissão de admin: aprovação fica gravada e volta aviso
PEDIDOS.clear()
REMOTO["status"] = "PENDING"
sincronizar()
RESPOSTA_CHATWOOT["status"] = 401
REMOTO["status"] = "APPROVED"
t = sincronizar()
assert t["status"] == "approved", t
assert "precisa ser de um administrador" in t["aviso_chatwoot"] and "Configurações → Modelos" in t["aviso_chatwoot"], t
assert len(PEDIDOS) == 2, PEDIDOS
assert client.get("/templates", headers=h).json()[0]["aviso_chatwoot"] is None

print("OK")
