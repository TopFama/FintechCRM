"""Leitura da fila (cobranca_fila) para os relatórios e o Dashboard: os
mesmos filtros (faixa, campanha, loja, período em dias de Brasília) e as
mesmas consultas, para card e relatório contarem igual. Só leitura."""

from datetime import date, datetime, timedelta

from sqlalchemy import Numeric, and_, case, func, or_, select, true
from sqlalchemy.orm import Session, contains_eager, selectinload

from . import campanhas_fixas, models, pausas
from .regras_db import carregar_regras
from .timezone import dia_br, inicio_do_dia_utc


def filtro_faixa(db: Session, faixa_id: str):
    """Itens da faixa. Numa faixa de atraso (régua), também os envios de
    campanha/remarketing a clientes que estavam nela, como no "Por faixa"
    do Dashboard."""
    faixa = db.get(models.Faixa, faixa_id)
    if faixa is None or faixa.tipo != models.TIPO_REGUA:
        return models.QueueItem.faixa_id == faixa_id
    return or_(models.QueueItem.faixa_id == faixa_id, models.QueueItem.faixa_atraso == faixa.name)

def filtro_campanha(db: Session, coluna_faixa_id, campanha: str | None):
    """Filtro "Campanha" dos relatórios da fila: "regua" = só as faixas de
    atraso; id = só os envios feitos por aquela campanha (a faixa dela)."""
    if campanha == "regua":
        return coluna_faixa_id.in_(select(models.Faixa.id).where(models.Faixa.tipo == models.TIPO_REGUA))
    if campanhas_fixas.eh_fixa(campanha):
        return coluna_faixa_id == campanhas_fixas.faixa_id(db, campanha)
    c = db.get(models.Campanha, campanha)
    return coluna_faixa_id == (c.faixa_id if c else None)

def no_periodo(query, coluna, de: date | None, ate: date | None):
    """Período em dias de Brasília sobre um timestamp UTC do banco."""
    if de:
        query = query.filter(coluna >= inicio_do_dia_utc(de))
    if ate:
        query = query.filter(coluna < inicio_do_dia_utc(ate + timedelta(days=1)))
    return query

def envios_realizados(
    db: Session,
    faixa_id: str | None,
    de: date | None = None,
    ate: date | None = None,
    sort_by: str | None = None,
    sort_dir: str = "asc",
    campanha: str | None = None,
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
        query = query.filter(filtro_faixa(db, faixa_id))
    if campanha:
        query = query.filter(filtro_campanha(db, models.QueueItem.faixa_id, campanha))
    query = no_periodo(query, models.QueueItem.sent_at, de, ate)

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
    elif sort_by == "valor":
        query = query.order_by(_ordenado(valor_numerico()).nulls_last(), models.QueueItem.id)
    elif sort_by in ("codigo_cliente", "nome"):
        query = query.order_by(_ordenado(getattr(models.QueueItem, sort_by)), models.QueueItem.id)
    elif sort_by == "enviado_em":
        query = query.order_by(_ordenado(models.QueueItem.sent_at), models.QueueItem.id)
    else:
        query = query.order_by(models.QueueItem.sent_at.desc())
    return query

def valor_numerico():
    """QueueItem.valor (texto: "1.500,00" da planilha ou "1500.00" do SETA)
    como número, para ordenar pelo valor e não em ordem alfabética. Texto
    fora desses formatos fica sem valor (vai para o fim)."""

    texto = models.QueueItem.valor
    sem_milhar = case(
        (texto.like("%,%"), func.replace(func.replace(texto, ".", ""), ",", ".")),
        else_=texto,
    )
    return case((sem_milhar.op("~")(r"^-?[0-9]+(\.[0-9]+)?$"), func.cast(sem_milhar, Numeric)), else_=None)


def separar_faixa(item: models.QueueItem, nome_faixa: str) -> tuple[str | None, str | None]:
    """(faixa de atraso, campanha) do item, pelo tipo da faixa: régua tem só a
    faixa; campanha e remarketing têm o nome da campanha e a faixa de atraso
    do cliente."""
    if item.faixa.tipo == models.TIPO_REGUA:
        return nome_faixa, None
    return item.faixa_atraso, nome_faixa.removeprefix("Campanha: ")

def ultimo_erro():
    return (
        select(models.ErrorLog.queue_item_id, func.max(models.ErrorLog.created_at).label("quando"))
        .group_by(models.ErrorLog.queue_item_id)
        .subquery()
    )


def itens_da_fila(
    db: Session,
    status_fila: tuple[models.QueueStatus, ...],
    faixa_id: str | None,
    de: date | None,
    ate: date | None,
    sort_by: str | None = None,
    sort_dir: str = "asc",
    loja: str | None = None,
    campanha: str | None = None,
):
    ultimo = ultimo_erro()
    # erro de upload/extração não passa por log_erros: vale a entrada na fila
    quando = func.coalesce(ultimo.c.quando, models.QueueItem.created_at)
    query = (
        db.query(models.QueueItem, models.Faixa.name, quando)
        .join(models.Faixa, models.Faixa.id == models.QueueItem.faixa_id)
        .options(contains_eager(models.QueueItem.faixa))  # tipo da faixa sem consulta por item
        .outerjoin(ultimo, ultimo.c.queue_item_id == models.QueueItem.id)
        .filter(models.QueueItem.status.in_(status_fila))
    )
    if faixa_id:
        query = query.filter(filtro_faixa(db, faixa_id))
    if campanha:
        query = query.filter(filtro_campanha(db, models.QueueItem.faixa_id, campanha))
    if loja:
        query = query.filter(models.QueueItem.lojas.like(f"%,{pausas.normalizar_valor('loja', loja)},%"))
    query = no_periodo(query, models.QueueItem.created_at, de, ate)

    def _ordenado(coluna):
        return coluna.desc() if sort_dir == "desc" else coluna.asc()

    eh_campanha = models.Faixa.tipo != models.TIPO_REGUA
    if sort_by == "faixa":
        nomes_faixa = carregar_regras(db).nomes_faixa
        faixa_atraso = case((eh_campanha, models.QueueItem.faixa_atraso), else_=models.Faixa.name)
        expr = (
            case({nome: i for i, nome in enumerate(nomes_faixa)}, value=faixa_atraso, else_=len(nomes_faixa))
            if nomes_faixa
            else faixa_atraso
        )
        return query.order_by(_ordenado(expr), models.QueueItem.id)
    if sort_by == "campanha":
        # régua (sem campanha) fica junto, antes das campanhas no crescente
        expr = case((eh_campanha, models.Faixa.name), else_="")
        return query.order_by(_ordenado(expr), models.QueueItem.id)
    colunas = {
        "codigo_cliente": models.QueueItem.codigo_cliente,
        "nome": models.QueueItem.nome,
        "valor": valor_numerico(),
        "telefone": models.QueueItem.celular,
        "entrou_em": models.QueueItem.created_at,
        "quando": quando,
        "mensagem": models.QueueItem.error_message,
    }
    if sort_by in colunas:
        return query.order_by(_ordenado(colunas[sort_by]).nulls_last(), models.QueueItem.id)
    padrao = quando if models.QueueStatus.error in status_fila else models.QueueItem.created_at
    return query.order_by(padrao.desc(), models.QueueItem.id)


# --- Dashboard: período dos cards ---


def limites_utc(de: date | None, ate: date | None) -> tuple[datetime | None, datetime | None]:
    """Datas locais (GMT-3) → limites em UTC naive, como está gravado no banco."""
    ini = inicio_do_dia_utc(de) if de else None
    fim = inicio_do_dia_utc(ate + timedelta(days=1)) if ate else None
    return ini, fim


def condicao_periodo(coluna, ini: datetime | None, fim: datetime | None):
    conds = []
    if ini:
        conds.append(coluna >= ini)
    if fim:
        conds.append(coluna < fim)
    return and_(true(), *conds)


def periodo_dos_cards(de: date | None, ate: date | None):
    """Enviado conta pela data do envio, o resto pela data em que entrou na fila."""
    ini, fim = limites_utc(de, ate)
    return or_(
        and_(models.QueueItem.status == models.QueueStatus.sent, condicao_periodo(models.QueueItem.sent_at, ini, fim)),
        and_(models.QueueItem.status != models.QueueStatus.sent, condicao_periodo(models.QueueItem.created_at, ini, fim)),
    )


def dia_do_card(status: str, criado: datetime | None, enviado: datetime | None) -> date | None:
    """Dia (Brasília) em que o item conta nos cards: a mesma regra de
    periodo_dos_cards, para os contadores do Dashboard em tempo real."""
    quando = enviado if status == models.QueueStatus.sent.value else criado
    return dia_br(quando) if quando else None


def contar_cards(db: Session, de: date | None, ate: date | None) -> dict[str, int]:
    """Números dos cards do Dashboard no período, iguais aos totais dos relatórios."""
    ini, fim = limites_utc(de, ate)
    periodo = periodo_dos_cards(de, ate)
    return {
        "total_pendentes": contar(db, periodo, models.QueueStatus.pending, models.QueueStatus.reserved),
        "total_enviados": contar(db, periodo, models.QueueStatus.sent),
        "total_erros": contar(db, periodo, models.QueueStatus.error),
        "total_telefones_invalidos": db.query(func.count(models.InvalidPhoneRecord.id))
        .filter(condicao_periodo(models.InvalidPhoneRecord.created_at, ini, fim))
        .scalar()
        or 0,
    }


def contar(db: Session, periodo, *status_values: models.QueueStatus) -> int:
    return (
        db.query(func.count(models.QueueItem.id))
        .filter(models.QueueItem.status.in_(status_values), periodo)
        .scalar()
        or 0
    )


def contar_pausados(db: Session, periodo) -> int:
    return (
        db.query(func.count(models.QueueItem.id))
        .filter(models.QueueItem.status.in_(pausas.STATUS_PENDENTE), periodo, pausas.Retencao.carregar(db).condicao())
        .scalar()
        or 0
    )
