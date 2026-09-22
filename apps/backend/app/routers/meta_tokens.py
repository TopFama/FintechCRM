from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, selectinload

from .. import crypto, models, schemas
from ..database import get_db
from ..deps import get_current_user
from ..meta_client import MetaAPIError, MetaClient

router = APIRouter(prefix="/meta-tokens", tags=["meta-tokens"])


@router.get("", response_model=list[schemas.MetaTokenOut])
def list_meta_tokens(
    db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    return (
        db.query(models.MetaToken)
        .options(selectinload(models.MetaToken.numeros))
        .order_by(models.MetaToken.created_at.desc())
        .all()
    )


@router.post("", response_model=schemas.MetaTokenOut, status_code=status.HTTP_201_CREATED)
def create_meta_token(
    payload: schemas.MetaTokenCreate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    nome = payload.nome.strip()
    token_raw = payload.token.strip()
    if not nome or not token_raw:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Nome e token não podem ser vazios"
        )

    # Verifica se já existe algum token cadastrado com o mesmo valor decifrado
    existing_tokens = db.query(models.MetaToken).all()
    for existing in existing_tokens:
        decrypted = crypto.decifrar(existing.token_cifrado)
        if decrypted == token_raw:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Já existe um token cadastrado com este mesmo valor",
            )

    token_cifrado = crypto.cifrar(token_raw)
    ultimos4 = token_raw[-4:] if len(token_raw) >= 4 else token_raw

    novo_token = models.MetaToken(
        nome=nome,
        token_cifrado=token_cifrado,
        ultimos4=ultimos4,
        ativo=True,
    )
    db.add(novo_token)
    db.commit()
    db.refresh(novo_token)
    return novo_token


@router.patch("/{token_id}", response_model=schemas.MetaTokenOut)
def update_meta_token(
    token_id: str,
    payload: schemas.MetaTokenUpdate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    token = (
        db.query(models.MetaToken)
        .options(selectinload(models.MetaToken.numeros))
        .filter(models.MetaToken.id == token_id)
        .first()
    )
    if not token:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token não encontrado")

    if "nome" in payload.model_fields_set:
        if payload.nome is None or not payload.nome.strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nome não pode ser vazio")
        token.nome = payload.nome.strip()

    if "ativo" in payload.model_fields_set and payload.ativo is not None:
        token.ativo = payload.ativo

    db.commit()
    db.refresh(token)
    return token


@router.delete("/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_meta_token(
    token_id: str,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    token = db.get(models.MetaToken, token_id)
    if not token:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token não encontrado")

    numeros_vinculados = (
        db.query(models.WhatsappNumber)
        .filter(models.WhatsappNumber.meta_token_id == token_id)
        .count()
    )
    if numeros_vinculados > 0:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Token não pode ser excluído: usado por {numeros_vinculados} número(s)",
        )

    db.delete(token)
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{token_id}/testar", response_model=schemas.MetaTokenTestResult)
async def testar_meta_token(
    token_id: str,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    token = db.get(models.MetaToken, token_id)
    if not token:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token não encontrado")

    decrypted = crypto.decifrar(token.token_cifrado)
    if not decrypted:
        return schemas.MetaTokenTestResult(
            ok=False, detalhe="Não foi possível decifrar o token com a chave atual"
        )

    client = MetaClient(access_token=decrypted)
    try:
        dados = await client.test_token()
        nome = dados.get("name") or "Sem nome"
        return schemas.MetaTokenTestResult(
            ok=True, detalhe=f"Token válido (conectado como '{nome}')"
        )
    except MetaAPIError as exc:
        detalhe_erro = exc.payload.get("error", {}).get("message", str(exc))
        return schemas.MetaTokenTestResult(
            ok=False, detalhe=f"Erro retornado pela Meta ({exc.status_code}): {detalhe_erro}"
        )
    except Exception as exc:
        return schemas.MetaTokenTestResult(
            ok=False, detalhe=f"Erro de conexão com a Meta: {str(exc)}"
        )
