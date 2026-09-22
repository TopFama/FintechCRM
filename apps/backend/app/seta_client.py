"""Único ponto de integração com o SETA (ERP da TopFama).

O SETA é um Postgres externo de produção que este sistema só **lê**: a conexão
abre em modo somente leitura e com teto de tempo por consulta, então nem um
bug nosso consegue gravar no ERP nem uma query pesada segurar o banco dele.
Qualquer consulta nova ao SETA entra aqui, nunca direto num router.

Convenções do schema do SETA que o restante do código precisa conhecer:
- os campos são `character(N)`, preenchidos com espaços — sempre `trim` na saída;
- `pessoas.faturamento` é o campo "salário" no sistema (é ele que gera a
  disponibilidade de limite) e é exposto como `salario`, nunca como faturamento;
- datas de `pessoas` vêm corrompidas em parte dos cadastros (ano 0001 BC,
  9999) e derrubam o driver, então são saneadas no SQL.
"""

import logging
import time
from functools import lru_cache

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import SQLAlchemyError

from .config import settings

logger = logging.getLogger(__name__)


class SetaIndisponivel(Exception):
    """SETA não configurado ou inalcançável. A mensagem é segura para o usuário
    (não carrega host, usuário nem senha)."""


def is_configured() -> bool:
    return bool(settings.seta_db_host and settings.seta_db_user and settings.seta_db_password)


@lru_cache(maxsize=1)
def _engine() -> Engine:
    url = URL.create(
        "postgresql+psycopg",
        username=settings.seta_db_user,
        password=settings.seta_db_password,
        host=settings.seta_db_host,
        port=settings.seta_db_port,
        database=settings.seta_db_name,
    )
    timeout_ms = settings.seta_db_statement_timeout_seconds * 1000
    return create_engine(
        url,
        pool_size=3,
        max_overflow=2,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={
            "connect_timeout": settings.seta_db_connect_timeout_seconds,
            "options": f"-c default_transaction_read_only=on -c statement_timeout={timeout_ms}",
        },
    )


def engine_ou_erro() -> Engine:
    if not is_configured():
        raise SetaIndisponivel(
            "Integração com o SETA não configurada (defina SETA_DB_HOST, SETA_DB_USER e SETA_DB_PASSWORD)"
        )
    return _engine()


def check_connection() -> dict:
    """Testa a conexão e confirma que a sessão está mesmo somente leitura."""

    engine = engine_ou_erro()
    inicio = time.perf_counter()
    try:
        with engine.connect() as conn:
            row = conn.execute(
                text(
                    "select current_database(), current_user, version(),"
                    " current_setting('default_transaction_read_only')"
                )
            ).one()
    except SQLAlchemyError as exc:
        logger.warning("Falha ao conectar no SETA: %s", exc.__class__.__name__)
        raise SetaIndisponivel(f"Não foi possível conectar ao SETA ({exc.__class__.__name__})") from exc
    return {
        "banco": row[0],
        "usuario": row[1],
        "versao": row[2],
        "somente_leitura": row[3] == "on",
        "latencia_ms": round((time.perf_counter() - inicio) * 1000),
    }


# --- Base de cobrança --------------------------------------------------------

STATUS_CLIENTE = {"E": "especial", "A": "ativo", "B": "bloqueado"}

# Portadores (cobradoras) dos títulos no SETA.
PORTADOR_TOPFAMA = "001"
PORTADOR_SYSCO = "114"
PORTADOR_MJ = "216"

# Único título de seguro no SETA (conferido na base: as outras descrições que
# contêm "seg" são IDs aleatórios de baixa de crédito). Entra na cobrança, mas
# não conta para o cluster de valor pago.
DESCRICAO_SEGURO = "SEGURO TOPFAMA"

# Condição de pagamento "A PRAZO ATIVO": crediário (condicoes.tipo = '4'), mas
# não conta como compra na faixa de compra.
CONDICAO_IGNORADA = "130"

# Datas de `pessoas` fora da janela 1900..hoje são lixo de cadastro (0001 BC,
# 9999, futuro) e viram NULL.
_SQL_BASE_COBRANCA = r"""
WITH abertos AS (
    SELECT ft.pessoa,
           count(*)                                     AS qtd_titulos,
           sum(ft.valor)                                AS valor_em_aberto,
           min(ft.vencimento)                           AS vencimento_mais_antigo,
           string_agg(DISTINCT trim(ft.empresa), ',')   AS lojas,
           string_agg(DISTINCT trim(ft.portador), ',')  AS portadores
      FROM financeiro_titulos ft
     WHERE ft.rp = 'R'
       AND ft.status = 'A'
       AND ft.tipo IN ('4', '5')
       AND ft.valor > 0
       {filtro_loja_titulo}
       {filtro_portador}
     GROUP BY ft.pessoa
),
candidatos AS (
    SELECT a.*, current_date - a.vencimento_mais_antigo AS dias_atraso
      FROM abertos a
     WHERE {filtro_dias}
),
base AS (
    SELECT c.*,
           trim(p.codigo)    AS codigo,
           trim(p.nome)      AS nome,
           trim(p.telefone2) AS telefone2,
           trim(p.telefone1) AS telefone1,
           trim(p.telefone3) AS telefone3,
           trim(p.cpfcnpj)   AS cpfcnpj,
           p.status          AS status,
           trim(p.empresa)   AS loja_cadastro,
           p.faturamento     AS salario,
           p.credito         AS limite_rotativo,
           CASE WHEN p.nascimento BETWEEN DATE '1900-01-01' AND current_date
                THEN p.nascimento END AS nascimento,
           CASE WHEN p.cadastro BETWEEN DATE '1900-01-01' AND current_date
                THEN p.cadastro END   AS cadastro
      FROM candidatos c
      JOIN pessoas p ON p.codigo = c.pessoa
     WHERE p.cliente
       AND p.status IN ('E', 'A', 'B')
       AND p.codigo <> :codigo_ignorado
       AND trim(p.codigo) <> ALL(CAST(:bl_codigos AS text[]))
       AND regexp_replace(p.cpfcnpj, '\D', '', 'g') <> ALL(CAST(:bl_cpfs AS text[]))
       {filtro_status}
),
pagos AS (
    SELECT ft.pessoa, sum(ft.valor) AS valor_pago
      FROM financeiro_titulos ft
      JOIN base b ON b.pessoa = ft.pessoa
     WHERE ft.rp = 'R'
       AND ft.status = 'B'
       AND ft.tipo IN ('4', '5')
       AND ft.valor > 0
       AND ft.auxiliar LIKE 'VE%'
       AND trim(ft.descricao) <> :descricao_seguro
     GROUP BY ft.pessoa
),
compras AS (
    SELECT v.cliente AS pessoa, count(*) AS qtd_compras, max(v.data) AS ultima_compra
      FROM vendas v
      JOIN condicoes c ON c.codigo = v.condicoes
      JOIN base b ON b.pessoa = v.cliente
     WHERE v.status = 'S'
       AND c.tipo = '4'
       AND c.codigo <> :condicao_ignorada
       AND EXISTS (
           SELECT 1
             FROM financeiro_titulos ft
            WHERE ft.auxiliar = CAST('VE' || v.codigo AS char(10))
              AND ft.rp = 'R'
              AND ft.tipo IN ('4', '5')
       )
     GROUP BY v.cliente
)
SELECT b.*,
       COALESCE(g.valor_pago, 0)  AS valor_pago,
       COALESCE(k.qtd_compras, 0) AS qtd_compras,
       k.ultima_compra
  FROM base b
  LEFT JOIN pagos g ON g.pessoa = b.pessoa
  LEFT JOIN compras k ON k.pessoa = b.pessoa
"""


_DIAS_ATRASO = "(current_date - a.vencimento_mais_antigo)"


def _sql_dias(dias_exatos: list[int] | None, faixas: list[tuple[int, int | None]]) -> str:
    """Predicado sobre os dias de atraso. Só recebe inteiros vindos de
    `cobranca_regras` (nunca texto do usuário), por isso vai direto no SQL."""

    if dias_exatos is not None:
        if not dias_exatos:
            return "false"
        return f"{_DIAS_ATRASO} IN (%s)" % ", ".join(str(int(d)) for d in dias_exatos)
    if not faixas:
        return "false"
    partes = []
    for dmin, dmax in faixas:
        partes.append(
            f"{_DIAS_ATRASO} >= {int(dmin)}" + (f" AND {_DIAS_ATRASO} <= {int(dmax)}" if dmax is not None else "")
        )
    return "(" + ") OR (".join(partes) + ")"


def buscar_base_cobranca(
    *,
    faixas: list[tuple[int, int | None]],
    dias_exatos: list[int] | None = None,
    lojas: list[str] | None = None,
    portadores: list[str] | None = None,
    status_cliente: list[str] | None = None,
    bloqueados_codigos: list[str] | None = None,
    bloqueados_cpfs: list[str] | None = None,
) -> list[dict]:
    """Clientes (`pessoas.cliente`, status Especial/Ativo/Bloqueado) com
    parcela de recebimento em aberto (`rp='R'`, tipo 4/5, `valor > 0`), já com
    o valor pago em vendas para o cluster. Devolve linhas cruas: classificar em
    cluster/faixa e aplicar a matriz WhatsApp é com `cobranca_regras`.

    - `dias_atraso` = hoje − vencimento da parcela aberta mais antiga (ela
      define a faixa do cliente). A parcela de seguro entra normalmente.
    - `faixas` (intervalos de dias) e `dias_exatos` (só o primeiro dia de cada
      faixa) restringem quem volta; `dias_exatos` tem precedência.
    - `lojas` (`ft.empresa`) e `portadores` restringem **quais parcelas** contam:
      dias, valor e quantidade são calculados só sobre elas.
    - `valor_pago` soma parcelas pagas de venda (auxiliar `VE…`), sem seguro.
    - `qtd_compras` conta vendas finalizadas (`status = 'S'`) de condição de
      crediário (tipo 4, menos a 130), só se a venda tem parcela `VE`+código
      de tipo 4/5 — é o que confirma que foi crediário de verdade.
    - blacklist e o código ignorado ficam de fora, com ou sem atraso."""

    from .cobranca_regras import CODIGO_CLIENTE_IGNORADO

    engine = engine_ou_erro()
    params: dict = {
        "codigo_ignorado": CODIGO_CLIENTE_IGNORADO,
        "bl_codigos": bloqueados_codigos or [],
        "bl_cpfs": bloqueados_cpfs or [],
        "descricao_seguro": DESCRICAO_SEGURO,
        "condicao_ignorada": CONDICAO_IGNORADA,
    }
    expanding: list[str] = []
    filtro_loja = filtro_portador = filtro_status = ""
    if lojas:
        filtro_loja = "AND trim(ft.empresa) IN :lojas"
        params["lojas"] = lojas
        expanding.append("lojas")
    if portadores:
        filtro_portador = "AND trim(ft.portador) IN :portadores"
        params["portadores"] = portadores
        expanding.append("portadores")
    if status_cliente:
        filtro_status = "AND p.status IN :status_cliente"
        params["status_cliente"] = status_cliente
        expanding.append("status_cliente")

    stmt = text(
        _SQL_BASE_COBRANCA.format(
            filtro_loja_titulo=filtro_loja,
            filtro_portador=filtro_portador,
            filtro_status=filtro_status,
            filtro_dias=_sql_dias(dias_exatos, faixas),
        )
    ).bindparams(*(bindparam(nome, expanding=True) for nome in expanding))

    try:
        with engine.connect() as conn:
            rows = conn.execute(stmt, params).mappings().all()
    except SQLAlchemyError as exc:
        logger.warning("Falha ao consultar o SETA: %s", exc.__class__.__name__)
        raise SetaIndisponivel(f"Falha ao consultar o SETA ({exc.__class__.__name__})") from exc
    return [dict(r) for r in rows]


def buscar_spc(codigos: list[str]) -> dict[str, str]:
    """Texto bruto da consulta SPC de cada cliente. É pesado (~1 KB por cliente),
    então só se pede para quem vai aparecer na tela ou virar lead."""

    if not codigos:
        return {}
    engine = engine_ou_erro()
    stmt = text(
        "SELECT trim(codigo) AS codigo, scpcresultado FROM pessoas WHERE trim(codigo) IN :codigos"
    ).bindparams(bindparam("codigos", expanding=True))
    try:
        with engine.connect() as conn:
            return {r.codigo: r.scpcresultado for r in conn.execute(stmt, {"codigos": codigos})}
    except SQLAlchemyError as exc:
        logger.warning("Falha ao consultar o SETA: %s", exc.__class__.__name__)
        raise SetaIndisponivel(f"Falha ao consultar o SETA ({exc.__class__.__name__})") from exc
