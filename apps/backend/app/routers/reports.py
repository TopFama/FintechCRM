import csv
import io

from fastapi import APIRouter, Depends, Response
from sqlalchemy.orm import Session, selectinload

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/relatorios", tags=["relatorios"])


def _invalid_phones_query(db: Session, faixa_id: str | None):
    query = db.query(models.InvalidPhoneRecord).order_by(models.InvalidPhoneRecord.created_at.desc())
    if faixa_id:
        query = query.filter(models.InvalidPhoneRecord.faixa_id == faixa_id)
    return query


@router.get("/telefones-invalidos", response_model=list[schemas.InvalidPhoneOut])
def list_invalid_phones(
    faixa_id: str | None = None,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    return _invalid_phones_query(db, faixa_id).limit(1000).all()


@router.get("/telefones-invalidos/export")
def export_invalid_phones(
    faixa_id: str | None = None,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    records = (
        _invalid_phones_query(db, faixa_id)
        .options(selectinload(models.InvalidPhoneRecord.faixa))
        .all()
    )
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["codigo_cliente", "faixa", "celular_original", "celular_normalizado", "motivo", "data_hora"])
    for r in records:
        writer.writerow(
            [
                r.codigo_cliente,
                r.faixa.name if r.faixa else "",
                r.celular_original,
                r.celular_normalizado or "",
                r.motivo,
                r.created_at.isoformat(),
            ]
        )
    return Response(
        content=buffer.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="telefones_invalidos.csv"'},
    )


def _dispatch_report_rows(db: Session, faixa_id: str | None) -> list[models.QueueItem]:
    query = (
        db.query(models.QueueItem)
        .options(
            selectinload(models.QueueItem.faixa),
            selectinload(models.QueueItem.whatsapp_number),
        )
        .filter(models.QueueItem.status == models.QueueStatus.sent)
        .order_by(models.QueueItem.sent_at.desc())
    )
    if faixa_id:
        query = query.filter(models.QueueItem.faixa_id == faixa_id)
    return query.limit(1000).all()


def _to_report_item(item: models.QueueItem) -> schemas.DispatchReportItemOut:
    return schemas.DispatchReportItemOut(
        codigo_cliente=item.codigo_cliente,
        faixa=item.faixa.name if item.faixa else "",
        nome=item.nome,
        valor=item.valor,
        telefone=item.whatsapp_number.display_phone_number if item.whatsapp_number else "",
        enviado_em=item.sent_at,
    )


@router.get("/envios", response_model=list[schemas.DispatchReportItemOut])
def list_dispatch_report(
    faixa_id: str | None = None,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    return [_to_report_item(item) for item in _dispatch_report_rows(db, faixa_id) if item.sent_at]


@router.get("/envios/export")
def export_dispatch_report(
    faixa_id: str | None = None,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    rows = _dispatch_report_rows(db, faixa_id)
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["codigo_cliente", "faixa_de_atraso", "nome", "valor_cobrado", "telefone_que_cobrou", "data_hora"])
    for item in rows:
        if not item.sent_at:
            continue
        writer.writerow(
            [
                item.codigo_cliente,
                item.faixa.name if item.faixa else "",
                item.nome,
                item.valor or "",
                item.whatsapp_number.display_phone_number if item.whatsapp_number else "",
                item.sent_at.isoformat(),
            ]
        )
    return Response(
        content=buffer.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="relatorio_envios.csv"'},
    )
