"""Cliente para a Graph API da Meta (WhatsApp Business Management + Cloud API).

Substitui a lógica que antes vivia em nós HTTP Request do n8n: o backend
chama a Meta diretamente para listar/criar templates, listar números e
enviar mensagens de template.
"""

import httpx

from .config import settings


class MetaAPIError(Exception):
    def __init__(self, status_code: int, payload: dict):
        self.status_code = status_code
        self.payload = payload
        message = payload.get("error", {}).get("message", str(payload))
        super().__init__(f"Meta API error ({status_code}): {message}")


class MetaClient:
    def __init__(self, access_token: str | None = None):
        self.access_token = access_token or settings.meta_access_token
        self.base_url = f"https://graph.facebook.com/{settings.meta_graph_api_version}"

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    async def _request(self, method: str, path: str, **kwargs) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.request(
                method, f"{self.base_url}/{path}", headers=self._headers(), **kwargs
            )
        if response.status_code >= 400:
            raise MetaAPIError(response.status_code, response.json())
        return response.json()

    async def list_templates(self, waba_id: str) -> list[dict]:
        data = await self._request(
            "GET",
            f"{waba_id}/message_templates",
            params={"limit": 200, "fields": "name,language,category,status,components,id"},
        )
        return data.get("data", [])

    async def get_template_status(self, meta_template_id: str) -> dict:
        return await self._request("GET", meta_template_id, params={"fields": "status,name,category"})

    async def create_template(self, waba_id: str, payload: dict) -> dict:
        return await self._request("POST", f"{waba_id}/message_templates", json=payload)

    async def list_phone_numbers(self, waba_id: str) -> list[dict]:
        data = await self._request(
            "GET",
            f"{waba_id}/phone_numbers",
            params={"fields": "id,display_phone_number,verified_name,quality_rating,status"},
        )
        return data.get("data", [])

    async def send_template_message(
        self,
        phone_number_id: str,
        to: str,
        template_name: str,
        language_code: str,
        body_params: list[str],
        header_image_link: str | None = None,
    ) -> dict:
        components = []
        if header_image_link:
            components.append(
                {"type": "header", "parameters": [{"type": "image", "image": {"link": header_image_link}}]}
            )
        if body_params:
            components.append(
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": str(value)} for value in body_params],
                }
            )
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language_code},
                "components": components,
            },
        }
        return await self._request("POST", f"{phone_number_id}/messages", json=payload)
