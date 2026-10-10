"""Único ponto de integração com a API do Chatwoot: usado para enviar
cobrança pelos números cuja inbox do Chatwoot foi vinculada em Configurações
(WhatsappNumber.chatwoot_inbox_id), como alternativa a enviar direto pela
Graph API da Meta (meta_client.py).

Fluxo pra mandar um template pra um cliente (a API do Chatwoot não tem um
"enviar template" direto: é preciso ter um contato e uma conversa primeiro):
1. Busca o contato pelo celular; cria se não existir.
2. Busca uma conversa aberta do contato nessa inbox; cria se não existir.
3. Cria a mensagem na conversa, com os parâmetros do template
   (`template_params`) — é isso que faz o Chatwoot disparar de fato o
   template aprovado via WhatsApp, mesmo fora da janela de 24h.
"""

import httpx

from sqlalchemy.orm import Session

from . import crypto, models


class ChatwootAPIError(Exception):
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self.payload = payload
        super().__init__(f"Chatwoot API error ({status_code}): {payload}")


class ChatwootConfigError(Exception):
    pass


class ChatwootClient:
    default_transport: httpx.AsyncBaseTransport | None = None

    def __init__(
        self,
        base_url: str,
        account_id: str,
        api_access_token: str,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.account_id = account_id
        self.api_access_token = api_access_token
        self._transport = transport if transport is not None else self.default_transport

    def _headers(self) -> dict:
        return {"api_access_token": self.api_access_token}

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        url = f"{self.base_url}/api/v1/accounts/{self.account_id}/{path}"
        async with httpx.AsyncClient(timeout=30, transport=self._transport) as client:
            response = await client.request(method, url, headers=self._headers(), **kwargs)
        if response.status_code >= 400:
            raise ChatwootAPIError(response.status_code, response.json() if response.content else {})
        return response.json() if response.content else {}

    async def test_connection(self) -> dict:
        return await self._request("GET", "")

    async def buscar_ou_criar_contato(self, inbox_id: int, celular: str, nome: str) -> tuple[str, str]:
        """Retorna (contact_id, source_id) do contato com esse celular nessa
        inbox — source_id é o identificador do "contact_inbox" (canal
        específico do contato), exigido pra criar a conversa.

        `celular` chega aqui no formato interno do sistema (só dígitos,
        55DDD9XXXXXXXX — ver utils/phone.py); a API do Chatwoot exige E.164
        (com "+") no campo phone_number, senão responde 422.

        O telefone é único por CONTA no Chatwoot, não por inbox: se o
        contato já existe (de outro número/inbox que falou com o mesmo
        cliente) mas ainda não tem canal nesta inbox, tentar criar de novo
        responde 422 "Phone number has already been taken" — nesse caso só
        associa um contact_inbox novo ao contato existente."""

        celular_e164 = f"+{celular}"
        busca = await self._request("GET", "contacts/search", params={"q": celular_e164})
        contato_existente = None
        for contato in busca.get("payload", []):
            if contato.get("phone_number") == celular_e164:
                contato_existente = contato
                for contact_inbox in contato.get("contact_inboxes", []):
                    if contact_inbox.get("inbox", {}).get("id") == inbox_id:
                        return str(contato["id"]), str(contact_inbox["source_id"])
                break

        if contato_existente is not None:
            vinculo = await self._request(
                "POST",
                f"contacts/{contato_existente['id']}/contact_inboxes",
                json={"inbox_id": inbox_id},
            )
            return str(contato_existente["id"]), str(vinculo["source_id"])

        criado = await self._request(
            "POST",
            "contacts",
            json={"inbox_id": inbox_id, "name": nome or celular_e164, "phone_number": celular_e164},
        )
        payload = criado.get("payload", criado)
        contato_id = str(payload["contact"]["id"])
        source_id = str(payload["contact_inbox"]["source_id"])
        return contato_id, source_id

    async def buscar_ou_criar_conversa(self, inbox_id: int, contact_id: str, source_id: str) -> int:
        conversas = await self._request("GET", f"contacts/{contact_id}/conversations")
        for conversa in conversas.get("payload", []):
            if conversa.get("inbox_id") == inbox_id:
                return int(conversa["id"])

        criada = await self._request(
            "POST",
            "conversations",
            json={"source_id": source_id, "inbox_id": inbox_id, "contact_id": contact_id, "status": "pending"},
        )
        return int(criada["id"])

    async def enviar_mensagem_template(
        self,
        conversation_id: int,
        body_text: str,
        template_name: str,
        category: str,
        language: str,
        body_params: list[str],
        header_image_url: str | None = None,
        botoes: list[dict] | None = None,
        botoes_params: dict[int, str] | None = None,
    ) -> dict:
        """`body_text` é o corpo do template ORIGINAL, com `{{1}}`, `{{2}}`...
        ainda não substituídos — com `content_mode: raw_template`, é o
        Chatwoot quem faz a substituição ao renderizar a mensagem na
        conversa. Sem esse campo, o Chatwoot registra o envio mas a
        mensagem de abertura (a que efetivamente cria a conversa) não
        aparece na tela do agente."""

        processed_params: dict = {"body": {str(i + 1): valor for i, valor in enumerate(body_params)}}
        if header_image_url:
            processed_params["header"] = {"media_url": header_image_url, "media_type": "image"}
        if botoes_params:
            # O Chatwoot usa a posição na lista como índice do botão: vai um item por botão do template
            processed_params["buttons"] = [
                {"type": "url", "parameter": botoes_params[i]} if i in botoes_params else {"type": b.get("tipo")}
                for i, b in enumerate(botoes or [])
            ]

        payload = {
            "content": body_text,
            "message_type": "outgoing",
            "template_params": {
                "name": template_name,
                "category": category,
                "language": language,
                "content_mode": "raw_template",
                "processed_params": processed_params,
            },
        }
        return await self._request("POST", f"conversations/{conversation_id}/messages", json=payload)

    async def buscar_status_mensagem(self, conversation_id: int, message_id: int) -> tuple[str, str | None]:
        """Consulta as mensagens da conversa e retorna (status, external_error|None) da mensagem informada."""
        conversas = await self._request("GET", f"conversations/{conversation_id}/messages")
        for msg in conversas.get("payload", []):
            if msg.get("id") == message_id:
                status = msg.get("status", "sent")
                error = (msg.get("content_attributes") or {}).get("external_error")
                return status, error
        return "sent", None

    async def listar_webhooks(self) -> list[dict]:
        """Lista os webhooks configurados na conta do Chatwoot."""
        res = await self._request("GET", "webhooks")
        return res.get("payload", {}).get("webhooks", [])

    async def criar_webhook(self, url: str, subscriptions: list[str] | None = None) -> dict:
        """Cria um webhook na conta do Chatwoot com os eventos especificados."""
        subs = subscriptions or ["message_created", "message_updated"]
        res = await self._request("POST", "webhooks", json={
            "webhook": {
                "url": url,
                "subscriptions": subs,
            }
        })
        return res.get("payload", {}).get("webhook", {})

    async def garantir_webhook(self, url: str, subscriptions: list[str] | None = None) -> dict:
        """Garante que o webhook para a URL informada esteja cadastrado no Chatwoot."""
        for wh in await self.listar_webhooks():
            if wh.get("url") == url:
                return wh
        return await self.criar_webhook(url, subscriptions)

    async def obter_mensagem(self, conversation_id: int, message_id: int) -> dict | None:
        """Pagina até o ID exato, sem confundir com mensagens do atendente."""
        antes = None
        while True:
            resposta = await self._request(
                "GET", f"conversations/{conversation_id}/messages",
                params={"before": antes} if antes is not None else {},
            )
            mensagens = resposta.get("payload", [])
            if not isinstance(mensagens, list) or not mensagens:
                return None
            for mensagem in mensagens:
                if str(mensagem.get("id")) == str(message_id):
                    return mensagem
            ids = [int(m["id"]) for m in mensagens if str(m.get("id", "")).isdigit()]
            if not ids or min(ids) < message_id or (antes is not None and min(ids) >= antes):
                return None
            antes = min(ids)


def is_configured(db: Session) -> bool:
    return db.query(models.ConfiguracaoChatwoot).first() is not None


def cliente_configurado(db: Session) -> ChatwootClient:
    config = db.query(models.ConfiguracaoChatwoot).first()
    if not config:
        raise ChatwootConfigError("Chatwoot não configurado: cadastre em Configurações → Chatwoot")
    token = crypto.decifrar(config.api_access_token_cifrado)
    if not token:
        raise ChatwootConfigError("Não foi possível decifrar o token do Chatwoot com a chave atual")
    return ChatwootClient(base_url=config.base_url, account_id=config.account_id, api_access_token=token)
