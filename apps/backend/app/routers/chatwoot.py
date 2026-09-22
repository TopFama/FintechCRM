from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import chatwoot_client, crypto, models, schemas
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/chatwoot", tags=["chatwoot"])


@router.get("/status", response_model=schemas.ChatwootStatusOut)
def status_chatwoot(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    config = db.query(models.ConfiguracaoChatwoot).first()
    if not config:
        return schemas.ChatwootStatusOut(configurado=False)
    return schemas.ChatwootStatusOut(configurado=True, base_url=config.base_url, account_id=config.account_id)


@router.put("/config", response_model=schemas.ChatwootStatusOut)
def salvar_config(
    payload: schemas.ChatwootConfigIn,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    config = db.query(models.ConfiguracaoChatwoot).first()
    if not config:
        if not payload.api_access_token:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Informe o token de acesso da API")
        config = models.ConfiguracaoChatwoot(
            base_url=payload.base_url,
            account_id=payload.account_id,
            api_access_token_cifrado=crypto.cifrar(payload.api_access_token),
        )
        db.add(config)
    else:
        config.base_url = payload.base_url
        config.account_id = payload.account_id
        if payload.api_access_token:
            config.api_access_token_cifrado = crypto.cifrar(payload.api_access_token)
    db.commit()
    return schemas.ChatwootStatusOut(configurado=True, base_url=config.base_url, account_id=config.account_id)


@router.post("/testar", response_model=schemas.ChatwootTestResult)
async def testar_conexao(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    try:
        client = chatwoot_client.cliente_configurado(db)
    except chatwoot_client.ChatwootConfigError as exc:
        return schemas.ChatwootTestResult(ok=False, detalhe=str(exc))

    try:
        await client.test_connection()
        return schemas.ChatwootTestResult(ok=True, detalhe="Conexão com o Chatwoot bem-sucedida")
    except chatwoot_client.ChatwootAPIError as exc:
        return schemas.ChatwootTestResult(ok=False, detalhe=f"Erro retornado pelo Chatwoot ({exc.status_code})")
    except Exception as exc:  # noqa: BLE001 - qualquer falha de rede/config vira mensagem pro usuário
        return schemas.ChatwootTestResult(ok=False, detalhe=f"Erro de conexão com o Chatwoot: {exc}")
