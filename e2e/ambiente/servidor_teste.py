"""Sobe o backend em modo de TESTE, com toda integração externa simulada:

- Meta Graph API: httpx.MockTransport no MetaClient (templates, números, custo,
  envio). Nenhuma mensagem real sai — os envios ficam só em memória
  (GET /__e2e/envios para conferir).
- Chatwoot: ChatwootClient._request simulado.
- Google Sheets (planilha de lojas): google_client.ler_aba simulado.
- Câmbio USD→BRL: cotação fixa de 5,00.
- SETA: um Postgres local criado por seta_falso.py (variáveis SETA_DB_*).

Nunca usa o .env do projeto: rode a partir desta pasta com as variáveis de
teste (ver e2e/README.md). Uso: python servidor_teste.py [porta]
"""

import json
import os
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

BACKEND = Path(__file__).resolve().parents[2] / "apps" / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(Path(__file__).resolve().parent)  # garante que nenhum .env do projeto é lido

for var in ("DATABASE_URL", "SETA_DB_HOST", "JWT_SECRET", "ENCRYPTION_KEY", "ADMIN_PASSWORD"):
    if not os.environ.get(var):
        sys.exit(f"Defina {var} (ver e2e/README.md)")
if "seta" in os.environ["DATABASE_URL"].split("/")[-1] and "fake" not in os.environ["DATABASE_URL"]:
    sys.exit("DATABASE_URL parece apontar para o SETA — recusado")

from app import cambio, chatwoot_client, google_client, lojas_iniciais, meta_client, remarketing  # noqa: E402

WABA = "1111111111"
NUMEROS = [
    {"id": "900001", "display_phone_number": "+55 11 4000-0001", "verified_name": "TopFama Cobrança",
     "quality_rating": "GREEN", "status": "CONNECTED"},
    {"id": "900002", "display_phone_number": "+55 11 4000-0002", "verified_name": "TopFama Lembrete",
     "quality_rating": "YELLOW", "status": "CONNECTED"},
]
TEMPLATES = [
    {"id": "tpl-1", "name": "cobranca_atraso", "language": "pt_BR", "category": "UTILITY", "status": "APPROVED",
     "components": [{"type": "BODY", "text": "Olá {{1}}, seu débito de R$ {{2}} venceu em {{3}}. Código {{4}}."}]},
    {"id": "tpl-2", "name": "lembrete_vencimento", "language": "pt_BR", "category": "UTILITY", "status": "APPROVED",
     "components": [{"type": "BODY", "text": "Oi {{1}}, sua parcela vence amanhã."}]},
    {"id": "tpl-3", "name": "promo_reprovada", "language": "pt_BR", "category": "MARKETING", "status": "REJECTED",
     "components": [{"type": "BODY", "text": "Promoção {{1}}"}]},
]
ENVIOS: list[dict] = []
TOKEN_INVALIDO = "token-invalido"


def _meta(request: httpx.Request) -> httpx.Response:
    auth = request.headers.get("authorization", "")
    if TOKEN_INVALIDO in auth:
        return httpx.Response(401, json={"error": {"message": "Invalid OAuth access token", "code": 190}})
    path = request.url.path.split("/", 2)[-1]
    if path == "me":
        return httpx.Response(200, json={"id": "42", "name": "Conta de teste"})
    if path.endswith("/message_templates"):
        if request.method == "POST":
            body = json.loads(request.content or b"{}")
            novo = {**body, "id": f"tpl-{len(TEMPLATES) + 1}", "status": "PENDING"}
            TEMPLATES.append(novo)
            return httpx.Response(200, json={"id": novo["id"], "status": "PENDING", "category": body.get("category")})
        return httpx.Response(200, json={"data": TEMPLATES})
    if path.endswith("/phone_numbers"):
        return httpx.Response(200, json={"data": NUMEROS})
    if path.endswith("/messages"):
        body = json.loads(request.content or b"{}")
        ENVIOS.append({"canal": "meta", "phone_number_id": path.split("/")[0], **body})
        return httpx.Response(200, json={"messages": [{"id": f"wamid.teste{len(ENVIOS)}"}]})
    if path == WABA or path.startswith(WABA):
        # pricing analytics: 1 ponto por número nos últimos 3 dias
        agora = int(time.time())
        pontos = []
        for d in range(3):
            inicio = agora - (d + 1) * 86400
            for n in NUMEROS:
                pontos.append({"start": inicio, "end": inicio + 86400, "phone_number": n["display_phone_number"],
                               "volume": 10 + d, "cost": 0.5 + d / 10, "pricing_type": "REGULAR"})
        return httpx.Response(200, json={"pricing_analytics": {"data": [{"data_points": pontos}]}, "id": WABA})
    for t in TEMPLATES:
        if path == t["id"]:
            return httpx.Response(200, json={"status": t["status"], "name": t["name"], "category": t["category"]})
    return httpx.Response(404, json={"error": {"message": f"rota simulada inexistente: {path}"}})


meta_client.MetaClient.default_transport = httpx.MockTransport(_meta)


async def _chatwoot(self, method: str, path: str, **kwargs):
    if path == "":
        return {"id": self.account_id, "name": "Conta Chatwoot de teste"}
    if path.startswith("contacts/search"):
        return {"payload": []}
    if path == "contacts":
        return {"payload": {"contact": {"id": 7}, "contact_inbox": {"source_id": "src-7"}}}
    if "conversations" in path and method == "GET":
        return {"payload": []}
    if path == "conversations":
        return {"id": 99}
    if path.endswith("/messages"):
        ENVIOS.append({"canal": "chatwoot", "path": path, **(kwargs.get("json") or {})})
        return {"id": len(ENVIOS)}
    if path.startswith("inboxes"):
        return {"payload": [{"id": 1, "name": "WhatsApp teste", "channel_type": "Channel::Whatsapp"}]}
    return {}


chatwoot_client.ChatwootClient._request = _chatwoot

LOJAS = [
    ["FILIAL", "NOME COM COD", "REGIONAL", "ESTADO", "CLUSTER INAD", "CLUSTER POPULACAO"],
    ["1", "01 - LOJA CENTRO", "SUL", "SP", "ALTO", "GRANDE"],
    ["2", "02 - LOJA NORTE", "NORTE", "SP", "BAIXO", "MEDIA"],
    ["6", "06 - LOJA PRAIA", "SUL", "RJ", "MEDIO", "PEQUENA"],
    ["10", "10 - LOJA INTERIOR", "CENTRO", "MG", "ALTO", "PEQUENA"],
]
google_client.ler_aba = lambda db, planilha_id, gid: LOJAS
# a tabela `lojas` nasce com a carga da planilha real: no teste, usa as lojas falsas
lojas_iniciais.LOJAS_INICIAIS = [
    ("01", "01 - LOJA CENTRO", "SUL", "SP", "SYSCOB", "ALTO", "GRANDE"),
    ("02", "02 - LOJA NORTE", "NORTE", "SP", "MJ", "BAIXO", "MEDIA"),
    ("06", "06 - LOJA PRAIA", "SUL", "RJ", "SYSCOB", "MEDIO", "PEQUENA"),
    ("10", "10 - LOJA INTERIOR", "CENTRO", "MG", None, "ALTO", "PEQUENA"),
]
google_client.is_configured = lambda: True


class _ContaGoogle:
    email = "teste@topfama.com.br"
    conectado_em = None
    id = "google-teste"


google_client.conta_conectada = lambda db: _ContaGoogle()


async def _cotacao() -> float:
    return 5.0


cambio.cotacao_usd_brl = _cotacao

# Portal TopFamaRenegocie: quem desistiu (códigos do SETA falso). Chave aceita: "chave-teste".
CHAVE_RENEGOCIE = "chave-teste"


def _renegocie(request: httpx.Request) -> httpx.Response:
    if request.headers.get("X-Integration-Key") != CHAVE_RENEGOCIE:
        return httpx.Response(401, json={"error": {"code": "INTEGRATION_KEY_INVALID"}})
    if request.url.path != "/api/v1/integracoes/remarketing":
        return httpx.Response(404, json={})
    agora = datetime.now(timezone.utc)

    def cliente(codigo, segmento, dias_atras, celular=None, proposta=None, ref=None):
        return {
            "segmento": segmento, "person_ids": [codigo], "nome": f"Cliente {codigo}",
            "celular": celular, "evento_em": (agora - timedelta(days=dias_atras)).isoformat(),
            "proposta": proposta, "referencia_seta": ref, "loja": None,
        }

    return httpx.Response(200, json={"clientes": [
        cliente("00000003", "SO_IDENTIFICOU", 2, celular="5511988887777"),
        cliente("00000004", "VIU_PROPOSTA", 40),
        cliente("00000005", "ACORDO_SEM_ENTRADA", 3, proposta="P-900", ref="RE000900"),
        cliente("00000027", "ACORDO_SEM_ENTRADA", 3, proposta="P-901", ref="RE000901"),
        cliente("00000009", "CANCELOU_PROPOSTA", 1, proposta="P-902"),
    ]})


remarketing.TRANSPORTE = httpx.MockTransport(_renegocie)

from app.main import app  # noqa: E402


@app.get("/__e2e/envios", include_in_schema=False)
def envios_simulados():
    return ENVIOS


@app.post("/__e2e/campanhas/enviar", include_in_schema=False)
def enviar_campanhas():
    """Envia na hora os pendentes das campanhas (sem depender do horário de
    disparo do relógio), pelo mesmo caminho que marca o lead como cobrado."""

    from app import models
    from app.database import SessionLocal
    from app.dispatch_service import _marcar_lead_cobrado

    db = SessionLocal()
    try:
        # campanhas e remarketing (campanha fixa)
        faixas = [c.faixa_id for c in db.query(models.Campanha)] + [
            f.id for f in db.query(models.Faixa).filter(models.Faixa.tipo == models.TIPO_REMARKETING)
        ]
        itens = db.query(models.QueueItem).filter(
            models.QueueItem.faixa_id.in_(faixas), models.QueueItem.status == models.QueueStatus.pending
        ).all()
        for item in itens:
            item.status = models.QueueStatus.sent
            item.sent_at = datetime.utcnow()
            _marcar_lead_cobrado(db, item)
        db.commit()
        return {"enviados": len(itens)}
    finally:
        db.close()


@app.post("/__e2e/campanhas/regua-no-dia-seguinte", include_in_schema=False)
def regua_no_dia_seguinte():
    """Simula a virada do dia: o que a campanha mandou hoje passa a ser de
    ontem, e roda a entrada na régua de quem recebeu a campanha."""

    from app import campanhas, models
    from app.database import SessionLocal
    from app.fila_automatica import inicio_hoje_utc

    db = SessionLocal()
    try:
        # campanhas e remarketing (campanha fixa)
        faixas = [c.faixa_id for c in db.query(models.Campanha)] + [
            f.id for f in db.query(models.Faixa).filter(models.Faixa.tipo == models.TIPO_REMARKETING)
        ]
        um_dia = timedelta(days=1)
        for lead in db.query(models.Lead).filter(models.Lead.campanha_id != "", models.Lead.cobrado_em >= inicio_hoje_utc()):
            lead.cobrado_em -= um_dia
        for item in db.query(models.QueueItem).filter(
            models.QueueItem.faixa_id.in_(faixas), models.QueueItem.sent_at >= inicio_hoje_utc()
        ):
            item.sent_at -= um_dia
        db.commit()
        for _ in range(60):
            resultado = campanhas.enfileirar_na_regua(db)
            if resultado["status"] == "ready":
                return resultado
            time.sleep(1)
        return resultado
    finally:
        db.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(sys.argv[1]) if len(sys.argv) > 1 else 8010)
