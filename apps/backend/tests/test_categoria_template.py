"""Aviso de template recategorizado pela Meta.

Confere que o Sincronizar e o Atualizar status gravam previous_category e
correct_category, que o aviso aparece na tabela, no Dashboard e na subida de
fila (avisos_categoria_das_faixas), que o Ciente esconde o aviso e que uma
troca nova da Meta volta a avisar. Executado com asserts simples sem pytest,
encerrando com 'OK'.
"""

import os
import tempfile

from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres:t@localhost:15432/agy_cattpl")
os.environ["JWT_SECRET"] = "segredo-de-teste-categoria-template-123456"
os.environ["ADMIN_PASSWORD"] = "senha-admin-categoria-template-987"
os.environ["MEDIA_DIR"] = tempfile.mkdtemp()
os.environ["ENCRYPTION_KEY"] = Fernet.generate_key().decode()

import httpx
from fastapi.testclient import TestClient

from app import crypto, itens_fila, models
from app.config import settings
from app.database import SessionLocal
from app.main import _run_migrations, app
from app.meta_client import MetaClient
from app.security import hash_password

WABA = "7770001"
# O que a Meta devolve para o template; cada passo do teste ajusta
REMOTO = {"id": "TPLCAT", "name": "lembrete_parcela", "language": "pt_BR", "category": "UTILITY", "status": "APPROVED",
          "components": [{"type": "BODY", "text": "Oi {{1}}"}]}


def meta_falsa(request: httpx.Request) -> httpx.Response:
    caminho = request.url.path.split("/", 2)[-1]
    if caminho == f"{WABA}/message_templates":
        return httpx.Response(200, json={"data": [REMOTO]})
    if caminho == "TPLCAT":
        assert "previous_category" in request.url.params["fields"], request.url.params
        return httpx.Response(200, json=REMOTO)
    return httpx.Response(404, json={"error": {"message": f"rota simulada inexistente: {caminho}"}})


MetaClient.default_transport = httpx.MockTransport(meta_falsa)
client = TestClient(app)
_run_migrations()

db = SessionLocal()
admin = db.query(models.User).filter(models.User.email == settings.admin_email).first()
if admin:
    admin.password_hash = hash_password("senha-admin-categoria-template-987")
else:
    db.add(models.User(email=settings.admin_email, password_hash=hash_password("senha-admin-categoria-template-987")))
token = models.MetaToken(nome="Teste", token_cifrado=crypto.cifrar("TOKEN_TESTE"), ultimos4="ESTE", waba_id=WABA)
db.add(token)
db.flush()
db.add(models.WhatsappNumber(waba_id=WABA, phone_number_id="PNCAT", display_phone_number="+55 11 4000-0002",
                             meta_token_id=token.id))
db.commit()
db.close()

login = client.post("/auth/login", json={"email": settings.admin_email, "password": "senha-admin-categoria-template-987"})
assert login.status_code == 200, login.text
h = {"Authorization": f"Bearer {login.json()['access_token']}"}


def sincronizar() -> dict:
    r = client.post("/templates/meta/sync", headers=h)
    assert r.status_code == 200, r.text
    return next(t for t in r.json() if t["meta_template_name"] == "lembrete_parcela")


def avisos_da_faixa() -> list[str]:
    db = SessionLocal()
    try:
        return itens_fila.avisos_categoria_das_faixas([db.query(models.Faixa).filter_by(name="Faixa categoria").one()])
    finally:
        db.close()


# 1. Sem troca de categoria: nenhum aviso
t = sincronizar()
assert t["aviso_categoria"] is None, t
assert client.get("/templates/avisos-categoria", headers=h).json() == []

db = SessionLocal()
faixa = models.Faixa(name="Faixa categoria", tipo=models.TIPO_REGUA)
db.add(faixa)
db.flush()
numero = db.query(models.WhatsappNumber).filter_by(phone_number_id="PNCAT").one()
db.add(models.FaixaEnvio(faixa_id=faixa.id, whatsapp_number_id=numero.id, template_id=t["id"]))
db.commit()
db.close()
assert avisos_da_faixa() == []

# 2. A Meta mudou de Utilidade para Marketing: aviso na tabela, no Dashboard e na fila
REMOTO.update(category="MARKETING", previous_category="UTILITY")
t = sincronizar()
assert t["category"] == "MARKETING"
assert t["aviso_categoria"] == "A Meta mudou a categoria de Utilidade para Marketing", t
dashboard = client.get("/templates/avisos-categoria", headers=h).json()
assert len(dashboard) == 1 and "lembrete_parcela" in dashboard[0] and "clique em Ciente" in dashboard[0], dashboard
assert avisos_da_faixa() == dashboard

# 3. Ciente esconde em todo lugar, e o próximo sync com a mesma troca não traz de volta
r = client.post(f"/templates/{t['id']}/categoria-ciente", headers=h)
assert r.status_code == 200 and r.json()["aviso_categoria"] is None, r.text
assert sincronizar()["aviso_categoria"] is None
assert client.get("/templates/avisos-categoria", headers=h).json() == []
assert avisos_da_faixa() == []

# 4. Troca nova anunciada pela Meta (Atualizar status): volta a avisar
REMOTO.update(category="UTILITY", previous_category=None, correct_category="MARKETING")
r = client.post(f"/templates/{t['id']}/refresh-status", headers=h)
assert r.status_code == 200, r.text
assert r.json()["aviso_categoria"] == "A Meta vai mudar a categoria de Utilidade para Marketing", r.json()
assert len(avisos_da_faixa()) == 1

# 5. Template inexistente
assert client.post("/templates/nao-existe/categoria-ciente", headers=h).status_code == 404

print("OK")
