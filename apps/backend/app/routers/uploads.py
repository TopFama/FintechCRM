from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session, selectinload

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user
from ..utils.phone import is_valid_phone, normalize_phone
from ..utils.spreadsheet import parse_uploaded_spreadsheet

router = APIRouter(prefix="/faixas", tags=["uploads"])


@router.post("/{faixa_id}/uploads", response_model=schemas.UploadResult)
async def upload_planilha(
    faixa_id: str,
    file: UploadFile,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
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

    content = await file.read()
    try:
        rows = parse_uploaded_spreadsheet(file.filename or "planilha.csv", content)
    except Exception as exc:  # noqa: BLE001 - erro de parsing vira 400 explícito
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Não foi possível ler a planilha: {exc}") from exc

    variable_by_id = {v.id: v for v in faixa.template.variables}
    mapping = [
        (variable_by_id[m.template_variable_id].internal_name, m.column_name)
        for m in faixa.variable_mappings
    ]

    accepted = 0
    rejected = 0
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
        nome = (row.get("nome") or "").strip()
        celular_original = (row.get("celular") or "").strip()

        if not nome:
            rejected += 1
            reasons.append(f"Linha {i}: sem nome")
            continue
        if not is_valid_phone(celular_original):
            rejected += 1
            reasons.append(f"Linha {i}: telefone inválido ({celular_original})")
            continue

        celular = normalize_phone(celular_original)
        if celular in existing_phones:
            rejected += 1
            reasons.append(f"Linha {i}: cliente já está na fila desta faixa")
            continue

        missing = [col for internal_name, col in mapping if not (row.get(col) or "").strip()]
        if missing:
            rejected += 1
            reasons.append(f"Linha {i}: faltando coluna(s) {', '.join(missing)}")
            continue

        variables_json = {internal_name: row.get(col, "") for internal_name, col in mapping}
        db.add(
            models.QueueItem(
                faixa_id=faixa_id,
                nome=nome,
                celular=celular,
                celular_original=celular_original,
                variables_json=variables_json,
                status=models.QueueStatus.pending,
            )
        )
        existing_phones.add(celular)
        accepted += 1

    db.add(
        models.UploadLog(
            faixa_id=faixa_id,
            filename=file.filename or "planilha.csv",
            uploaded_by=user.id,
            row_count=len(rows),
            accepted_count=accepted,
            rejected_count=rejected,
        )
    )
    db.commit()

    return schemas.UploadResult(
        filename=file.filename or "planilha.csv",
        row_count=len(rows),
        accepted_count=accepted,
        rejected_count=rejected,
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
