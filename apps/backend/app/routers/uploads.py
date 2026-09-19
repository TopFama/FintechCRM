from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy.orm import Session, selectinload

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user
from ..utils.document import validate_client_code
from ..utils.phone import is_valid_phone, normalize_phone
from ..utils.spreadsheet import parse_uploaded_spreadsheet, read_spreadsheet_headers

router = APIRouter(prefix="/faixas", tags=["uploads"])


def _load_faixa(db: Session, faixa_id: str) -> models.Faixa:
    faixa = (
        db.query(models.Faixa)
        .options(
            selectinload(models.Faixa.variable_mappings),
            selectinload(models.Faixa.template).selectinload(models.Template.variables),
        )
        .filter(models.Faixa.id == faixa_id)
        .first()
    )
    if not faixa:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faixa não encontrada")
    return faixa


@router.post("/{faixa_id}/uploads/columns", response_model=schemas.UploadColumnsOut)
async def read_upload_columns(
    faixa_id: str,
    file: UploadFile,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Lê só o cabeçalho da planilha enviada, para o usuário escolher em uma
    lista suspensa qual coluna alimenta cada variável/campo."""

    _load_faixa(db, faixa_id)
    content = await file.read()
    try:
        columns = read_spreadsheet_headers(file.filename or "planilha.xlsx", content)
    except Exception as exc:  # noqa: BLE001 - erro de parsing vira 400 explícito
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Não foi possível ler a planilha: {exc}") from exc
    if not columns:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A planilha está vazia ou sem cabeçalho")
    return schemas.UploadColumnsOut(columns=columns)


@router.post("/{faixa_id}/uploads", response_model=schemas.UploadResult)
async def upload_planilha(
    faixa_id: str,
    file: UploadFile,
    mapping: str = Form(..., description="JSON de UploadFieldMapping"),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    faixa = _load_faixa(db, faixa_id)

    try:
        field_mapping = schemas.UploadFieldMapping.model_validate_json(mapping)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Mapeamento inválido: {exc}") from exc

    variable_by_id = {v.id: v for v in faixa.template.variables}
    missing_vars = set(variable_by_id) - set(field_mapping.variables)
    if missing_vars:
        names = ", ".join(variable_by_id[v].internal_name for v in missing_vars)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"Faltando coluna mapeada para a(s) variável(is): {names}"
        )

    content = await file.read()
    try:
        rows = parse_uploaded_spreadsheet(file.filename or "planilha.xlsx", content)
    except Exception as exc:  # noqa: BLE001 - erro de parsing vira 400 explícito
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Não foi possível ler a planilha: {exc}") from exc

    accepted = 0
    rejected = 0
    invalid_phone_count = 0
    reasons: list[str] = []

    existing_phones = {
        row.celular
        for row in db.query(models.QueueItem.celular).filter(
            models.QueueItem.faixa_id == faixa_id,
            models.QueueItem.status.in_(
                [models.QueueStatus.pending, models.QueueStatus.reserved, models.QueueStatus.sent]
            ),
        )
    }

    for i, row in enumerate(rows, start=2):  # linha 1 = cabeçalho
        codigo_raw = (row.get(field_mapping.codigo_cliente) or "").strip()
        celular_original = (row.get(field_mapping.celular) or "").strip()
        nome = (row.get(field_mapping.nome) or "").strip() if field_mapping.nome else ""
        valor = (row.get(field_mapping.valor) or "").strip() if field_mapping.valor else None

        code_result = validate_client_code(codigo_raw)
        if not code_result:
            rejected += 1
            reasons.append(
                f"Linha {i}: código do cliente inválido ({codigo_raw or 'vazio'}) — use SETA de 8 dígitos ou CPF"
            )
            continue
        codigo_cliente, codigo_tipo = code_result

        if not is_valid_phone(celular_original):
            db.add(
                models.InvalidPhoneRecord(
                    faixa_id=faixa_id,
                    codigo_cliente=codigo_cliente,
                    celular_original=celular_original,
                    celular_normalizado=normalize_phone(celular_original) or None,
                    motivo="Telefone fora do padrão 55DD9XXXXXXXX (dígitos insuficientes ou inválidos)",
                )
            )
            invalid_phone_count += 1
            rejected += 1
            reasons.append(f"Linha {i}: telefone inválido ({celular_original}) — enviado ao relatório de telefones inválidos")
            continue

        celular = normalize_phone(celular_original)
        if celular in existing_phones:
            rejected += 1
            reasons.append(f"Linha {i}: cliente já está na fila desta faixa")
            continue

        missing_var_cols = [
            v.internal_name
            for vid, v in variable_by_id.items()
            if not (row.get(field_mapping.variables[vid]) or "").strip()
        ]
        if missing_var_cols:
            rejected += 1
            reasons.append(f"Linha {i}: faltando coluna(s) {', '.join(missing_var_cols)}")
            continue

        variables_json = {v.internal_name: row.get(field_mapping.variables[vid], "") for vid, v in variable_by_id.items()}
        db.add(
            models.QueueItem(
                faixa_id=faixa_id,
                codigo_cliente=codigo_cliente,
                codigo_tipo=codigo_tipo,
                nome=nome,
                valor=valor or None,
                celular=celular,
                celular_original=celular_original,
                variables_json=variables_json,
                status=models.QueueStatus.pending,
            )
        )
        existing_phones.add(celular)
        accepted += 1

    faixa.upload_field_mapping = field_mapping.model_dump()

    db.add(
        models.UploadLog(
            faixa_id=faixa_id,
            filename=file.filename or "planilha.xlsx",
            uploaded_by=user.id,
            row_count=len(rows),
            accepted_count=accepted,
            rejected_count=rejected,
            invalid_phone_count=invalid_phone_count,
        )
    )
    db.commit()

    return schemas.UploadResult(
        filename=file.filename or "planilha.xlsx",
        row_count=len(rows),
        accepted_count=accepted,
        rejected_count=rejected,
        invalid_phone_count=invalid_phone_count,
        rejected_reasons=reasons[:50],
    )


@router.get("/{faixa_id}/queue", response_model=list[schemas.QueueItemOut])
def list_queue(
    faixa_id: str, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    return (
        db.query(models.QueueItem)
        .filter(models.QueueItem.faixa_id == faixa_id)
        .order_by(models.QueueItem.created_at.desc())
        .limit(500)
        .all()
    )
