"""Cadastro de template na plataforma e envio para aprovação na Meta.

Confere que o rascunho salva incompleto e é editável, as regras da Meta antes
do envio (nome, corpo, botões, exemplos), o idioma fixo em pt_BR e o payload
enviado na aprovação: exemplos das variáveis em example.body_text, botões em
BUTTONS e imagem do cabeçalho em example.header_handle (Resumable Upload). Executado com asserts simples sem pytest, encerrando com 'OK'.
"""

import asyncio
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
from app.dispatch_service import montar_parametros_envio
from app.main import _run_migrations, app
from app.meta_client import MetaClient
from app.routers.templates import _extract_botoes, _extract_variables
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
    if caminho.startswith("TPL") and request.method == "POST":
        return httpx.Response(200, json={"success": True})
    if caminho == "PN1/messages":
        return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})
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


def enviar(template_id):
    return client.post(f"/templates/{template_id}/enviar-para-aprovacao", headers=h)


# Categoria fora do cadastro, campo inexistente e sem nome interno: 422 sem gravar
assert criar(category="AUTHENTICATION").status_code == 422
assert criar(variables=[{"position": 1, "internal_name": "variavel_1", "campo_sugerido": "inexistente"},
                        {"position": 2, "internal_name": "variavel_2"}]).status_code == 422
assert criar(name="  ").status_code == 422
assert criar(botoes=[{"tipo": "telefone", "texto": "Ligar"}]).status_code == 422

# Rascunho pode ser salvo incompleto, mas só vai para a Meta com as regras dela cumpridas
invalidos = [
    ({"meta_template_name": "", "body_text": "", "variables": []}, "Nome na Meta"),
    ({"meta_template_name": "Cobrança Atraso"}, "Nome na Meta"),
    ({"meta_template_name": "a" * 513}, "Nome na Meta"),
    ({"body_text": "", "variables": []}, "corpo do template é obrigatório"),
    ({"body_text": "{{1}}, sua parcela venceu.", "variables": [{"position": 1, "internal_name": "variavel_1", "exemplo": "a"}]}, "começar nem terminar"),
    ({"body_text": "Olá, sua parcela venceu {{1}}", "variables": [{"position": 1, "internal_name": "variavel_1", "exemplo": "a"}]}, "começar nem terminar"),
    ({"body_text": "Olá {{1}} e {{3}}.", "variables": [{"position": 1, "internal_name": "variavel_1", "exemplo": "a"},
                                                      {"position": 3, "internal_name": "variavel_3", "exemplo": "b"}]}, "em sequência"),
    ({"body_text": "Olá " + "x" * 1030 + ".", "variables": []}, "passa de 1024"),
    ({"variables": [{"position": 1, "internal_name": "variavel_1", "exemplo": "Maria"}]}, "não batem"),
    ({"botoes": [{"tipo": "url", "texto": "Pagar", "url": "site.com"}]}, "https://"),
    ({"botoes": [{"tipo": "url", "texto": "Pagar", "url": "https://site.com/{{1}}/x"}]}, "https://"),
    ({"botoes": [{"tipo": "resposta_rapida", "texto": ""}]}, "preencha o texto"),
    ({"botoes": [{"tipo": "resposta_rapida", "texto": "x" * 26}]}, "passa de 25"),
    ({"botoes": [{"tipo": "url", "texto": f"Link {i}", "url": "https://site.com"} for i in range(3)]}, "botões de link"),
    ({"botoes": [{"tipo": "resposta_rapida", "texto": "Sim"}, {"tipo": "url", "texto": "Site", "url": "https://site.com"},
                 {"tipo": "resposta_rapida", "texto": "Não"}]}, "juntas"),
    ({"botoes": [{"tipo": "url", "texto": "Boleto", "url": "https://site.com/{{1}}"}]}, "links não batem"),
]
for n, (campos, motivo) in enumerate(invalidos):
    resp = criar(name=f"Incompleto {n}", **{"meta_template_name": f"incompleto_{n}", **campos})
    assert resp.status_code == 201, (campos, resp.text)
    resp = enviar(resp.json()["id"])
    assert resp.status_code == 400 and motivo in resp.json()["detail"], (campos, resp.text)
assert CHAMADAS == []

# Editar o rascunho: completa o que faltava e passa a poder enviar
incompleto = criar(name="Só o nome", meta_template_name="", body_text="", variables=[]).json()
assert incompleto["status"] == "draft" and incompleto["meta_template_name"] == "" and incompleto["botoes"] == []
assert client.put(f"/templates/{incompleto['id']}", json={"name": "Só o nome", "meta_template_name": "incompleto_3"},
                  headers=h).status_code == 409
editado = client.put(f"/templates/{incompleto['id']}", headers=h, json={
    "name": "Com botões", "meta_template_name": "com_botoes", "category": "MARKETING",
    "body_text": "Olá {{1}}, veja seu boleto.",
    "variables": [{"position": 1, "internal_name": "variavel_1", "exemplo": "Maria"},
                  {"position": 2, "internal_name": "link_botao_2", "exemplo": "ABC123", "campo_sugerido": "codigo", "botao_indice": 1}],
    "botoes": [{"tipo": "url", "texto": "Site", "url": "https://lojastopfama.com.br"},
               {"tipo": "url", "texto": "Boleto", "url": "https://lojastopfama.com.br/boleto/{{1}}"},
               {"tipo": "resposta_rapida", "texto": "Já paguei"}],
})
assert editado.status_code == 200, editado.text
editado = editado.json()
assert editado["id"] == incompleto["id"] and editado["category"] == "MARKETING"
assert [(v["position"], v["botao_indice"]) for v in editado["variables"]] == [(1, None), (2, 1)]
assert [b["tipo"] for b in editado["botoes"]] == ["url", "url", "resposta_rapida"]
resp = enviar(editado["id"])
assert resp.status_code == 200, resp.text
id_na_meta = resp.json()["meta_template_id"]
assert json.loads(CHAMADAS[-1]["corpo"])["components"] == [
    {"type": "BODY", "text": "Olá {{1}}, veja seu boleto.", "example": {"body_text": [["Maria"]]}},
    {"type": "BUTTONS", "buttons": [
        {"type": "URL", "text": "Site", "url": "https://lojastopfama.com.br"},
        {"type": "URL", "text": "Boleto", "url": "https://lojastopfama.com.br/boleto/{{1}}",
         "example": ["https://lojastopfama.com.br/boleto/ABC123"]},
        {"type": "QUICK_REPLY", "text": "Já paguei"},
    ]},
]
# No envio, o valor do link variável vai no índice do botão, fora dos parâmetros do corpo
db = SessionLocal()
tpl = db.get(models.Template, editado["id"])
assert montar_parametros_envio(tpl, {"variavel_1": "Ana", "link_botao_2": "XYZ"}) == (["Ana"], None, {1: "XYZ"})
db.close()
CHAMADAS.clear()
asyncio.run(MetaClient(access_token="T").send_template_message(
    "PN1", "5511999998888", "com_botoes", "pt_BR", ["Ana"], botoes_params={1: "XYZ"}))
assert json.loads(CHAMADAS[-1]["corpo"])["template"]["components"] == [
    {"type": "body", "parameters": [{"type": "text", "text": "Ana"}]},
    {"type": "button", "sub_type": "url", "index": "1", "parameters": [{"type": "text", "text": "XYZ"}]},
]

# Sincronizado da Meta: botões na ordem dela e a variável do link depois das do corpo
remoto = {"components": [
    {"type": "BODY", "text": "Oi {{1}}"},
    {"type": "BUTTONS", "buttons": [{"type": "QUICK_REPLY", "text": "Sim"}, {"type": "PHONE_NUMBER", "text": "Ligar", "phone_number": "+55"},
                                    {"type": "URL", "text": "Boleto", "url": "https://x.com/{{1}}"}]},
]}
assert [b["tipo"] for b in _extract_botoes(remoto)] == ["resposta_rapida", "phone_number", "url"]
assert _extract_variables(remoto) == [(1, "variavel_1", None), (2, "link_botao_3", 2)]

# Em análise na Meta não edita; aprovado edita e volta para análise, sem mudar nome nem categoria
def editar(**campos):
    corpo = {"name": "Com botões", "meta_template_name": "com_botoes", "category": "MARKETING",
             "body_text": "Oi {{1}}, veja seu boleto.", "variables": editado["variables"], "botoes": editado["botoes"], **campos}
    return client.put(f"/templates/{editado['id']}", json=corpo, headers=h)


resp = editar()
assert resp.status_code == 400 and "aprovado, reprovado ou pausado" in resp.json()["detail"]
db = SessionLocal()
db.get(models.Template, editado["id"]).meta_status_raw = "APPROVED"
db.commit()
db.close()
CHAMADAS.clear()
assert "nome" in editar(meta_template_name="outro_nome").json()["detail"]
assert "categoria" in editar(category="UTILITY").json()["detail"]
resp = editar(variables=[editado["variables"][1]])
assert resp.status_code == 400 and "não batem" in resp.json()["detail"]
assert CHAMADAS == []
# Em uso numa faixa: não muda as variáveis (decisão do dono), só texto e botões
db = SessionLocal()
faixa = models.Faixa(name="Faixa com botões")
db.add(faixa)
db.flush()
numero = db.query(models.WhatsappNumber).filter(models.WhatsappNumber.phone_number_id == "PN1").one()
db.add(models.FaixaEnvio(faixa_id=faixa.id, whatsapp_number_id=numero.id, template_id=editado["id"]))
db.commit()
db.close()
resp = editar(body_text="Oi {{1}}, veja seu boleto, {{2}}.", variables=[
    editado["variables"][0], {"position": 2, "internal_name": "variavel_2", "exemplo": "hoje"},
    {**editado["variables"][1], "position": 3}])
assert resp.status_code == 400 and "em uso em Faixa com botões" in resp.json()["detail"]
assert CHAMADAS == []
resp = editar()
assert resp.status_code == 200, resp.text
assert resp.json()["body_text"] == "Oi {{1}}, veja seu boleto." and resp.json()["status"] == "pending"
assert [v["id"] for v in resp.json()["variables"]] == [v["id"] for v in editado["variables"]]
edicao = CHAMADAS[-1]
assert edicao["caminho"] == id_na_meta and "category" not in json.loads(edicao["corpo"])
assert json.loads(edicao["corpo"])["components"][0]["text"] == "Oi {{1}}, veja seu boleto."
# Reprovado pode mudar a categoria, que vai junto na edição
db = SessionLocal()
db.get(models.Template, editado["id"]).meta_status_raw = "REJECTED"
db.commit()
db.close()
resp = editar(category="UTILITY")
assert resp.status_code == 200, resp.text
assert json.loads(CHAMADAS[-1]["corpo"])["category"] == "UTILITY"
CHAMADAS.clear()

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
resp = enviar(sem_exemplo["id"])
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
