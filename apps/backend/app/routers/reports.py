import io

from fastapi import APIRouter, Depends, Response
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session, selectinload

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/relatorios", tags=["relatorios"])

_XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")
_DATETIME_FORMAT = "DD/MM/YYYY HH:MM:SS"


def _formula_safe(value: str) -> str:
    """Neutraliza injeção de fórmula (CWE-1236): nome/valor/telefone vêm da
    planilha importada por qualquer usuário e, sem isso, um valor como
    "=cmd|'/c calc'!A0" seria executado ao abrir o relatório no Excel/
    LibreOffice — o openpyxl trata string começando com "=" como fórmula
    igual ao próprio Excel."""

    if value and value[0] in _FORMULA_PREFIXES:
        return "'" + value
    return value


def _build_xlsx(headers: list[str], rows: list[list]) -> bytes:
    """Gera um .xlsx com cabeçalho destacado, painel congelado, autofiltro e
    largura de coluna ajustada — usado por todos os relatórios exportáveis."""

    wb = Workbook()
    ws = wb.active
    ws.append(headers)
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="003090")
    for row in rows:
        ws.append(row)
        for cell in ws[ws.max_row]:
            if hasattr(cell.value, "strftime"):
                cell.number_format = _DATETIME_FORMAT
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for i, header in enumerate(headers, start=1):
        widths = [len(header)] + [len(str(row[i - 1])) for row in rows if row[i - 1] is not None]
        ws.column_dimensions[get_column_letter(i)].width = min(max(widths) + 4, 40)
    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


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
    headers = ["Código do cliente", "Faixa", "Telefone informado", "Telefone normalizado", "Motivo", "Data/hora"]
    rows = [
        [
            r.codigo_cliente,
            r.faixa.name if r.faixa else "",
            _formula_safe(r.celular_original),
            r.celular_normalizado or "",
            r.motivo,
            r.created_at,
        ]
        for r in records
    ]
    return Response(
        content=_build_xlsx(headers, rows),
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="telefones_invalidos.xlsx"'},
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
    rows_data = _dispatch_report_rows(db, faixa_id)
    headers = ["Código do cliente", "Faixa de atraso", "Nome", "Valor cobrado", "Telefone que cobrou", "Data/hora"]
    rows = [
        [
            item.codigo_cliente,
            item.faixa.name if item.faixa else "",
            _formula_safe(item.nome),
            _formula_safe(item.valor or ""),
            item.whatsapp_number.display_phone_number if item.whatsapp_number else "",
            item.sent_at,
        ]
        for item in rows_data
        if item.sent_at
    ]
    return Response(
        content=_build_xlsx(headers, rows),
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="relatorio_envios.xlsx"'},
    )
