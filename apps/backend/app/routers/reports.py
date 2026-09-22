import io
from datetime import date, datetime, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session, selectinload

from .. import google_client, lojas as lojas_base, models, schemas, seta_client
from ..database import get_db
from ..deps import get_current_user
from ..regras_db import carregar_regras
from ..relatorio_efetividade import montar_relatorio

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
        "Clientes cobrados",
        "Valor cobrado",
        "Clientes que pagaram",
        "Valor pago",
        "Conversão (%)",
        "Recuperação (%)",
    ]
    ws_faixa.append(headers_faixa)

    for linha in relatorio["por_faixa"]:
        ws_faixa.append(
            [
                linha["faixa"],
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
            if col_idx in (3, 5):
                cell.number_format = '"R$" #,##0.00'
            elif col_idx in (6, 7):
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
        "Clientes cobrados",
        "Valor cobrado",
        "Clientes que pagaram",
        "Valor pago",
        "Conversão (%)",
        "Recuperação (%)",
    ]
    ws_loja.append(headers_loja)

    for linha in relatorio["por_loja"]:
        ws_loja.append(
            [
                linha["loja"],
                linha.get("regional") or "",
                linha.get("cluster_inad") or "",
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
            if col_idx in (5, 7):
                cell.number_format = '"R$" #,##0.00'
            elif col_idx in (8, 9):
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


def _invalid_phones_query(db: Session, faixa_id: str | None):
    query = db.query(models.InvalidPhoneRecord).order_by(models.InvalidPhoneRecord.created_at.desc())
    if faixa_id:
        query = query.filter(models.InvalidPhoneRecord.faixa_id == faixa_id)
    return query


@api.get("/telefones-invalidos", response_model=list[schemas.InvalidPhoneOut])
def list_invalid_phones(
    faixa_id: str | None = None,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    return _invalid_phones_query(db, faixa_id).limit(1000).all()


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


@api.get("/envios", response_model=list[schemas.DispatchReportItemOut])
def list_dispatch_report(
    faixa_id: str | None = None,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    return [_to_report_item(item) for item in _dispatch_report_rows(db, faixa_id) if item.sent_at]


@api.get("/envios/export")
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


# --- Relatório de Efetividade da Cobrança ------------------------------------


def _obter_dados_efetividade(
    db: Session,
    *,
    cobrado_de: date | None = None,
    cobrado_ate: date | None = None,
    dias_janela: int | None = None,
    faixa: list[str] | None = None,
    cluster: list[str] | None = None,
    loja: list[str] | None = None,
    regional: list[str] | None = None,
    estado: list[str] | None = None,
    cluster_inad: list[str] | None = None,
) -> tuple[dict, int]:
    try:
        codigos_loja = lojas_base.combinar_lojas(
            db,
            loja=loja,
            regional=regional,
            estado=estado,
            cluster_inad=cluster_inad,
        )
    except google_client.GoogleIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    regras = carregar_regras(db)
    if codigos_loja is not None and len(codigos_loja) == 0:
        return montar_relatorio([], lojas_info={}, faixas_ordem=regras.nomes_faixa), 0

    try:
        lojas_info = {l["filial"]: l for l in lojas_base.listar_lojas(db)}
    except google_client.GoogleIndisponivel:
        lojas_info = {}

    leads_query = db.query(models.Lead).filter(models.Lead.status == "cobrado")
    if cobrado_de:
        leads_query = leads_query.filter(
            models.Lead.cobrado_em >= datetime.combine(cobrado_de, datetime.min.time())
        )
    if cobrado_ate:
        leads_query = leads_query.filter(
            models.Lead.cobrado_em <= datetime.combine(cobrado_ate, datetime.max.time())
        )
    if faixa:
        leads_query = leads_query.filter(models.Lead.faixa.in_(faixa))
    if cluster:
        leads_query = leads_query.filter(models.Lead.cluster.in_(cluster))

    leads_sem_parcelas = leads_query.filter(~models.Lead.parcelas.any()).count()

    parc_query = (
        db.query(
            models.LeadParcela.titulo_codigo,
            models.LeadParcela.empresa,
            models.LeadParcela.valor,
            models.LeadParcela.valor_cobrar,
            models.Lead.codigo_cliente,
            models.Lead.faixa,
            models.Lead.cobrado_em,
        )
        .join(models.Lead, models.LeadParcela.lead_id == models.Lead.id)
        .filter(models.Lead.status == "cobrado")
    )
    if cobrado_de:
        parc_query = parc_query.filter(
            models.Lead.cobrado_em >= datetime.combine(cobrado_de, datetime.min.time())
        )
    if cobrado_ate:
        parc_query = parc_query.filter(
            models.Lead.cobrado_em <= datetime.combine(cobrado_ate, datetime.max.time())
        )
    if faixa:
        parc_query = parc_query.filter(models.Lead.faixa.in_(faixa))
    if cluster:
        parc_query = parc_query.filter(models.Lead.cluster.in_(cluster))
    if codigos_loja is not None:
        parc_query = parc_query.filter(models.LeadParcela.empresa.in_(codigos_loja))

    parcelas_db = parc_query.all()

    codigos_titulos = list({p.titulo_codigo for p in parcelas_db})
    situacoes: dict[str, dict] = {}
    if codigos_titulos:
        try:
            situacoes = seta_client.situacao_titulos(codigos_titulos)
        except seta_client.SetaIndisponivel as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    itens = []
    for p in parcelas_db:
        sit = situacoes.get(p.titulo_codigo)
        data_cobranca = p.cobrado_em.date() if p.cobrado_em else None
        pago = False
        renegociada = False
        valor_pago = Decimal("0.00")

        if sit:
            st = sit.get("status")
            if st == "B" and data_cobranca:
                pagamento = sit.get("pagamento")
                if hasattr(pagamento, "date") and callable(pagamento.date):
                    pagamento = pagamento.date()
                if pagamento and pagamento >= data_cobranca:
                    if dias_janela is None or pagamento <= data_cobranca + timedelta(days=dias_janela):
                        pago = True
                        valorpago = sit.get("valorpago")
                        if valorpago is not None and Decimal(str(valorpago)) > 0:
                            valor_pago = Decimal(str(valorpago))
                        else:
                            valor_pago = Decimal(str(sit.get("valor") or 0))
            elif st == "S":
                renegociada = True

        itens.append(
            {
                "codigo_cliente": p.codigo_cliente,
                "faixa": p.faixa,
                "empresa": p.empresa,
                "valor_cobrar": p.valor_cobrar,
                "pago": pago,
                "renegociada": renegociada,
                "valor_pago": valor_pago,
            }
        )

    relatorio = montar_relatorio(itens, lojas_info=lojas_info, faixas_ordem=regras.nomes_faixa)
    return relatorio, leads_sem_parcelas


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
    dados, leads_sem_parcelas = _obter_dados_efetividade(
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
    return schemas.RelatorioEfetividadeOut(
        por_faixa=dados["por_faixa"],
        por_loja=dados["por_loja"],
        total=dados["total"],
        leads_sem_parcelas=leads_sem_parcelas,
        dias_janela=dias_janela,
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
    dados, _ = _obter_dados_efetividade(
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


router = APIRouter()
router.include_router(api, prefix="/relatorios", tags=["relatorios"])
router.include_router(api, prefix="/reports", tags=["reports"])
