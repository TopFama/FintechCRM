"""Campanhas de cobrança (tela Campanhas): uma base filtrada com os mesmos
filtros da Cobrança, templates próprios e um período em que roda sozinha.

Cada campanha tem uma faixa só dela ("Campanha: …"), onde ficam número,
template e variáveis, como no remarketing. Com "Envio automático", roda todo
dia de disparo dentro do período (um dia só = início e fim iguais); sem ele,
só pelo "Colocar na fila agora". No dia,
antes do horário de início, o agendador busca a base da campanha no SETA
(só clientes em atraso) e coloca na fila quem ainda não recebeu. Com uma
planilha de clientes, a base fica restrita a eles e, se a campanha usa os
valores da planilha, valor, celular e colunas das variáveis vêm dela. Daí em diante é o fluxo
normal: blacklist, uma cobrança por cliente por dia, pausas, expiração no
fim da janela.

Quem entra na fila da campanha vira também um Lead da sua faixa de atraso
marcado com a campanha (é o que a Efetividade e a exportação de leads filtram
por campanha). Num dia de disparo seguinte ao envio da campanha, o cliente
entra também na fila da régua da faixa de atraso em que estiver naquele dia
(`enfileirar_na_regua`): no mesmo dia não dá, só vai uma cobrança por dia.
"""

import io
import logging
import re
from datetime import date, datetime, timedelta
from decimal import Decimal

from openpyxl import load_workbook
from sqlalchemy import or_
from sqlalchemy.orm import Session, selectinload

from . import cobranca_base, lojas as lojas_base, models, pausas, seta_client
from .fila_automatica import clientes_bloqueados_hoje, enfileirar_clientes, enfileirar_leads, inicio_hoje_utc
from .leads_service import gerar_leads_de_clientes
from .regras_db import carregar_regras
from .timezone import hoje_br
from .utils.phone import is_valid_phone

logger = logging.getLogger("campanhas")

PREFIXO_FAIXA = "Campanha: "
MAX_LINHAS_PLANILHA = 200_000

# Filtros de loja: viram uma lista de códigos de filial antes da consulta.
_FILTROS_LOJA = ("loja", "regional", "estado", "cluster_inad", "cluster_populacao", "cobradora")


def nome_faixa(nome: str) -> str:
    return PREFIXO_FAIXA + nome


def em_periodo(campanha: models.Campanha, hoje: date) -> bool:
    if campanha.modo == "unica":  # legado: período de um dia
        return campanha.data_inicio == hoje
    if campanha.data_inicio and hoje < campanha.data_inicio:
        return False
    if campanha.data_fim and hoje > campanha.data_fim:
        return False
    return True


def filtros_para_busca(db: Session, filtros: dict, clientes: list[str] | None) -> dict:
    """Argumentos de `cobranca_base.buscar_base` a partir dos filtros salvos
    (mesmos nomes dos parâmetros de /cobranca/clientes). Numa campanha, o
    padrão é pegar todos os dias da faixa e ignorar a matriz do WhatsApp:
    quem decide quem entra são os filtros da própria campanha."""

    def lista(chave: str) -> list[str] | None:
        return list(filtros.get(chave) or []) or None

    def data(chave: str) -> date | None:
        valor = filtros.get(chave)
        return date.fromisoformat(valor) if valor else None

    def decimal(chave: str) -> Decimal | None:
        valor = filtros.get(chave)
        return Decimal(str(valor)) if valor not in (None, "") else None

    codigos_loja = lojas_base.combinar_lojas(
        db,
        lista("loja"),
        regional=lista("regional"),
        estado=lista("estado"),
        cluster_inad=lista("cluster_inad"),
        cluster_populacao=lista("cluster_populacao"),
        cobradora=lista("cobradora"),
    )
    return dict(
        apenas_primeiro_dia=bool(filtros.get("apenas_primeiro_dia", False)),
        somente_regra_whatsapp=bool(filtros.get("somente_regra_whatsapp", False)),
        faixas=lista("faixa"),
        clusters=lista("cluster"),
        faixas_compra=lista("faixa_compra"),
        lojas=codigos_loja,
        status_cliente=lista("status_cliente"),
        restricoes_spc=lista("restricao_spc"),
        vencimento_de=data("vencimento_de"),
        vencimento_ate=data("vencimento_ate"),
        valor_atraso_min=decimal("valor_atraso_min"),
        valor_atraso_max=decimal("valor_atraso_max"),
        valor_atraso_com_juros=bool(filtros.get("valor_atraso_com_juros", False)),
        codigos=list(clientes) if clientes else None,
    )


def ja_receberam(db: Session, campanha: models.Campanha, agora: datetime | None = None) -> set[str]:
    """Quem já está na fila ou recebeu desta campanha (em qualquer data, ou
    dentro do prazo de recontato, quando a recorrente tem um). Erro de envio
    só conta no próprio dia: o cliente tenta de novo no próximo."""

    q = db.query(models.QueueItem.codigo_cliente).filter(
        models.QueueItem.faixa_id == campanha.faixa_id,
        or_(models.QueueItem.status != models.QueueStatus.error, models.QueueItem.created_at >= inicio_hoje_utc()),
    )
    if campanha.recontato_dias:
        agora = agora or datetime.utcnow()
        q = q.filter(models.QueueItem.created_at >= agora - timedelta(days=campanha.recontato_dias))
    return {codigo for (codigo,) in q}


def selecionar(db: Session, campanha: models.Campanha) -> dict:
    """{"status": "ready", "clientes": [...], "total_base": n} com quem entraria
    hoje (base filtrada menos quem já recebeu da campanha), ou
    {"status": "processing"} enquanto o SETA calcula a base em segundo plano."""

    job = cobranca_base.buscar_base(db, **filtros_para_busca(db, campanha.filtros or {}, campanha.clientes))
    if job["status"] != "ready":
        return {"status": "processing"}
    # Só quem está em atraso: fica de fora o lembrete (parcela ainda a vencer).
    base = [c for c in job["data"] if c["dias_atraso"] >= 1]
    fora = ja_receberam(db, campanha)
    return {"status": "ready", "total_base": len(base), "clientes": [c for c in base if c["codigo"] not in fora]}


_COLUNAS_VALOR = ("VALOR", "VALOR EM ATRASO", "VALOR A COBRAR", "VALOR ATRASO", "VALOR EM ABERTO", "VALOR DIVIDA")
_COLUNAS_CELULAR = ("CELULAR", "TELEFONE", "FONE", "WHATSAPP")


def _coluna_da_linha(linha: dict[str, str], nomes: tuple[str, ...]) -> str | None:
    for coluna, valor in linha.items():
        if lojas_base._normalizar(coluna) in nomes and str(valor).strip():
            return str(valor).strip()
    return None


def _decimal_planilha(texto: str) -> Decimal | None:
    texto = texto.replace("R$", "").strip()
    if "," in texto:
        texto = texto.replace(".", "").replace(",", ".")
    try:
        return Decimal(texto)
    except ArithmeticError:
        return None


def com_valores_da_planilha(cliente: dict, campanha: models.Campanha) -> dict:
    """Cliente do SETA com valor e celular trocados pelos da linha da
    planilha (quando a planilha tem essas colunas preenchidas)."""

    linha = (campanha.planilha_linhas or {}).get(cliente["codigo"])
    if not linha:
        return cliente
    novo = dict(cliente)
    valor = _coluna_da_linha(linha, _COLUNAS_VALOR)
    if valor is not None and _decimal_planilha(valor) is not None:
        novo["valor_cobrar"] = _decimal_planilha(valor)
        novo["valor_atraso"] = novo["valor_cobrar"]
    celular = _coluna_da_linha(linha, _COLUNAS_CELULAR)
    if celular and is_valid_phone(celular):
        novo["celular"] = celular
        novo["celular_original"] = celular
    return novo


def _carregar_faixa(db: Session, campanha: models.Campanha) -> models.Faixa:
    return (
        db.query(models.Faixa)
        .options(
            selectinload(models.Faixa.envios).selectinload(models.FaixaEnvio.template).selectinload(
                models.Template.variables
            ),
            selectinload(models.Faixa.variable_mappings),
        )
        .filter(models.Faixa.id == campanha.faixa_id)
        .one()
    )


def executar(db: Session, campanha: models.Campanha, *, created_by: str | None = None) -> dict:
    """Busca a base e coloca na fila. Devolve {"status": "processing"} se a
    base ainda está sendo calculada (quem chamou tenta de novo depois) ou o
    resumo {"encontrados", "na_fila"}, que fica gravado na campanha."""

    selecao = selecionar(db, campanha)
    if selecao["status"] != "ready":
        return selecao
    clientes = selecao["clientes"]
    extras = None
    if campanha.fonte_valores == "planilha":
        clientes = [com_valores_da_planilha(c, campanha) for c in clientes]
        extras = campanha.planilha_linhas or {}
    na_fila = 0
    if clientes:
        juros = carregar_regras(db).juros
        parcelas = seta_client.buscar_parcelas_cobranca([c["codigo"] for c in clientes], juros=juros)
        enfileirados: list[dict] = []
        na_fila = enfileirar_clientes(
            db,
            _carregar_faixa(db, campanha),
            clientes,
            bloqueados=clientes_bloqueados_hoje(db),
            juros=juros,
            parcelas=parcelas,
            origem="na campanha",
            colunas_extras=extras,
            enfileirados=enfileirados,
        )
        db.flush()
        # Lead na faixa de atraso do cliente, marcado com a campanha: o envio
        # o marca como cobrado (Efetividade/exportação) e leva o cliente à régua.
        gerar_leads_de_clientes(
            db, enfileirados, created_by=created_by, campanha_id=campanha.id, parcelas=parcelas
        )
    resumo = {"status": "ready", "encontrados": len(clientes), "na_fila": na_fila}
    campanha.ultima_execucao = datetime.utcnow()
    campanha.parada_em = None
    campanha.ultimo_resultado = {"encontrados": len(clientes), "na_fila": na_fila}
    db.commit()
    logger.info("Campanha '%s': %s", campanha.nome, resumo)
    return resumo


def enfileirar_na_regua(db: Session) -> dict:
    """Quem recebeu mensagem de campanha em dia anterior entra na fila da
    régua da faixa de atraso em que está hoje (base do SETA recalculada: quem
    pagou ou saiu do atraso não entra). Cliente bloqueado hoje (já na fila ou
    cobrado em outra faixa) tenta de novo no próximo dia de disparo.
    Devolve {"status": "processing"} enquanto a base calcula, ou o resumo."""

    leads = (
        db.query(models.Lead)
        .filter(
            models.Lead.campanha_id != "",
            models.Lead.status == "cobrado",
            models.Lead.regua_em.is_(None),
            models.Lead.cobrado_em < inicio_hoje_utc(),
        )
        .all()
    )
    if not leads:
        return {"status": "ready", "clientes": 0, "na_fila": 0}
    codigos = sorted({l.codigo_cliente for l in leads})
    job = cobranca_base.buscar_base(db, apenas_primeiro_dia=False, somente_regra_whatsapp=False, codigos=codigos)
    if job["status"] != "ready":
        return {"status": "processing"}
    base = [c for c in job["data"] if c["dias_atraso"] >= 1]
    na_fila = 0
    if base:
        gerar_leads_de_clientes(db, base, created_by=None)
        na_fila = enfileirar_leads(db, base)

    faixa_por_id = {f.id: f.name for f in db.query(models.Faixa.id, models.Faixa.name)}
    na_regua_hoje = {
        (codigo, faixa_por_id.get(faixa_id))
        for codigo, faixa_id in db.query(models.QueueItem.codigo_cliente, models.QueueItem.faixa_id).filter(
            models.QueueItem.codigo_cliente.in_(codigos), models.QueueItem.created_at >= inicio_hoje_utc()
        )
    }
    com_envio = {
        f.name
        for f in db.query(models.Faixa).filter(models.Faixa.active.is_(True), models.Faixa.tipo == models.TIPO_REGUA)
        if any(e.active and e.template_id for e in f.envios)
    }
    faixa_hoje = {c["codigo"]: c["faixa"] for c in base}
    agora = datetime.utcnow()
    for lead in leads:
        faixa = faixa_hoje.get(lead.codigo_cliente)
        # Resolvido: saiu da base (pagou, blacklist…), a faixa não tem régua
        # ligada ou o cliente já está na fila da régua hoje.
        if faixa is None or faixa not in com_envio or (lead.codigo_cliente, faixa) in na_regua_hoje:
            lead.regua_em = agora
    db.commit()
    resumo = {"status": "ready", "clientes": len(codigos), "na_fila": na_fila}
    logger.info("Régua de quem recebeu campanha: %s", resumo)
    return resumo


def campanhas_para_hoje(db: Session) -> list[models.Campanha]:
    """Com envio automático, não arquivadas nem pausadas, dentro do período,
    ainda não rodadas hoje e com algum número + template ativo (ligar antes de
    atribuir não perde o dia)."""

    hoje = hoje_br()
    pausadas = {p.valor for p in pausas.ativas(db) if p.escopo == "faixa"}
    return [
        c
        for c in db.query(models.Campanha).filter(
            models.Campanha.ativa.is_(True), models.Campanha.arquivada_em.is_(None)
        )
        if em_periodo(c, hoje)
        and c.ultima_execucao_dia != hoje
        and c.faixa_id not in pausadas
        and any(e.active for e in c.faixa.envios)
    ]


# --- Leitura de planilhas -----------------------------------------------------


def _linhas_xlsx(filename: str, content: bytes) -> list[list[str]]:
    if not filename.lower().endswith(".xlsx"):
        raise ValueError("Envie um arquivo .xlsx")
    try:
        wb = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001 - arquivo corrompido ou não é xlsx de verdade
        raise ValueError("Não consegui abrir a planilha; confira se é um .xlsx válido") from exc
    linhas = []
    for linha in wb.active.iter_rows(values_only=True):
        if len(linhas) > MAX_LINHAS_PLANILHA:
            raise ValueError(f"A planilha passa de {MAX_LINHAS_PLANILHA} linhas")
        linhas.append(["" if c is None else _texto_celula(c) for c in linha])
    return [l for l in linhas if any(c.strip() for c in l)]


def _texto_celula(valor) -> str:
    # Código numérico lido como 6.0 volta a ser "6"
    if isinstance(valor, float) and valor.is_integer():
        return str(int(valor))
    return str(valor).strip()


def _achar_coluna(linhas: list[list[str]], nomes: tuple[str, ...]) -> tuple[int, int] | None:
    """(linha do cabeçalho, coluna) da primeira coluna cujo título está em `nomes`, nas 10 primeiras linhas."""

    for i, linha in enumerate(linhas[:10]):
        normalizados = [lojas_base._normalizar(c) for c in linha]
        for nome in nomes:
            if nome in normalizados:
                return i, normalizados.index(nome)
    return None


_COLUNAS_LOJA = ("FILIAL", "LOJA", "COD LOJA", "CODIGO LOJA", "COD FILIAL", "CODIGO FILIAL", "EMPRESA", "CODIGO", "COD")


def ler_lojas(db: Session, filename: str, content: bytes) -> dict:
    """Lojas de um relatório .xlsx pela coluna de código da loja (FILIAL,
    LOJA, CÓDIGO…; sem cabeçalho conhecido, a primeira coluna). "6" vale
    "06". Devolve as filiais que existem na base de lojas e os códigos que
    não casaram com nenhuma."""

    linhas = _linhas_xlsx(filename, content)
    achou = _achar_coluna(linhas, _COLUNAS_LOJA)
    cab, col = achou if achou else (-1, 0)
    existentes = {l["filial"] for l in lojas_base.listar_lojas(db)}

    encontradas: list[str] = []
    nao_encontradas: list[str] = []
    for linha in linhas[cab + 1 :]:
        valor = linha[col].strip() if col < len(linha) else ""
        if not valor:
            continue
        filial = lojas_base.codigo_filial(valor)
        if filial not in existentes:
            if valor not in nao_encontradas:
                nao_encontradas.append(valor)
        elif filial not in encontradas:
            encontradas.append(filial)
    return {"lojas": encontradas, "nao_encontradas": nao_encontradas}


_COLUNAS_CODIGO = ("CODIGO", "COD", "CODIGO SETA", "COD SETA", "CODIGO CLIENTE", "COD CLIENTE", "PESSOA")
_COLUNAS_CPF = ("CPF", "CPF/CNPJ", "CPFCNPJ", "CPF CNPJ", "DOCUMENTO")


def ler_clientes(filename: str, content: bytes) -> dict:
    """Clientes de uma planilha .xlsx para restringir a campanha: usa a
    coluna de código SETA (Codigo, Código SETA…) ou, sem ela, a de CPF, que
    vira código numa consulta só ao SETA. Devolve os códigos (8 dígitos) e
    quantas linhas não deram para identificar."""

    linhas = _linhas_xlsx(filename, content)
    achou = _achar_coluna(linhas, _COLUNAS_CODIGO)
    por_cpf = False
    if achou is None:
        achou = _achar_coluna(linhas, _COLUNAS_CPF)
        por_cpf = True
    if achou is None:
        raise ValueError("Não achei a coluna de código do cliente (Codigo) nem a de CPF na planilha")
    cab, col = achou
    cabecalho = [c.strip() for c in linhas[cab]]
    colunas = [c for c in cabecalho if c]
    # (identificador só dígitos, linha como {coluna: valor})
    corpo = [
        (re.sub(r"\D", "", l[col]) if col < len(l) else "", {c: l[i] for i, c in enumerate(cabecalho) if c and i < len(l)})
        for l in linhas[cab + 1 :]
    ]
    if por_cpf:
        mapa = seta_client.codigos_por_cpf([v.zfill(11) for v, _ in corpo if v and len(v) <= 11])
        chave = lambda v: mapa.get(v.zfill(11)) if v and len(v) <= 11 else None
    else:
        chave = lambda v: v.zfill(8) if v and len(v) <= 8 else None

    por_codigo: dict[str, dict[str, str]] = {}
    ignoradas = 0
    for valor, linha in corpo:
        codigo = chave(valor)
        if codigo is None:
            ignoradas += 1
        elif codigo not in por_codigo:  # cliente repetido: vale a primeira linha
            por_codigo[codigo] = linha
    return {
        "clientes": list(por_codigo),
        "linhas": por_codigo,
        "colunas": colunas,
        "ignoradas": ignoradas,
        "coluna": "CPF" if por_cpf else "Código",
    }
