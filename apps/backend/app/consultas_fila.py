"""Leitura da fila (cobranca_fila) para os relatórios e o Dashboard: os
mesmos filtros (faixa, campanha, loja, período em dias de Brasília) e as
mesmas consultas, para card e relatório contarem igual. Só leitura."""

import re
from datetime import date, datetime, timedelta

from sqlalchemy import Numeric, and_, case, func, or_, select, true
from sqlalchemy.orm import Session, contains_eager, selectinload

from . import campanhas_fixas, filtros_coluna, models, pausas
from .filtros_coluna import Coluna
from .config import settings
from .regras_db import carregar_regras
from .timezone import dia_br, inicio_do_dia_utc


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

def um_por_telefone(db: Session, filtrada):
    """Telefones inválidos já filtrados, um registro por número (o mais recente),
    para relatório, exportação e card contarem números e não tentativas."""
    r = models.InvalidPhoneRecord
    ultimas = filtrada.with_entities(r.id, func.row_number().over(
        partition_by=func.coalesce(r.celular_normalizado, r.celular_original),
        order_by=(r.created_at.desc(), r.id.desc()),
    ).label("pos")).subquery()
    return db.query(r).filter(r.id.in_(select(ultimas.c.id).where(ultimas.c.pos == 1)))


def envios_realizados(
    db: Session,
    de: date | None = None,
    ate: date | None = None,
    sort_by: str | None = None,
    sort_dir: str = "asc",
    filtros: dict | None = None,
    carregar: bool = True,
):
    query = (
        db.query(models.QueueItem)
        .join(models.QueueItem.faixa)
        .outerjoin(models.QueueItem.whatsapp_number)
        .filter(models.QueueItem.status == models.QueueStatus.sent, models.QueueItem.sent_at.isnot(None))
    )
    if carregar:
        query = query.options(selectinload(models.QueueItem.faixa), selectinload(models.QueueItem.whatsapp_number))
    query = no_periodo(query, models.QueueItem.sent_at, de, ate)
    query = filtros_coluna.aplicar(query, COLUNAS_ENVIOS, filtros)

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
        query = query.order_by(_ordenado(expr), models.QueueItem.id)
    elif sort_by == "telefone":
        query = query.order_by(_ordenado(models.WhatsappNumber.display_phone_number), models.QueueItem.id)
    elif sort_by == "valor":
        query = query.order_by(_ordenado(valor_numerico()).nulls_last(), models.QueueItem.id)
    elif sort_by in ("codigo_cliente", "nome", "celular"):
        query = query.order_by(_ordenado(getattr(models.QueueItem, sort_by)), models.QueueItem.id)
    elif sort_by == "loja":
        query = query.order_by(_ordenado(models.QueueItem.lojas), models.QueueItem.id)
    elif sort_by == "enviado_em":
        query = query.order_by(_ordenado(models.QueueItem.sent_at), models.QueueItem.id)
    else:
        query = query.order_by(models.QueueItem.sent_at.desc())
    return query


def valores_envios(db: Session, de, ate, filtros: dict | None, coluna: str, busca: str | None):
    """Valores distintos de uma coluna do relatório de envios (lista do filtro da coluna)."""
    if coluna == "celular" and busca:
        busca = re.sub(r"\D", "", busca)  # a tela mostra "+55 (63) 99123-4567"; o banco guarda só os dígitos
    return filtros_coluna.valores_distintos(
        envios_realizados(db, de, ate, carregar=False), COLUNAS_ENVIOS, filtros, coluna, busca
    )

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


# Faixa: escolher uma faixa de atraso traz também as campanhas feitas a clientes que estavam
# nela, como a linha da faixa no "Por faixa" do Dashboard (a contagem do card bate com o relatório)
COLUNAS_ENVIOS = {
    "codigo_cliente": Coluna(models.QueueItem.codigo_cliente),
    "faixa": Coluna(models.Faixa.name, tambem=models.QueueItem.faixa_atraso),
    "nome": Coluna(models.QueueItem.nome),
    "loja": Coluna(models.QueueItem.lojas, "multi"),
    "valor": Coluna(valor_numerico(), "numero"),
    "celular": Coluna(models.QueueItem.celular),
    "telefone": Coluna(models.WhatsappNumber.display_phone_number),
}


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


def _base_fila(db: Session, status_fila: tuple[models.QueueStatus, ...], de, ate, carregar: bool):
    """Itens da fila nos status e período dados, com o mapa das colunas filtráveis."""
    ultimo = ultimo_erro()
    # erro de upload/extração não passa por log_erros: vale a entrada na fila
    quando = func.coalesce(ultimo.c.quando, models.QueueItem.created_at)
    query = (
        db.query(models.QueueItem, models.Faixa.name, quando)
        .select_from(models.QueueItem)  # a lista de valores troca as colunas e os joins partem sempre da fila
        .join(models.Faixa, models.Faixa.id == models.QueueItem.faixa_id)
        .outerjoin(ultimo, ultimo.c.queue_item_id == models.QueueItem.id)
        .filter(models.QueueItem.status.in_(status_fila))
    )
    if carregar:
        query = query.options(contains_eager(models.QueueItem.faixa))  # tipo da faixa sem consulta por item
    query = no_periodo(query, models.QueueItem.created_at, de, ate)
    eh_campanha = models.Faixa.tipo != models.TIPO_REGUA
    colunas = {
        "codigo_cliente": Coluna(models.QueueItem.codigo_cliente),
        "nome": Coluna(models.QueueItem.nome),
        "faixa": Coluna(case((eh_campanha, models.QueueItem.faixa_atraso), else_=models.Faixa.name)),
        "campanha": Coluna(case((eh_campanha, func.regexp_replace(models.Faixa.name, "^Campanha: ", "")), else_=None)),
        "valor": Coluna(valor_numerico(), "numero"),
        "telefone": Coluna(models.QueueItem.celular),
        "entrou_em": Coluna(models.QueueItem.created_at, "data"),
        "quando": Coluna(quando, "data"),
        "mensagem": Coluna(func.coalesce(func.nullif(models.QueueItem.error_message, ""), "Erro sem detalhe")),
        "loja": Coluna(models.QueueItem.lojas, "multi"),
    }
    return query, quando, colunas


def valores_fila(db: Session, status_fila, de, ate, filtros: dict | None, coluna: str, busca: str | None):
    """Valores distintos de uma coluna dos relatórios de pendentes/erros (lista do filtro da coluna)."""
    query, _quando, colunas = _base_fila(db, status_fila, de, ate, carregar=False)
    return filtros_coluna.valores_distintos(query, colunas, filtros, coluna, busca)


def itens_da_fila(
    db: Session,
    status_fila: tuple[models.QueueStatus, ...],
    de: date | None,
    ate: date | None,
    sort_by: str | None = None,
    sort_dir: str = "asc",
    filtros: dict | None = None,
):
    query, quando, colunas = _base_fila(db, status_fila, de, ate, carregar=True)
    query = filtros_coluna.aplicar(query, colunas, filtros)

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
    ordenaveis = {
        "codigo_cliente": models.QueueItem.codigo_cliente,
        "nome": models.QueueItem.nome,
        "valor": valor_numerico(),
        "telefone": models.QueueItem.celular,
        "entrou_em": models.QueueItem.created_at,
        "quando": quando,
        "mensagem": models.QueueItem.error_message,
    }
    if sort_by in ordenaveis:
        return query.order_by(_ordenado(ordenaveis[sort_by]).nulls_last(), models.QueueItem.id)
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


def nome_faixa():
    """Faixa da linha de "Por faixa" do Dashboard: a de atraso do cliente
    (envio de campanha/remarketing), senão a faixa da fila. Pede o join com
    models.Faixa."""
    return func.coalesce(func.nullif(models.QueueItem.faixa_atraso, ""), models.Faixa.name)


def clientes_com_envio_no_periodo(db: Session, de: date | None, ate: date | None, campanha: str | None = None):
    """Clientes cobrados do período: quem recebeu mensagem (status sent) com
    data de envio no período, por faixa de nome_faixa(). Devolve {faixa:
    {codigo_cliente: linha}}, a linha com `mensagens` (quantas no período,
    na faixa) e os dados do primeiro envio do período na faixa (`primeiro_envio`
    em UTC, `nome`, `cpf`, `lojas`, `valor`). Base dos clientes cobrados, da
    Frequência e do "Pagaram após cobrança" do Dashboard."""

    ini, fim = limites_utc(de, ate)
    faixa = nome_faixa()
    grupo = (faixa, models.QueueItem.codigo_cliente)
    envios = (
        select(
            faixa.label("faixa"),
            models.QueueItem.codigo_cliente,
            func.count().over(partition_by=grupo).label("mensagens"),
            func.row_number().over(partition_by=grupo, order_by=models.QueueItem.sent_at).label("ordem"),
            models.QueueItem.sent_at.label("primeiro_envio"),
            models.QueueItem.nome,
            models.QueueItem.cpf,
            models.QueueItem.lojas,
            valor_numerico().label("valor"),
        )
        .select_from(models.QueueItem)
        .join(models.Faixa, models.QueueItem.faixa_id == models.Faixa.id)
        .where(
            models.QueueItem.status == models.QueueStatus.sent,
            condicao_periodo(models.QueueItem.sent_at, ini, fim),
        )
    )
    if campanha:
        envios = envios.where(filtro_campanha(db, models.QueueItem.faixa_id, campanha))
    envios = envios.subquery()
    por_faixa: dict[str, dict] = {}
    for linha in db.execute(select(envios).where(envios.c.ordem == 1)):
        por_faixa.setdefault(linha.faixa, {})[linha.codigo_cliente] = linha
    return por_faixa


def envios_por_dia(db: Session, de: date | None, ate: date | None) -> dict[tuple[date, str], int]:
    """Mensagens enviadas (sent) com data de envio no período, por dia de
    Brasília e faixa de nome_faixa(): base do rateio do custo do WhatsApp
    (services/custo_whatsapp.custo_por_envio) e do custo por faixa do Dashboard."""

    ini, fim = limites_utc(de, ate)
    # sent_at é UTC ingênuo: vira timestamptz em UTC e depois o dia em Brasília
    dia = func.date(func.timezone(settings.business_timezone, func.timezone("UTC", models.QueueItem.sent_at)))
    # Agrupa por fora: no GROUP BY a expressão com parâmetros não casaria com a do SELECT
    envios = (
        select(dia.label("dia"), nome_faixa().label("faixa"))
        .select_from(models.QueueItem)
        .join(models.Faixa, models.QueueItem.faixa_id == models.Faixa.id)
        .where(
            models.QueueItem.status == models.QueueStatus.sent,
            condicao_periodo(models.QueueItem.sent_at, ini, fim),
        )
        .subquery()
    )
    linhas = db.execute(select(envios.c.dia, envios.c.faixa, func.count()).group_by(envios.c.dia, envios.c.faixa))
    return {(d, f): n for d, f, n in linhas}


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
    }


def contar_telefones_invalidos(db: Session, de: date | None, ate: date | None) -> int:
    """Números distintos no período, igual ao total do relatório. Fora de
    contar_cards porque não é soma de eventos por dia (o painel em tempo real
    soma): o mesmo número em dois dias conta uma vez."""
    ini, fim = limites_utc(de, ate)
    return um_por_telefone(
        db, db.query(models.InvalidPhoneRecord).filter(condicao_periodo(models.InvalidPhoneRecord.created_at, ini, fim))
    ).count()


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
