"""Imagem de cabeçalho do template no envio (régua, campanha e remarketing
passam todos por dispatch_service.enviar_item).

Sem banco: objetos simples no lugar dos modelos e a Meta/Chatwoot simulados,
conferindo o payload que sairia. Rodar: PYTHONPATH=. .venv/bin/python tests/test_imagem_template.py
"""

import asyncio
import json
import os
import tempfile
from types import SimpleNamespace

import httpx
from cryptography.fernet import Fernet

MEDIA = tempfile.mkdtemp()
os.environ["MEDIA_DIR"] = MEDIA
os.environ.setdefault("ENCRYPTION_KEY", Fernet.generate_key().decode())

from app import chatwoot_client, dispatch_service, models  # noqa: E402
from app.config import settings  # noqa: E402
from app.meta_client import MetaClient  # noqa: E402

chamadas: list[dict] = []
falhar_envio = {"ativo": False}


def _meta(request: httpx.Request) -> httpx.Response:
    caminho = request.url.path.split("/", 2)[-1]
    if caminho.endswith("/media"):
        corpo = request.content
        assert b'name="messaging_product"' in corpo and b"whatsapp" in corpo, corpo[:300]
        assert b'name="file"; filename="tpl-1.png"' in corpo, corpo[:300]
        assert b"image/png" in corpo
        chamadas.append({"tipo": "upload"})
        return httpx.Response(200, json={"id": f"midia-{sum(c['tipo'] == 'upload' for c in chamadas)}"})
    if caminho.endswith("/messages"):
        chamadas.append({"tipo": "envio", "json": json.loads(request.content)})
        if falhar_envio["ativo"]:
            return httpx.Response(400, json={"error": {"message": "media expirada"}})
        return httpx.Response(200, json={"messages": [{"id": "wamid.1"}]})
    return httpx.Response(404, json={"error": {"message": caminho}})


MetaClient.default_transport = httpx.MockTransport(_meta)
dispatch_service.token_do_numero = lambda db, number: "token"


class Cw:
    def __init__(self):
        self.enviados = []

    async def buscar_ou_criar_contato(self, *a):
        return 1, "src"

    async def buscar_ou_criar_conversa(self, *a):
        return 9

    async def enviar_mensagem_template(self, conversation_id, body_text, **kw):
        self.enviados.append(kw)


cw = Cw()
chatwoot_client.cliente_configurado = lambda db: cw


class Db:
    def __init__(self):
        self.erros = []

    def add(self, obj):
        self.erros.append(obj.message)

    def get(self, *a):
        return None

    def begin_nested(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def cenario(image_url, inbox=None):
    template = SimpleNamespace(
        id="tpl-1", name="Cobrança com imagem", meta_template_name="cobranca_img", language="pt_BR",
        category="UTILITY", body_text="Olá {{1}}", header_type=models.TemplateHeaderType.image,
        image_url=image_url, variables=[SimpleNamespace(internal_name="nome", position=1, botao_indice=None)], botoes=[],
    )
    number = SimpleNamespace(id="n1", phone_number_id="900001", chatwoot_inbox_id=inbox)
    envio = SimpleNamespace(id="e1", faixa_id="f1", whatsapp_number=number, template=template)
    item = SimpleNamespace(
        id="q1", faixa_id="f1", celular="5511999990000", nome="Ana", variables_json={"nome": "Ana"},
        status=models.QueueStatus.reserved, error_message=None, sent_at=None, whatsapp_message_id=None,
        whatsapp_number_id=None, reserved_by=None, codigo_cliente="1",
    )
    return envio, item


def enviar(image_url, inbox=None):
    envio, item = cenario(image_url, inbox)
    db = Db()
    asyncio.run(dispatch_service.enviar_item(envio, item, db))
    return item, db


with open(os.path.join(MEDIA, "tpl-1.png"), "wb") as f:
    f.write(b"\x89PNG imagem de teste")

# 1. Meta: a imagem subida (link interno /media/...) vai como media id no cabeçalho
item, _ = enviar("/media/tpl-1.png")
assert item.status == models.QueueStatus.sent, item.error_message
envio = [c for c in chamadas if c["tipo"] == "envio"][-1]["json"]
assert envio["template"]["components"][0] == {
    "type": "header", "parameters": [{"type": "image", "image": {"id": "midia-1"}}]
}, envio
assert envio["template"]["components"][1]["parameters"] == [{"type": "text", "text": "Ana"}]

# 2. O mesmo arquivo não sobe de novo a cada mensagem (link absoluto também acha o arquivo)
enviar("https://api.exemplo.com.br/media/tpl-1.png")
assert sum(c["tipo"] == "upload" for c in chamadas) == 1, chamadas
# link com ?v= (versão da subida) também acha o arquivo
item, _ = enviar("/media/tpl-1.png?v=abc123")
assert item.status == models.QueueStatus.sent, item.error_message
assert sum(c["tipo"] == "upload" for c in chamadas) == 1, chamadas

# 3. Meta recusou o envio: a mídia é esquecida e o próximo envio sobe de novo
falhar_envio["ativo"] = True
item, _ = enviar("/media/tpl-1.png")
assert item.status == models.QueueStatus.error
falhar_envio["ativo"] = False
item, _ = enviar("/media/tpl-1.png")
assert item.status == models.QueueStatus.sent
assert sum(c["tipo"] == "upload" for c in chamadas) == 2, chamadas

# 4. Template com cabeçalho de imagem sem imagem: erro claro, nada vai para a Meta e o cliente fica livre
antes = len(chamadas)
item, db = enviar(None)
assert item.status == models.QueueStatus.error and item.sent_at is None
assert "nenhuma imagem foi subida" in item.error_message, item.error_message
assert len(chamadas) == antes

# 5. Chatwoot: link público montado com PUBLIC_BASE_URL
settings.public_base_url = "https://api.topfama.exemplo/"
item, _ = enviar("/media/tpl-1.png", inbox=5)
assert item.status == models.QueueStatus.sent, item.error_message
assert cw.enviados[-1]["header_image_url"] == "https://api.topfama.exemplo/media/tpl-1.png"

# 6. Chatwoot com link absoluto guardado na subida da imagem
settings.public_base_url = ""
item, _ = enviar("https://api.exemplo.com.br/media/tpl-1.png", inbox=5)
assert cw.enviados[-1]["header_image_url"] == "https://api.exemplo.com.br/media/tpl-1.png"

# 7. Chatwoot sem link público: erro claro em vez de mandar sem a imagem
n = len(cw.enviados)
item, _ = enviar("/media/tpl-1.png", inbox=5)
assert item.status == models.QueueStatus.error and item.sent_at is None
assert "link público" in item.error_message
assert len(cw.enviados) == n

# 8. Template sem cabeçalho de imagem continua sem componente header
envio_, item = cenario(None)
envio_.template.header_type = models.TemplateHeaderType.none
asyncio.run(dispatch_service.enviar_item(envio_, item, Db()))
ultimo = [c for c in chamadas if c["tipo"] == "envio"][-1]["json"]
assert [c["type"] for c in ultimo["template"]["components"]] == ["body"], ultimo

# 9. Link guardado na subida da imagem: endereço por onde o navegador chegou ao backend
from starlette.requests import Request  # noqa: E402

from app.routers.templates import _base_publica  # noqa: E402


def req(headers, scheme="http"):
    return Request({"type": "http", "scheme": scheme, "path": "/", "server": ("x", 80),
                    "headers": [(k.encode(), v.encode()) for k, v in headers.items()]})


assert _base_publica(req({"host": "api.topfama.com.br", "x-forwarded-proto": "https"})) == "https://api.topfama.com.br"
assert _base_publica(req({"host": "127.0.0.1:18001", "x-forwarded-host": "api.topfama.com.br"})) == "http://api.topfama.com.br"
assert _base_publica(req({"host": "localhost:8000"})) is None
assert _base_publica(req({"host": "127.0.0.1:8000"})) is None
assert _base_publica(req({"host": "backend:8000"})) is None
settings.public_base_url = "https://api.topfama.exemplo"
assert _base_publica(req({"host": "api.topfama.com.br"})) is None  # o link sai do PUBLIC_BASE_URL no envio
settings.public_base_url = ""

print("OK")
