import io
from datetime import date, datetime
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import case
from sqlalchemy.orm import Session, selectinload

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user
from ..regras_db import carregar_regras
from ..services import efetividade_service
from ..timezone import BUSINESS_TZ

api = APIRouter()

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


def _build_efetividade_xlsx(relatorio: dict) -> bytes:
    """Gera o .xlsx de efetividade com duas abas ('Por faixa' e 'Por loja'),
    cabeçalho azul, congelamento de painel, autofiltro, linha Total em negrito,
    formatação de moeda/porcentagem e formatação condicional no Cluster INAD."""

    wb = Workbook()

    # Aba 1: Por faixa
    ws_faixa = wb.active
    ws_faixa.title = "Por faixa"

    headers_faixa = [
        "Faixa de atraso",
        "Qtd. de envios",
        "Clientes cobrados",
        "Valor cobrado",
        "Clientes que pagaram",
        "Recebimento",
        "% Conv.",
        "Recuperação (%)",
    ]
    ws_faixa.append(headers_faixa)

    for linha in relatorio["por_faixa"]:
        ws_faixa.append(
            [
                linha["faixa"],
                linha["qtd_envios"],
                linha["clientes_cobrados"],
                float(linha["valor_cobrado"]),
                linha["clientes_pagaram"],
                float(linha["valor_pago"]),
                float(linha["conversao_clientes"]),
                float(linha["recuperacao_valor"]),
            ]
        )

    tot = relatorio["total"]
    ws_faixa.append(
        [
            "Total",
            tot["qtd_envios"],
            tot["clientes_cobrados"],
            float(tot["valor_cobrado"]),
            tot["clientes_pagaram"],
            float(tot["valor_pago"]),
            float(tot["conversao_clientes"]),
            float(tot["recuperacao_valor"]),
        ]
    )

    for cell in ws_faixa[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="003090")

    for row_idx in range(2, ws_faixa.max_row + 1):
        is_total = row_idx == ws_faixa.max_row
        for col_idx, cell in enumerate(ws_faixa[row_idx], start=1):
            if is_total:
                cell.font = Font(bold=True)
            if col_idx in (4, 6):
                cell.number_format = '"R$" #,##0.00'
            elif col_idx in (7, 8):
                cell.number_format = "0.0%"

    ws_faixa.freeze_panes = "A2"
    ws_faixa.auto_filter.ref = ws_faixa.dimensions

    for col_idx in range(1, len(headers_faixa) + 1):
        col_letter = get_column_letter(col_idx)
        max_len = len(headers_faixa[col_idx - 1])
        for row in ws_faixa.iter_rows(min_row=2, max_col=col_idx, min_col=col_idx):
            val = row[0].value
            if val is not None:
                max_len = max(max_len, len(str(val)))
        ws_faixa.column_dimensions[col_letter].width = min(max_len + 4, 40)

    # Aba 2: Por loja
    ws_loja = wb.create_sheet(title="Por loja")
    headers_loja = [
        "Loja",
        "Regional",
        "Cluster INAD",
        "Qtd. de envios",
        "Clientes cobrados",
        "Valor cobrado",
        "Clientes que pagaram",
        "Recebimento",
        "% Conv.",
        "Recuperação (%)",
    ]
    ws_loja.append(headers_loja)

    for linha in relatorio["por_loja"]:
        ws_loja.append(
            [
                linha["loja"],
                linha.get("regional") or "",
                linha.get("cluster_inad") or "",
                linha["qtd_envios"],
                linha["clientes_cobrados"],
                float(linha["valor_cobrado"]),
                linha["clientes_pagaram"],
                float(linha["valor_pago"]),
                float(linha["conversao_clientes"]),
                float(linha["recuperacao_valor"]),
            ]
        )

    ws_loja.append(
        [
            "Total",
            "",
            "",
            tot["qtd_envios"],
            tot["clientes_cobrados"],
            float(tot["valor_cobrado"]),
            tot["clientes_pagaram"],
            float(tot["valor_pago"]),
            float(tot["conversao_clientes"]),
            float(tot["recuperacao_valor"]),
        ]
    )

    for cell in ws_loja[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="003090")

    for row_idx in range(2, ws_loja.max_row + 1):
        is_total = row_idx == ws_loja.max_row
        for col_idx, cell in enumerate(ws_loja[row_idx], start=1):
            if is_total:
                cell.font = Font(bold=True)
            if col_idx in (6, 8):
                cell.number_format = '"R$" #,##0.00'
            elif col_idx in (9, 10):
                cell.number_format = "0.0%"

    ws_loja.freeze_panes = "A2"
    ws_loja.auto_filter.ref = ws_loja.dimensions

    for col_idx in range(1, len(headers_loja) + 1):
        col_letter = get_column_letter(col_idx)
        max_len = len(headers_loja[col_idx - 1])
        for row in ws_loja.iter_rows(min_row=2, max_col=col_idx, min_col=col_idx):
            val = row[0].value
            if val is not None:
                max_len = max(max_len, len(str(val)))
        ws_loja.column_dimensions[col_letter].width = min(max_len + 4, 40)

    # Formatação condicional sobre o intervalo de dados da coluna Cluster INAD (coluna C)
    num_dados_loja = len(relatorio["por_loja"])
    cf_range = f"C2:C{num_dados_loja + 1}" if num_dados_loja > 0 else "C2:C2"

    red_fill = PatternFill(start_color="FFC7CE", end_color="FFC7CE", fill_type="solid")
    red_font = Font(color="9C0006")
    yellow_fill = PatternFill(start_color="FFEB9C", end_color="FFEB9C", fill_type="solid")
    yellow_font = Font(color="9C5700")
    green_fill = PatternFill(start_color="C6EFCE", end_color="C6EFCE", fill_type="solid")
    green_font = Font(color="006100")

    rule_alt = FormulaRule(
        formula=['NOT(ISERROR(SEARCH("ALT", C2)))'],
        fill=red_fill,
        font=red_font,
    )
    rule_med = FormulaRule(
        formula=['NOT(ISERROR(SEARCH("MED", C2)))'],
        fill=yellow_fill,
        font=yellow_font,
    )
    rule_baix = FormulaRule(
        formula=['NOT(ISERROR(SEARCH("BAIX", C2)))'],
        fill=green_fill,
        font=green_font,
    )

    ws_loja.conditional_formatting.add(cf_range, rule_alt)
    ws_loja.conditional_formatting.add(cf_range, rule_med)
    ws_loja.conditional_formatting.add(cf_range, rule_baix)

    buffer = io.BytesIO()
    wb.save(buffer)
    return buffer.getvalue()


InvalidPhoneSortColumn = Literal["codigo_cliente", "celular_original", "celular_normalizado", "motivo", "created_at"]

_INVALID_PHONE_SORT_COLUNAS = {
    "codigo_cliente": models.InvalidPhoneRecord.codigo_cliente,
    "celular_original": models.InvalidPhoneRecord.celular_original,
    "celular_normalizado": models.InvalidPhoneRecord.celular_normalizado,
    "motivo": models.InvalidPhoneRecord.motivo,
    "created_at": models.InvalidPhoneRecord.created_at,
}


def _invalid_phones_query(
    db: Session, faixa_id: str | None, sort_by: str | None = None, sort_dir: str = "asc"
):
    query = db.query(models.InvalidPhoneRecord)
    if faixa_id:
        query = query.filter(models.InvalidPhoneRecord.faixa_id == faixa_id)
    coluna = _INVALID_PHONE_SORT_COLUNAS.get(sort_by) if sort_by else None
    if coluna is not None:
        query = query.order_by(
            coluna.desc() if sort_dir == "desc" else coluna.asc(), models.InvalidPhoneRecord.id
        )
    else:
        query = query.order_by(models.InvalidPhoneRecord.created_at.desc())
    return query


def _hora_br(dt: datetime | None) -> datetime | None:
    """Timestamp UTC ingênuo do banco → horário de Brasília (ingênuo, pro Excel)."""
    if dt is None:
        return None
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(BUSINESS_TZ).replace(tzinfo=None)


@api.get("/telefones-invalidos", response_model=schemas.InvalidPhonePage)
def list_invalid_phones(
    faixa_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: InvalidPhoneSortColumn | None = Query(None),
    sort_dir: Literal["asc", "desc"] = Query("asc"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    query = _invalid_phones_query(db, faixa_id, sort_by, sort_dir)
    total = query.count()
    itens = query.offset(offset).limit(limit).all()
    return schemas.InvalidPhonePage(total=total, itens=itens)


@api.get("/telefones-invalidos/export")
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
            _hora_br(r.created_at),
        ]
        for r in records
    ]
    return Response(
        content=_build_xlsx(headers, rows),
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="telefones_invalidos.xlsx"'},
    )


DispatchSortColumn = Literal["codigo_cliente", "faixa", "nome", "valor", "telefone", "enviado_em"]


def _dispatch_report_query(
    db: Session, faixa_id: str | None, sort_by: str | None = None, sort_dir: str = "asc"
):
    query = (
        db.query(models.QueueItem)
        .options(
            selectinload(models.QueueItem.faixa),
            selectinload(models.QueueItem.whatsapp_number),
        )
        .filter(models.QueueItem.status == models.QueueStatus.sent, models.QueueItem.sent_at.isnot(None))
    )
    if faixa_id:
        query = query.filter(models.QueueItem.faixa_id == faixa_id)

    def _ordenado(coluna):
        return coluna.desc() if sort_dir == "desc" else coluna.asc()

    if sort_by == "faixa":
        # ordena pela progressão do atraso (mesma ordem de RegrasCobranca.faixas),
        # não alfabeticamente — mesmo critério usado em /leads
        nomes_faixa = carregar_regras(db).nomes_faixa
        expr = (
            case({nome: i for i, nome in enumerate(nomes_faixa)}, value=models.Faixa.name, else_=len(nomes_faixa))
            if nomes_faixa
            else models.Faixa.name
        )
        query = query.join(models.QueueItem.faixa).order_by(_ordenado(expr), models.QueueItem.id)
    elif sort_by == "telefone":
        query = query.outerjoin(models.QueueItem.whatsapp_number).order_by(
            _ordenado(models.WhatsappNumber.display_phone_number), models.QueueItem.id
        )
    elif sort_by in ("codigo_cliente", "nome", "valor"):
        query = query.order_by(_ordenado(getattr(models.QueueItem, sort_by)), models.QueueItem.id)
    elif sort_by == "enviado_em":
        query = query.order_by(_ordenado(models.QueueItem.sent_at), models.QueueItem.id)
    else:
        query = query.order_by(models.QueueItem.sent_at.desc())
    return query


def _to_report_item(item: models.QueueItem) -> schemas.DispatchReportItemOut:
    return schemas.DispatchReportItemOut(
        codigo_cliente=item.codigo_cliente,
        faixa=item.faixa.name if item.faixa else "",
        nome=item.nome,
        valor=item.valor,
        telefone=item.whatsapp_number.display_phone_number if item.whatsapp_number else "",
        enviado_em=item.sent_at,
    )


@api.get("/envios", response_model=schemas.DispatchReportPage)
def list_dispatch_report(
    faixa_id: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: DispatchSortColumn | None = Query(None),
    sort_dir: Literal["asc", "desc"] = Query("asc"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    query = _dispatch_report_query(db, faixa_id, sort_by, sort_dir)
    total = query.count()
    itens = [_to_report_item(item) for item in query.offset(offset).limit(limit).all()]
    return schemas.DispatchReportPage(total=total, itens=itens)


@api.get("/envios/export")
def export_dispatch_report(
    faixa_id: str | None = None,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    rows_data = _dispatch_report_query(db, faixa_id).all()
    headers = ["Código do cliente", "Faixa de atraso", "Nome", "Valor cobrado", "Telefone que cobrou", "Data/hora"]
    rows = [
        [
            item.codigo_cliente,
            item.faixa.name if item.faixa else "",
            _formula_safe(item.nome),
            _formula_safe(item.valor or ""),
            item.whatsapp_number.display_phone_number if item.whatsapp_number else "",
            _hora_br(item.sent_at),
        ]
        for item in rows_data
        if item.sent_at
    ]
    return Response(
        content=_build_xlsx(headers, rows),
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="relatorio_envios.xlsx"'},
    )


# --- Relatório de Efetividade da Cobrança ------------------------------------
# Regras em services/efetividade_service.py — aqui só validação HTTP e resposta.


@api.get("/efetividade", response_model=schemas.RelatorioEfetividadeOut)
def relatorio_efetividade(
    cobrado_de: date | None = Query(None, description="Data de cobrança inicial"),
    cobrado_ate: date | None = Query(None, description="Data de cobrança final"),
    dias_janela: int | None = Query(None, ge=0, le=365, description="Janela de dias para pagamento após cobrança"),
    faixa: list[str] | None = Query(None),
    cluster: list[str] | None = Query(None),
    loja: list[str] | None = Query(None),
    regional: list[str] | None = Query(None),
    estado: list[str] | None = Query(None),
    cluster_inad: list[str] | None = Query(None),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    dados, leads_sem_parcelas, _itens = efetividade_service.obter_dados_efetividade(
        db,
        cobrado_de=cobrado_de,
        cobrado_ate=cobrado_ate,
        dias_janela=dias_janela,
        faixa=faixa,
        cluster=cluster,
        loja=loja,
        regional=regional,
        estado=estado,
        cluster_inad=cluster_inad,
    )
    valor_a_pagar_brl = efetividade_service.calcular_valor_a_pagar_brl(db, cobrado_de, cobrado_ate)
    return schemas.RelatorioEfetividadeOut(
        por_faixa=dados["por_faixa"],
        por_loja=dados["por_loja"],
        total=dados["total"],
        leads_sem_parcelas=leads_sem_parcelas,
        dias_janela=dias_janela,
        valor_a_pagar_brl=valor_a_pagar_brl,
    )


@api.get("/efetividade.xlsx")
def export_relatorio_efetividade(
    cobrado_de: date | None = Query(None),
    cobrado_ate: date | None = Query(None),
    dias_janela: int | None = Query(None, ge=0, le=365),
    faixa: list[str] | None = Query(None),
    cluster: list[str] | None = Query(None),
    loja: list[str] | None = Query(None),
    regional: list[str] | None = Query(None),
    estado: list[str] | None = Query(None),
    cluster_inad: list[str] | None = Query(None),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    dados, _leads_sem_parcelas, _itens = efetividade_service.obter_dados_efetividade(
        db,
        cobrado_de=cobrado_de,
        cobrado_ate=cobrado_ate,
        dias_janela=dias_janela,
        faixa=faixa,
        cluster=cluster,
        loja=loja,
        regional=regional,
        estado=estado,
        cluster_inad=cluster_inad,
    )
    content = _build_efetividade_xlsx(dados)
    return Response(
        content=content,
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="relatorio_efetividade.xlsx"'},
    )


@api.get("/efetividade/clientes", response_model=list[schemas.LinhaEfetividadeClienteOut])
def relatorio_efetividade_clientes(
    cobrado_de: date | None = Query(None),
    cobrado_ate: date | None = Query(None),
    dias_janela: int | None = Query(None, ge=0, le=365),
    faixa: list[str] | None = Query(None),
    cluster: list[str] | None = Query(None),
    loja: list[str] | None = Query(None),
    regional: list[str] | None = Query(None),
    estado: list[str] | None = Query(None),
    cluster_inad: list[str] | None = Query(None),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Mesmo relatório de efetividade, no nível de cada cliente/parcela
    cobrada — pra investigar caso a caso em vez de só o agregado."""

    _dados, _leads_sem_parcelas, itens = efetividade_service.obter_dados_efetividade(
        db,
        cobrado_de=cobrado_de,
        cobrado_ate=cobrado_ate,
        dias_janela=dias_janela,
        faixa=faixa,
        cluster=cluster,
        loja=loja,
        regional=regional,
        estado=estado,
        cluster_inad=cluster_inad,
    )
    return [
        schemas.LinhaEfetividadeClienteOut(
            codigo_cliente=it["codigo_cliente"],
            nome=it["nome"],
            faixa=it["faixa"],
            empresa=it["empresa"],
            titulo_codigo=it["titulo_codigo"],
            data_cobranca=it["data_cobranca"],
            valor_cobrar=it["valor_cobrar"],
            pago=it["pago"],
            valor_pago=it["valor_pago"],
            renegociada=it["renegociada"],
        )
        for it in itens
    ]


@api.get("/efetividade/clientes.xlsx")
def export_relatorio_efetividade_clientes(
    cobrado_de: date | None = Query(None),
    cobrado_ate: date | None = Query(None),
    dias_janela: int | None = Query(None, ge=0, le=365),
    faixa: list[str] | None = Query(None),
    cluster: list[str] | None = Query(None),
    loja: list[str] | None = Query(None),
    regional: list[str] | None = Query(None),
    estado: list[str] | None = Query(None),
    cluster_inad: list[str] | None = Query(None),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    _dados, _leads_sem_parcelas, itens = efetividade_service.obter_dados_efetividade(
        db,
        cobrado_de=cobrado_de,
        cobrado_ate=cobrado_ate,
        dias_janela=dias_janela,
        faixa=faixa,
        cluster=cluster,
        loja=loja,
        regional=regional,
        estado=estado,
        cluster_inad=cluster_inad,
    )
    headers = ["Código", "Nome", "Faixa", "Loja", "Título", "Data cobrança", "Valor cobrado", "Pagou", "Valor pago"]
    rows = [
        [
            _formula_safe(it["codigo_cliente"]),
            _formula_safe(it["nome"] or ""),
            it["faixa"],
            it["empresa"],
            it["titulo_codigo"],
            it["data_cobranca"].isoformat() if it["data_cobranca"] else "",
            float(it["valor_cobrar"] or 0),
            "Sim" if it["pago"] else "Não",
            float(it["valor_pago"] or 0),
        ]
        for it in itens
    ]
    content = _build_xlsx(headers, rows)
    return Response(
        content=content,
        media_type=_XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="relatorio_efetividade_clientes.xlsx"'},
    )


router = APIRouter()
router.include_router(api, prefix="/relatorios", tags=["relatorios"])
router.include_router(api, prefix="/reports", tags=["reports"])
