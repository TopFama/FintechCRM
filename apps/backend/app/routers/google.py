from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import google_client, lojas, models, schemas
from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..security import create_oauth_state, decode_oauth_state

router = APIRouter(prefix="/google", tags=["google"])


@router.get("/status", response_model=schemas.GoogleStatusOut)
def google_status(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    conta = google_client.conta_conectada(db)
    return schemas.GoogleStatusOut(
        configurado=google_client.is_configured(),
        conectado=conta is not None,
        email=conta.email if conta else None,
        redirect_uri=settings.google_redirect_uri,
    )


@router.post("/oauth/iniciar", response_model=schemas.GoogleAutorizacaoOut)
def iniciar_oauth(user: models.User = Depends(get_current_user)):
    """Devolve a URL de consentimento do Google; a tela abre essa URL."""

    try:
        return schemas.GoogleAutorizacaoOut(url=google_client.url_autorizacao(create_oauth_state(user.email)))
    except google_client.GoogleIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("/oauth/callback", include_in_schema=False)
def callback_oauth(
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    db: Session = Depends(get_db),
):
    """Para onde o Google devolve o navegador. Não tem login (é um redirect do
    navegador): quem garante que o retorno é legítimo é o `state` assinado."""

    def voltar(**params) -> RedirectResponse:
        return RedirectResponse(f"{settings.google_frontend_url}/configuracoes?{urlencode(params)}")

    if error:
        return voltar(google="erro", motivo="Consentimento negado no Google")
    email = decode_oauth_state(state or "")
    if not email or not code:
        return voltar(google="erro", motivo="Retorno do Google inválido ou expirado; tente conectar de novo")
    usuario = db.query(models.User).filter(models.User.email == email).first()
    try:
        google_client.conectar(db, code, usuario.id if usuario else None)
    except google_client.GoogleIndisponivel as exc:
        return voltar(google="erro", motivo=str(exc))
    lojas.limpar_cache()
    return voltar(google="ok")


@router.delete("/oauth", status_code=status.HTTP_204_NO_CONTENT)
def desconectar(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    google_client.desconectar(db)
    lojas.limpar_cache()
