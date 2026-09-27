import io
import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from openpyxl import Workbook
from openpyxl.formatting.rule import FormulaRule
from openpyxl.styles import Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session, selectinload

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user
from ..regras_db import carregar_regras
from .. import cache, consultas_fila, fila_automatica, pausas, seta_client
from ..services import efetividade_service, pagamentos_service
from ..timezone import hora_br
from ..utils.xlsx import XLSX_MEDIA_TYPE, build_xlsx, formula_safe, texto_nunca_formula

api = APIRouter()
logger = logging.getLogger(__name__)


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
        "Código loja",
        "Nome da loja",
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
                linha.get("loja_nome") or "",
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
            if col_idx in (7, 9):
                cell.number_format = '"R$" #,##0.00'
            elif col_idx in (10, 11):
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

    # Formatação condicional sobre o intervalo de dados da coluna Cluster INAD (coluna D)
    num_dados_loja = len(relatorio["por_loja"])
    cf_range = f"D2:D{num_dados_loja + 1}" if num_dados_loja > 0 else "D2:D2"

    # Mesmas cores da planilha de lojas e da tela (TOP azul, UTI vermelho,
    # UTI + roxo). "UTI +" vem antes e para ali, senão pegaria a regra de "UTI".
    def regra(formula: str, cor: str) -> FormulaRule:
        return FormulaRule(
            formula=[formula],
            fill=PatternFill(start_color=cor, end_color=cor, fill_type="solid"),
            font=Font(color="FFFFFF"),
            stopIfTrue=True,
        )

    ws_loja.conditional_formatting.add(cf_range, regra('TRIM(D2)="CLUSTER UTI +"', "702F9F"))
    ws_loja.conditional_formatting.add(cf_range, regra('TRIM(D2)="CLUSTER UTI"', "F9000B"))
    ws_loja.conditional_formatting.add(cf_range, regra('TRIM(D2)="CLUSTER TOP"', "4B73C3"))

    # Aba 3: Por campanha (régua de atraso numa linha, cada campanha na sua)
    ws_camp = wb.create_sheet(title="Por campanha")
    headers_camp = ["Campanha", *headers_faixa[1:]]
    ws_camp.append(headers_camp)
    for linha in [*relatorio.get("por_campanha", []), {"campanha": "Total", **tot}]:
        ws_camp.append(
            [
                linha["campanha"],
                linha["qtd_envios"],
                linha["clientes_cobrados"],
                float(linha["valor_cobrado"]),
                linha["clientes_pagaram"],
                float(linha["valor_pago"]),
                float(linha["conversao_clientes"]),
                float(linha["recuperacao_valor"]),
            ]
        )
    for cell in ws_camp[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = PatternFill("solid", fgColor="003090")
    for row_idx in range(2, ws_camp.max_row + 1):
        for col_idx, cell in enumerate(ws_camp[row_idx], start=1):
            if row_idx == ws_camp.max_row:
                cell.font = Font(bold=True)
            if col_idx in (4, 6):
                cell.number_format = '"R$" #,##0.00'
            elif col_idx in (7, 8):
                cell.number_format = "0.0%"
    ws_camp.freeze_panes = "A2"
    ws_camp.column_dimensions["A"].width = 40

    # Nome de campanha, faixa e loja vêm de cadastro: nada vira fórmula
    for ws in wb.worksheets:
        for row in ws.iter_rows():
            for cell in row:
                texto_nunca_formula(cell)

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
    db: Session,
    faixa_id: str | None,
    de: date | None = None,
    ate: date | None = None,
    sort_by: str | None = None,
    sort_dir: str = "asc",
    campanha: str | None = None,
):
    query = db.query(models.InvalidPhoneRecord)
    if faixa_id:
        query = query.filter(models.InvalidPhoneRecord.faixa_id == faixa_id)
    if campanha:
        query = query.filter(consultas_fila.filtro_campanha(db, models.InvalidPhoneRecord.faixa_id, campanha))
    query = consultas_fila.no_periodo(query, models.InvalidPhoneRecord.created_at, de, ate)
    coluna = _INVALID_PHONE_SORT_COLUNAS.get(sort_by) if sort_by else None
    if coluna is not None:
        query = query.order_by(
            coluna.desc() if sort_dir == "desc" else coluna.asc(), models.InvalidPhoneRecord.id
        )
    else:
        query = query.order_by(models.InvalidPhoneRecord.created_at.desc())
    return query




@api.get("/telefones-invalidos", response_model=schemas.InvalidPhonePage)
def list_invalid_phones(
    faixa_id: str | None = None,
    campanha: str | None = Query(None, description='"regua" = só faixas de atraso; ou o id da campanha'),
    de: date | None = Query(None, description="Período de cobrança: início (GMT-3)"),
    ate: date | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: InvalidPhoneSortColumn | None = Query(None),
    sort_dir: Literal["asc", "desc"] = Query("asc"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    query = _invalid_phones_query(db, faixa_id, de, ate, sort_by, sort_dir, campanha)
    total = query.count()
    itens = query.offset(offset).limit(limit).all()
    return schemas.InvalidPhonePage(total=total, itens=itens)


@api.get("/telefones-invalidos/export")
def export_invalid_phones(
    faixa_id: str | None = None,
    campanha: str | None = Query(None, description='"regua" = só faixas de atraso; ou o id da campanha'),
    de: date | None = Query(None, description="Período de cobrança: início (GMT-3)"),
    ate: date | None = Query(None),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    records = (
        _invalid_phones_query(db, faixa_id, de, ate, campanha=campanha)
        .options(selectinload(models.InvalidPhoneRecord.faixa))
        .all()
    )
    headers = ["Código do cliente", "Faixa", "Telefone informado", "Telefone normalizado", "Motivo", "Data/hora"]
    rows = [
        [
            r.codigo_cliente,
            r.faixa.name if r.faixa else "",
            formula_safe(r.celular_original),
            r.celular_normalizado or "",
            r.motivo,
            hora_br(r.created_at),
        ]
        for r in records
    ]
    return Response(
        content=build_xlsx(headers, rows),
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="telefones_invalidos.xlsx"'},
    )


DispatchSortColumn = Literal["codigo_cliente", "faixa", "nome", "valor", "telefone", "enviado_em"]


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
    campanha: str | None = Query(None, description='"regua" = só faixas de atraso; ou o id da campanha'),
    de: date | None = Query(None, description="Período de cobrança: início (GMT-3)"),
    ate: date | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: DispatchSortColumn | None = Query(None),
    sort_dir: Literal["asc", "desc"] = Query("asc"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    query = consultas_fila.envios_realizados(db, faixa_id, de, ate, sort_by, sort_dir, campanha)
    total = query.count()
    itens = [_to_report_item(item) for item in query.offset(offset).limit(limit).all()]
    return schemas.DispatchReportPage(total=total, itens=itens)


@api.get("/envios/export")
def export_dispatch_report(
    faixa_id: str | None = None,
    campanha: str | None = Query(None, description='"regua" = só faixas de atraso; ou o id da campanha'),
    de: date | None = Query(None, description="Período de cobrança: início (GMT-3)"),
    ate: date | None = Query(None),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    rows_data = consultas_fila.envios_realizados(db, faixa_id, de, ate, campanha=campanha).all()
    headers = ["Código do cliente", "Faixa de atraso", "Nome", "Valor cobrado", "Telefone que cobrou", "Data/hora"]
    rows = [
        [
            item.codigo_cliente,
            item.faixa.name if item.faixa else "",
            formula_safe(item.nome),
            formula_safe(item.valor or ""),
            item.whatsapp_number.display_phone_number if item.whatsapp_number else "",
            hora_br(item.sent_at),
        ]
        for item in rows_data
        if item.sent_at
    ]
    return Response(
        content=build_xlsx(headers, rows),
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="relatorio_envios.xlsx"'},
    )


# --- Pendentes e erros (itens da fila) ---------------------------------------
# Mesmas regras de data dos cards do Dashboard: pendente e erro contam pela
# data em que entraram na fila (created_at), pra contagem bater com o card.


FilaSortColumn = Literal[
    "codigo_cliente", "nome", "faixa", "campanha", "valor", "telefone", "entrou_em", "quando", "mensagem"
]

_STATUS_PENDENTE = (models.QueueStatus.pending, models.QueueStatus.reserved)


def _to_fila_item(
    item: models.QueueItem, nome_faixa: str, quando: datetime, retencao: pausas.Retencao | None = None
) -> schemas.FilaReportItemOut:
    return schemas.FilaReportItemOut(
        lojas=[l for l in (item.lojas or "").split(",") if l],
        pausado=bool(retencao) and item.status in pausas.STATUS_PENDENTE and retencao.retido(item),
        id=item.id,
        codigo_cliente=item.codigo_cliente,
        nome=item.nome,
        faixa_id=item.faixa_id,
        faixa=consultas_fila.separar_faixa(item, nome_faixa)[0],
        campanha=consultas_fila.separar_faixa(item, nome_faixa)[1],
        valor=item.valor,
        telefone=item.celular,
        entrou_em=item.created_at,
        mensagem=(item.error_message or "Erro sem detalhe") if item.status == models.QueueStatus.error else None,
        quando=quando,
    )


def _pagina_fila(db, status_fila, faixa_id, de, ate, limit, offset, sort_by, sort_dir, loja=None, campanha=None):
    query = consultas_fila.itens_da_fila(db, status_fila, faixa_id, de, ate, sort_by, sort_dir, loja, campanha)
    total = query.count()
    retencao = pausas.Retencao.carregar(db)
    itens = [_to_fila_item(*linha, retencao) for linha in query.offset(offset).limit(limit).all()]
    pagina = schemas.FilaReportPage(total=total, itens=itens)
    if status_fila == _STATUS_PENDENTE:
        pagina.total_pausados = query.filter(retencao.condicao()).order_by(None).count()
        pagina.total_sem_loja = query.filter(models.QueueItem.lojas == ",").order_by(None).count()
    return pagina


@api.get("/pendentes", response_model=schemas.FilaReportPage)
def list_pendentes(
    faixa_id: str | None = None,
    campanha: str | None = Query(None, description='"regua" = só faixas de atraso; ou o id da campanha'),
    loja: str | None = Query(None, description="Filial (ex.: 07)"),
    de: date | None = Query(None, description="Entrou na fila de (GMT-3)"),
    ate: date | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: FilaSortColumn | None = Query(None),
    sort_dir: Literal["asc", "desc"] = Query("asc"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    return _pagina_fila(db, _STATUS_PENDENTE, faixa_id, de, ate, limit, offset, sort_by, sort_dir, loja, campanha)


@api.get("/pendentes/export")
def export_pendentes(
    faixa_id: str | None = None,
    campanha: str | None = Query(None, description='"regua" = só faixas de atraso; ou o id da campanha'),
    loja: str | None = Query(None),
    de: date | None = Query(None),
    ate: date | None = Query(None),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    linhas = consultas_fila.itens_da_fila(db, _STATUS_PENDENTE, faixa_id, de, ate, loja=loja, campanha=campanha).all()
    retencao = pausas.Retencao.carregar(db)
    headers = [
        "Código do cliente", "Nome", "Faixa de atraso", "Campanha", "Valor", "Telefone", "Lojas", "Entrou na fila em",
        "Pausado",
    ]
    rows = [
        [item.codigo_cliente, formula_safe(item.nome), consultas_fila.separar_faixa(item, faixa)[0] or "",
         formula_safe(consultas_fila.separar_faixa(item, faixa)[1] or ""), formula_safe(item.valor or ""),
         formula_safe(item.celular), (item.lojas or "").strip(","), hora_br(item.created_at),
         "Sim" if retencao.retido(item) else "Não"]
        for item, faixa, _q in linhas
    ]
    return Response(
        content=build_xlsx(headers, rows),
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="relatorio_pendentes.xlsx"'},
    )


# "Descartar fila": tira da fila os pendentes que batem com os filtros da tela,
# como a expiração do fim do dia faz (sem registro "parado"); o cliente pode
# voltar à fila depois. Item já reservado por um envio em andamento fica.


def _descartaveis(db, faixa_id, loja, de, ate, campanha):
    query = consultas_fila.itens_da_fila(db, (models.QueueStatus.pending,), faixa_id, de, ate, loja=loja, campanha=campanha)
    return [item.id for item, _f, _q in query.order_by(None).all()]


@api.get("/pendentes/descartar/previa", response_model=schemas.PararEnvioOut)
def previa_descartar_pendentes(
    faixa_id: str | None = None,
    campanha: str | None = Query(None),
    loja: str | None = Query(None),
    de: date | None = Query(None),
    ate: date | None = Query(None),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    return schemas.PararEnvioOut(qtd=len(_descartaveis(db, faixa_id, loja, de, ate, campanha)))


@api.post("/pendentes/descartar", response_model=schemas.PararEnvioOut)
def descartar_pendentes(
    faixa_id: str | None = None,
    campanha: str | None = Query(None),
    loja: str | None = Query(None),
    de: date | None = Query(None),
    ate: date | None = Query(None),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    total = fila_automatica.descartar_pendentes(db, _descartaveis(db, faixa_id, loja, de, ate, campanha))
    logger.info("Fila descartada por %s: %s pendente(s)", user.email, total)
    return schemas.PararEnvioOut(qtd=total)


@api.get("/erros", response_model=schemas.FilaReportPage)
def list_erros(
    faixa_id: str | None = None,
    campanha: str | None = Query(None, description='"regua" = só faixas de atraso; ou o id da campanha'),
    de: date | None = Query(None, description="Entrou na fila de (GMT-3)"),
    ate: date | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: FilaSortColumn | None = Query(None),
    sort_dir: Literal["asc", "desc"] = Query("asc"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    return _pagina_fila(
        db, (models.QueueStatus.error,), faixa_id, de, ate, limit, offset, sort_by, sort_dir, campanha=campanha
    )


@api.get("/erros/export")
def export_erros(
    faixa_id: str | None = None,
    campanha: str | None = Query(None, description='"regua" = só faixas de atraso; ou o id da campanha'),
    de: date | None = Query(None),
    ate: date | None = Query(None),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    linhas = consultas_fila.itens_da_fila(db, (models.QueueStatus.error,), faixa_id, de, ate, campanha=campanha).all()
    headers = ["Código do cliente", "Nome", "Faixa de atraso", "Campanha", "Valor", "Telefone", "Mensagem de erro", "Quando"]
    rows = [
        [item.codigo_cliente, formula_safe(item.nome), consultas_fila.separar_faixa(item, faixa)[0] or "",
         formula_safe(consultas_fila.separar_faixa(item, faixa)[1] or ""), formula_safe(item.valor or ""),
         formula_safe(item.celular), formula_safe(item.error_message or "Erro sem detalhe"), hora_br(quando)]
        for item, faixa, quando in linhas
    ]
    return Response(
        content=build_xlsx(headers, rows),
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="relatorio_erros.xlsx"'},
    )


# --- Relatório de Efetividade da Cobrança ------------------------------------
# Regras em services/efetividade_service.py — aqui só validação HTTP e resposta.


EfetividadeSortColumn = Literal[efetividade_service.COLUNAS_ORDENAVEIS]


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
    cobradora: list[str] | None = Query(None),
    campanha: str | None = Query(None, description='"regua" ou id da campanha'),
    sort_by: EfetividadeSortColumn | None = Query(None),
    sort_dir: Literal["asc", "desc"] = Query("asc"),
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
        cobradora=cobradora,
        campanha=campanha,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    valor_a_pagar_brl = efetividade_service.calcular_valor_a_pagar_brl(db, cobrado_de, cobrado_ate)
    return schemas.RelatorioEfetividadeOut(
        por_faixa=dados["por_faixa"],
        por_loja=dados["por_loja"],
        por_campanha=dados["por_campanha"],
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
    cobradora: list[str] | None = Query(None),
    campanha: str | None = Query(None, description='"regua" ou id da campanha'),
    sort_by: EfetividadeSortColumn | None = Query(None),
    sort_dir: Literal["asc", "desc"] = Query("asc"),
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
        cobradora=cobradora,
        campanha=campanha,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    content = _build_efetividade_xlsx(dados)
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
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
    cobradora: list[str] | None = Query(None),
    campanha: str | None = Query(None, description='"regua" ou id da campanha'),
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
        cobradora=cobradora,
        campanha=campanha,
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
    cobradora: list[str] | None = Query(None),
    campanha: str | None = Query(None, description='"regua" ou id da campanha'),
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
        cobradora=cobradora,
        campanha=campanha,
    )
    headers = ["Código", "Nome", "Faixa", "Loja", "Título", "Data cobrança", "Valor cobrado", "Pagou", "Valor pago"]
    rows = [
        [
            formula_safe(it["codigo_cliente"]),
            formula_safe(it["nome"] or ""),
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
    content = build_xlsx(headers, rows)
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="relatorio_efetividade_clientes.xlsx"'},
    )


# --- Quem pagou o que foi cobrado (por cliente) -------------------------------


_CAMPOS_DATA_PAGAMENTO = ("data_cobranca", "primeiro_pagamento", "ultimo_pagamento")


def _pagamentos(db, cobrado_de, cobrado_ate, pago_de, pago_ate, faixa, dias_janela=None, campanha=None):
    """Resultado cacheado por conjunto de filtros (compartilhado entre usuários):
    ordenar, paginar e exportar com os mesmos filtros não reconsulta o SETA."""

    filtros = dict(
        cobrado_de=cobrado_de, cobrado_ate=cobrado_ate, pago_de=pago_de, pago_ate=pago_ate,
        faixa=sorted(faixa or []), dias_janela=dias_janela, campanha=campanha,
    )

    def calcular():
        return pagamentos_service.clientes_que_pagaram(db, **{**filtros, "faixa": faixa})

    try:
        try:
            linhas = cache.obter_ou_calcular(cache.chave("relatorio-pagamentos", filtros), calcular, ttl_segundos=300)
        except cache.CacheIndisponivel:
            linhas = calcular()
    except seta_client.SetaIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    # o cache guarda JSON: devolve datas e valores aos tipos originais
    for l in linhas:
        for campo in _CAMPOS_DATA_PAGAMENTO:
            if isinstance(l.get(campo), str):
                l[campo] = date.fromisoformat(l[campo])
        for campo in ("valor_cobrado", "valor_pago"):
            l[campo] = Decimal(str(l[campo]))
    return linhas


PagamentoSortColumn = Literal[pagamentos_service.COLUNAS_ORDENAVEIS]


@api.get("/pagamentos", response_model=schemas.PagamentosClientesPage)
def relatorio_pagamentos(
    cobrado_de: date | None = Query(None, description="Período de cobrança: início (GMT-3)"),
    cobrado_ate: date | None = Query(None),
    pago_de: date | None = Query(None, description="Período de pagamento: início"),
    pago_ate: date | None = Query(None),
    faixa: list[str] | None = Query(None),
    campanha: str | None = Query(None, description='"regua" = só faixas de atraso; ou o id da campanha'),
    dias_janela: int | None = Query(None, ge=0, le=365, description="Pagou em até N dias corridos da cobrança"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: PagamentoSortColumn | None = Query(None),
    sort_dir: Literal["asc", "desc"] = Query("asc"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    linhas = _pagamentos(db, cobrado_de, cobrado_ate, pago_de, pago_ate, faixa, dias_janela, campanha)
    if sort_by:
        linhas = pagamentos_service.ordenar(linhas, sort_by, sort_dir, carregar_regras(db).nomes_faixa)
    return schemas.PagamentosClientesPage(
        total=len(linhas),
        total_clientes=len({l["codigo_cliente"] for l in linhas}),
        valor_cobrado=sum((l["valor_cobrado"] for l in linhas), Decimal("0.00")),
        valor_pago=sum((l["valor_pago"] for l in linhas), Decimal("0.00")),
        itens=linhas[offset : offset + limit],
    )


@api.get("/pagamentos/export")
def export_relatorio_pagamentos(
    cobrado_de: date | None = Query(None),
    cobrado_ate: date | None = Query(None),
    pago_de: date | None = Query(None),
    pago_ate: date | None = Query(None),
    faixa: list[str] | None = Query(None),
    campanha: str | None = Query(None, description='"regua" = só faixas de atraso; ou o id da campanha'),
    dias_janela: int | None = Query(None, ge=0, le=365),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    linhas = _pagamentos(db, cobrado_de, cobrado_ate, pago_de, pago_ate, faixa, dias_janela, campanha)
    headers = [
        "Código do cliente", "Nome", "CPF", "Loja", "Faixa", "Data da cobrança", "Valor cobrado",
        "Valor pago", "Títulos pagos", "Primeiro pagamento", "Último pagamento",
    ]
    rows = [
        [
            l["codigo_cliente"], formula_safe(l["nome"] or ""), l["cpf"] or "", formula_safe(l["loja"]),
            l["faixa"], l["data_cobranca"], float(l["valor_cobrado"]), float(l["valor_pago"]),
            l["qtd_titulos_pagos"], l["primeiro_pagamento"], l["ultimo_pagamento"],
        ]
        for l in linhas
    ]
    return Response(
        content=build_xlsx(headers, rows),
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="relatorio_pagamentos.xlsx"'},
    )


router = APIRouter()
router.include_router(api, prefix="/relatorios", tags=["relatorios"])
router.include_router(api, prefix="/reports", tags=["reports"])
