from fastapi import APIRouter, Depends

from .. import models, schemas, seta_client
from ..deps import get_current_user

router = APIRouter(prefix="/seta", tags=["seta"])


@router.get("/status", response_model=schemas.SetaStatusOut)
def seta_status(_user: models.User = Depends(get_current_user)):
    """Sempre responde 200: falha de conexão vira `conectado=false` + `erro`,
    para a tela poder mostrar o estado em vez de tratar como erro de API."""

    if not seta_client.is_configured():
        return schemas.SetaStatusOut(
            configurado=False, conectado=False, erro="Integração com o SETA não configurada"
        )
    try:
        info = seta_client.check_connection()
    except seta_client.SetaIndisponivel as exc:
        return schemas.SetaStatusOut(configurado=True, conectado=False, erro=str(exc))
    return schemas.SetaStatusOut(configurado=True, conectado=True, **info)
