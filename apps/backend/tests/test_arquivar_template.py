"""Arquivar, restaurar e remover template (Configurações → Templates).

Confere que template em uso numa faixa não arquiva nem remove (e o erro diz
onde está em uso), que o arquivado some da lista padrão e dos envios mas
continua no filtro e não volta pelo sync, que Restaurar devolve, que remover
template da Meta apaga lá (hsm_id + name) e no CRM e o sync não o recria
enquanto a Meta apaga, que rascunho remove sem chamar a Meta e que erro da
Meta não apaga nada. Executado com asserts simples sem pytest, encerrando com 'OK'.
"""

import os
import tempfile

from cryptography.fernet import Fernet

os.environ["DATABASE_URL"] = os.environ.get("DATABASE_URL", "postgresql+psycopg://postgres:t@localhost:15432/agy_arqtpl")
os.environ["JWT_SECRET"] = "segredo-de-teste-arquivar-template-123456"
os.environ["ADMIN_PASSWORD"] = "senha-admin-arquivar-template-987"
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

WABA = "7770002"
CORPO = [{"type": "BODY", "text": "Oi"}]
REMOTOS = [
    {"id": "TPLUSO", "name": "em_uso", "language": "pt_BR", "category": "UTILITY", "status": "APPROVED", "components": CORPO},
    {"id": "TPLLIVRE", "name": "livre", "language": "pt_BR", "category": "UTILITY", "status": "APPROVED", "components": CORPO},
]
APAGADOS: list[dict] = []
FALHAR_DELETE = False


def meta_falsa(request: httpx.Request) -> httpx.Response:
    caminho = request.url.path.split("/", 2)[-1]
    if caminho == f"{WABA}/message_templates" and request.method == "GET":
        return httpx.Response(200, json={"data": REMOTOS})
    if caminho == f"{WABA}/message_templates" and request.method == "DELETE":
        if FALHAR_DELETE:
            return httpx.Response(400, json={"error": {"message": "falha simulada"}})
        APAGADOS.append(dict(request.url.params))
        return httpx.Response(200, json={"success": True})
    return httpx.Response(404, json={"error": {"message": f"rota simulada inexistente: {caminho}"}})


MetaClient.default_transport = httpx.MockTransport(meta_falsa)
client = TestClient(app)
_run_migrations()

db = SessionLocal()
admin = db.query(models.User).filter(models.User.email == settings.admin_email).first()
if admin:
    admin.password_hash = hash_password("senha-admin-arquivar-template-987")
else:
    db.add(models.User(email=settings.admin_email, password_hash=hash_password("senha-admin-arquivar-template-987")))
token = models.MetaToken(nome="Teste", token_cifrado=crypto.cifrar("TOKEN_TESTE"), ultimos4="ESTE", waba_id=WABA)
db.add(token)
db.flush()
numero = models.WhatsappNumber(waba_id=WABA, phone_number_id="PNARQ", display_phone_number="+55 11 4000-0003",
                               meta_token_id=token.id)
db.add(numero)
db.commit()
numero_id = numero.id
db.close()

login = client.post("/auth/login", json={"email": settings.admin_email, "password": "senha-admin-arquivar-template-987"})
assert login.status_code == 200, login.text
h = {"Authorization": f"Bearer {login.json()['access_token']}"}


def sincronizar() -> dict:
    r = client.post("/templates/meta/sync", headers=h)
    assert r.status_code == 200, r.text
    return {t["meta_template_name"]: t for t in r.json()}


def nomes(incluir_arquivados: bool = False) -> set[str]:
    url = "/templates?incluir_arquivados=true" if incluir_arquivados else "/templates"
    return {t["meta_template_name"] for t in client.get(url, headers=h).json()}


templates = sincronizar()
em_uso, livre = templates["em_uso"], templates["livre"]
faixa = client.post("/faixas", json={"name": "Faixa arquivo"}, headers=h)
assert faixa.status_code == 201, faixa.text
faixa_id = faixa.json()["id"]
r = client.post(f"/faixas/{faixa_id}/envios", json={"whatsapp_number_id": numero_id, "template_id": em_uso["id"]}, headers=h)
assert r.status_code == 201, r.text

# 1. Em uso: não arquiva nem remove, e diz onde
for r in (client.post(f"/templates/{em_uso['id']}/arquivar", headers=h), client.delete(f"/templates/{em_uso['id']}", headers=h)):
    assert r.status_code == 400 and "Faixa arquivo" in r.json()["detail"], r.text
assert APAGADOS == []

# 2. Arquivar: some da lista padrão e dos envios, fica no filtro e o sync mantém
r = client.post(f"/templates/{livre['id']}/arquivar", headers=h)
assert r.status_code == 200 and r.json()["arquivado_em"], r.text
assert nomes() == {"em_uso"}
assert nomes(True) == {"em_uso", "livre"}
assert sincronizar()["livre"]["arquivado_em"], "sync não pode desarquivar"
assert nomes(True) == {"em_uso", "livre"}, "sync não pode recriar o arquivado"
r = client.post(f"/faixas/{faixa_id}/envios", json={"whatsapp_number_id": numero_id, "template_id": livre["id"]}, headers=h)
assert r.status_code == 422 and "arquivado" in r.json()["detail"], r.text

# 3. Restaurar devolve à lista
r = client.post(f"/templates/{livre['id']}/restaurar", headers=h)
assert r.status_code == 200 and r.json()["arquivado_em"] is None, r.text
assert nomes() == {"em_uso", "livre"}

# 4. Erro da Meta ao remover: nada é apagado
FALHAR_DELETE = True
r = client.delete(f"/templates/{livre['id']}", headers=h)
assert r.status_code == 502, r.text
assert "livre" in nomes()
FALHAR_DELETE = False

# 5. Remover template da Meta: apaga só este idioma lá e no CRM; o sync não recria enquanto a Meta apaga
r = client.delete(f"/templates/{livre['id']}", headers=h)
assert r.status_code == 204, r.text
assert APAGADOS == [{"hsm_id": "TPLLIVRE", "name": "livre"}], APAGADOS
REMOTOS[1]["status"] = "PENDING_DELETION"
sincronizar()
assert nomes(True) == {"em_uso"}

# 6. Rascunho remove sem chamar a Meta
rascunho = client.post("/templates", json={"name": "Rascunho", "meta_template_name": "rascunho_x", "category": "UTILITY",
                                           "body_text": "Oi", "variables": []}, headers=h)
assert rascunho.status_code == 201, rascunho.text
r = client.delete(f"/templates/{rascunho.json()['id']}", headers=h)
assert r.status_code == 204, r.text
assert len(APAGADOS) == 1
assert nomes(True) == {"em_uso"}

# 7. Template inexistente
assert client.post("/templates/nao-existe/arquivar", headers=h).status_code == 404
assert client.post("/templates/nao-existe/restaurar", headers=h).status_code == 404
assert client.delete("/templates/nao-existe", headers=h).status_code == 404

print("OK")
