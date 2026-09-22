"""Único ponto de integração com o Google: OAuth2 (fluxo de código com refresh
token) e leitura de planilhas pela API do Google Sheets.

O escopo é só leitura de planilhas (`spreadsheets.readonly`) mais `email`, para
mostrar qual conta está conectada. Sem `GOOGLE_CLIENT_ID`/`GOOGLE_CLIENT_SECRET`
a integração fica desligada e o resto do sistema segue funcionando.
"""

import base64
import json
import logging
import time
from urllib.parse import quote, urlencode

import httpx
from sqlalchemy.orm import Session

from . import crypto, models
from .config import settings

logger = logging.getLogger(__name__)

URL_AUTORIZACAO = "https://accounts.google.com/o/oauth2/v2/auth"
URL_TOKEN = "https://oauth2.googleapis.com/token"
URL_SHEETS = "https://sheets.googleapis.com/v4/spreadsheets"
ESCOPOS = "openid email https://www.googleapis.com/auth/spreadsheets.readonly"


class GoogleIndisponivel(Exception):
    """Integração desligada, não conectada ou recusada pelo Google. A mensagem
    é segura para mostrar ao usuário."""


def _http() -> httpx.Client:
    return httpx.Client(timeout=30)


def is_configured() -> bool:
    return bool(settings.google_client_id and settings.google_client_secret)


def _exigir_configurado() -> None:
    if not is_configured():
        raise GoogleIndisponivel(
            "Integração com o Google não configurada (defina GOOGLE_CLIENT_ID e GOOGLE_CLIENT_SECRET)"
        )


def url_autorizacao(state: str) -> str:
    _exigir_configurado()
    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": ESCOPOS,
        # offline + consent: sem isso o Google só devolve refresh token na primeira vez
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    }
    return f"{URL_AUTORIZACAO}?{urlencode(params)}"


def _email_do_id_token(id_token: str | None) -> str | None:
    """Lê o e-mail do id_token sem validar a assinatura: ele veio direto do
    endpoint de token do Google por TLS e é usado só para exibição."""

    if not id_token:
        return None
    try:
        corpo = id_token.split(".")[1]
        corpo += "=" * (-len(corpo) % 4)
        return json.loads(base64.urlsafe_b64decode(corpo)).get("email")
    except (IndexError, ValueError):
        return None


def _pedir_token(dados: dict) -> dict:
    _exigir_configurado()
    dados = {"client_id": settings.google_client_id, "client_secret": settings.google_client_secret, **dados}
    try:
        with _http() as client:
            resposta = client.post(URL_TOKEN, data=dados)
    except httpx.HTTPError as exc:
        logger.warning("Falha de rede ao falar com o Google: %s", exc.__class__.__name__)
        raise GoogleIndisponivel("Não foi possível falar com o Google") from exc
    corpo = resposta.json() if resposta.content else {}
    if resposta.status_code >= 400:
        logger.warning("Google recusou o token: %s", corpo.get("error"))
        raise GoogleIndisponivel(f"O Google recusou a autorização ({corpo.get('error', resposta.status_code)})")
    return corpo


def conectar(db: Session, code: str, user_id: str | None) -> str | None:
    """Troca o código do consentimento pelos tokens e guarda o refresh token
    cifrado. Devolve o e-mail da conta conectada."""

    corpo = _pedir_token(
        {"grant_type": "authorization_code", "code": code, "redirect_uri": settings.google_redirect_uri}
    )
    refresh = corpo.get("refresh_token")
    if not refresh:
        raise GoogleIndisponivel(
            "O Google não devolveu o token de renovação; remova o acesso do app na conta Google e conecte de novo"
        )
    email = _email_do_id_token(corpo.get("id_token"))
    integracao = db.query(models.IntegracaoGoogle).first() or models.IntegracaoGoogle()
    integracao.email = email
    integracao.refresh_token_cifrado = crypto.cifrar(refresh)
    integracao.connected_by = user_id
    db.add(integracao)
    db.commit()
    _access_token_cache.clear()
    return email


def desconectar(db: Session) -> None:
    db.query(models.IntegracaoGoogle).delete()
    db.commit()
    _access_token_cache.clear()


def conta_conectada(db: Session) -> models.IntegracaoGoogle | None:
    return db.query(models.IntegracaoGoogle).first()


_access_token_cache: dict = {}


def _access_token(db: Session) -> str:
    agora = time.time()
    if _access_token_cache.get("expira", 0) > agora + 30:
        return _access_token_cache["token"]

    integracao = conta_conectada(db)
    if not integracao:
        raise GoogleIndisponivel("Conta Google não conectada: conecte em Configurações")
    refresh = crypto.decifrar(integracao.refresh_token_cifrado)
    if not refresh:
        raise GoogleIndisponivel("Não foi possível abrir o acesso guardado do Google: conecte a conta de novo")

    corpo = _pedir_token({"grant_type": "refresh_token", "refresh_token": refresh})
    _access_token_cache.update(token=corpo["access_token"], expira=agora + int(corpo.get("expires_in", 3600)))
    return corpo["access_token"]


def _get_sheets(db: Session, caminho: str, params: dict | None = None) -> dict:
    headers = {"Authorization": f"Bearer {_access_token(db)}"}
    try:
        with _http() as client:
            resposta = client.get(f"{URL_SHEETS}/{caminho}", params=params, headers=headers)
    except httpx.HTTPError as exc:
        logger.warning("Falha de rede ao falar com o Google Sheets: %s", exc.__class__.__name__)
        raise GoogleIndisponivel("Não foi possível falar com o Google Sheets") from exc
    if resposta.status_code in (401, 403, 404):
        raise GoogleIndisponivel(
            "O Google Sheets negou o acesso à planilha: confira se a conta conectada tem permissão de leitura nela"
        )
    if resposta.status_code >= 400:
        raise GoogleIndisponivel(f"O Google Sheets respondeu com erro ({resposta.status_code})")
    return resposta.json()


def ler_aba(db: Session, planilha_id: str, gid: int) -> list[list[str]]:
    """Todas as linhas (como texto, do jeito que aparecem na planilha) da aba
    com o `gid` da URL (`...#gid=113434922`)."""

    meta = _get_sheets(db, planilha_id, {"fields": "sheets.properties(sheetId,title)"})
    titulo = next(
        (s["properties"]["title"] for s in meta.get("sheets", []) if s["properties"]["sheetId"] == gid), None
    )
    if titulo is None:
        raise GoogleIndisponivel(f"A planilha não tem uma aba com gid {gid}")
    # aspas simples protegem títulos com espaço/acento; a própria aspa é dobrada
    intervalo = quote("'" + titulo.replace("'", "''") + "'", safe="")
    dados = _get_sheets(db, f"{planilha_id}/values/{intervalo}", {"majorDimension": "ROWS"})
    return dados.get("values", [])
