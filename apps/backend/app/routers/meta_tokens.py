import httpx
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


def _waba_valida(valor: str | None) -> str:
    waba = (valor or "").strip()
    if not waba.isdigit():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Informe o WABA ID (só números) junto com o token")
    return waba


def _erro_meta(exc: MetaAPIError) -> str:
    detalhe = exc.payload.get("error", {}).get("message", str(exc))
    return f"A Meta recusou ({exc.status_code}): {detalhe}"


async def _numeros_da_waba(token: str, waba_id: str) -> list[dict]:
    """Números da WABA segundo a Meta; também serve para validar o par token + WABA."""

    try:
        return await MetaClient(access_token=token).list_phone_numbers(waba_id)
    except MetaAPIError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, _erro_meta(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, "Não foi possível falar com a Meta") from exc


@router.post("", response_model=schemas.MetaTokenOut, status_code=status.HTTP_201_CREATED)
async def create_meta_token(
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
    waba_id = _waba_valida(payload.waba_id)

    # Mesmo token pode dar acesso a mais de uma WABA (ex.: token de system user
    # com múltiplas WABAs) — só bloqueia duplicidade quando é a mesma WABA.
    existing_tokens = db.query(models.MetaToken).filter(models.MetaToken.waba_id == waba_id).all()
    for existing in existing_tokens:
        decrypted = crypto.decifrar(existing.token_cifrado)
        if decrypted == token_raw:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Já existe um token cadastrado com este mesmo valor para esta WABA",
            )

    # Só grava se a Meta aceitar o token para essa WABA
    await _numeros_da_waba(token_raw, waba_id)

    novo_token = models.MetaToken(
        nome=nome,
        token_cifrado=crypto.cifrar(token_raw),
        ultimos4=token_raw[-4:] if len(token_raw) >= 4 else token_raw,
        waba_id=waba_id,
        ativo=True,
    )
    db.add(novo_token)
    db.commit()
    db.refresh(novo_token)
    return novo_token


def _token_ou_404(db: Session, token_id: str) -> models.MetaToken:
    token = db.get(models.MetaToken, token_id)
    if not token:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Token não encontrado")
    return token


def _decifrado(token: models.MetaToken) -> str:
    valor = crypto.decifrar(token.token_cifrado)
    if not valor:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Não foi possível decifrar o token com a chave atual")
    return valor


@router.get("/{token_id}/numeros-meta", response_model=list[schemas.NumeroMetaOut])
async def listar_numeros_meta(
    token_id: str,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Números que a Meta tem para a WABA do token, marcando os já cadastrados."""

    token = _token_ou_404(db, token_id)
    if not token.waba_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Este token não tem WABA ID: edite-o e informe a WABA")
    da_meta = await _numeros_da_waba(_decifrado(token), token.waba_id)
    cadastrados = {
        n.phone_number_id: n
        for n in db.query(models.WhatsappNumber).filter(
            models.WhatsappNumber.phone_number_id.in_([str(m.get("id")) for m in da_meta])
        )
    }
    return [
        schemas.NumeroMetaOut(
            phone_number_id=str(m.get("id")),
            display_phone_number=m.get("display_phone_number", ""),
            verified_name=m.get("verified_name"),
            quality_rating=m.get("quality_rating"),
            status=m.get("status"),
            cadastrado=str(m.get("id")) in cadastrados,
            vinculado_a_este_token=cadastrados.get(str(m.get("id"))) is not None
            and cadastrados[str(m.get("id"))].meta_token_id == token.id,
        )
        for m in da_meta
    ]


@router.post("/{token_id}/importar-numeros", response_model=schemas.ImportarNumerosOut)
async def importar_numeros(
    token_id: str,
    payload: schemas.ImportarNumerosIn,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Cadastra os números escolhidos da WABA (card Números de WhatsApp), já com este token."""

    token = _token_ou_404(db, token_id)
    if not token.waba_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Este token não tem WABA ID: edite-o e informe a WABA")
    if not token.ativo:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ative o token antes de importar números")
    da_meta = {str(m.get("id")): m for m in await _numeros_da_waba(_decifrado(token), token.waba_id)}
    desconhecidos = [pid for pid in payload.phone_number_ids if pid not in da_meta]
    if desconhecidos:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Número(s) que não pertencem à WABA {token.waba_id}: {', '.join(desconhecidos)}"
        )

    importados = vinculados = ignorados = 0
    for pid in dict.fromkeys(payload.phone_number_ids):
        existente = db.query(models.WhatsappNumber).filter(models.WhatsappNumber.phone_number_id == pid).first()
        if existente:
            if existente.meta_token_id is None:
                existente.meta_token_id = token.id
                vinculados += 1
            elif existente.meta_token_id != token.id:
                ignorados += 1
            continue
        m = da_meta[pid]
        db.add(
            models.WhatsappNumber(
                waba_id=token.waba_id,
                phone_number_id=pid,
                display_phone_number=m.get("display_phone_number", ""),
                label=m.get("verified_name") or "",
                meta_token_id=token.id,
            )
        )
        importados += 1
    db.commit()
    return schemas.ImportarNumerosOut(importados=importados, vinculados=vinculados, ignorados=ignorados)


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

    if "waba_id" in payload.model_fields_set:
        token.waba_id = _waba_valida(payload.waba_id)

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

    # Números vinculados a este token são excluídos junto (CASCADE em
    # WhatsappNumber.meta_token_id — ver models.py).
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
        detalhe = f"Token válido (conectado como '{nome}')"
        if token.waba_id:
            numeros = await client.list_phone_numbers(token.waba_id)
            detalhe += f"; {len(numeros)} número(s) na WABA {token.waba_id}"
        return schemas.MetaTokenTestResult(ok=True, detalhe=detalhe)
    except MetaAPIError as exc:
        detalhe_erro = exc.payload.get("error", {}).get("message", str(exc))
        return schemas.MetaTokenTestResult(
            ok=False, detalhe=f"Erro retornado pela Meta ({exc.status_code}): {detalhe_erro}"
        )
    except Exception as exc:
        return schemas.MetaTokenTestResult(
            ok=False, detalhe=f"Erro de conexão com a Meta: {str(exc)}"
        )
