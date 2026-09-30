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
from datetime import date, timedelta
from functools import lru_cache

from sqlalchemy import bindparam, create_engine, text
from sqlalchemy.engine import URL, Engine
from sqlalchemy.exc import SQLAlchemyError

from .cobranca_regras import PARAMETROS_JUROS_PADRAO, ParametrosJuros
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
            # TimeZone: current_date das consultas (dias de atraso, juros, primeiro
            # dia da faixa) no fuso de Brasília, seja qual for o do servidor do ERP
            "options": (
                f"-c default_transaction_read_only=on -c statement_timeout={timeout_ms}"
                " -c TimeZone=America/Sao_Paulo"
            ),
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
# Vendas migradas do ERP antigo: condição 100 ("IMPORTACAO", tipo 1) com
# "CREDIARIO" na obs; contam como compra no crediário (sem título VE).
CONDICAO_MIGRADA = "100"

# Datas de `pessoas` fora da janela 1900..hoje são lixo de cadastro (0001 BC,
# 9999, futuro) e viram NULL.
_SQL_BASE_COBRANCA = r"""
WITH {cte_alvo}parcelas AS (
    SELECT ft.pessoa,
           ft.valor,
           ft.vencimento,
           trim(ft.empresa)  AS empresa,
           trim(ft.portador) AS portador,
           min(ft.vencimento) OVER (PARTITION BY ft.pessoa) AS vencimento_min
      FROM financeiro_titulos ft
     WHERE ft.rp = 'R'
       AND ft.status = 'A'
       AND ft.tipo IN ('4', '5')
       AND ft.valor > 0
       {filtro_loja_titulo}
       {filtro_portador}
       {filtro_alvo}
),
abertos AS (
    SELECT pessoa,
           count(*)                       AS qtd_titulos,
           sum(valor)                     AS valor_em_aberto,
           min(vencimento)                AS vencimento_mais_antigo,
           string_agg(DISTINCT empresa, ',')  AS lojas,
           string_agg(DISTINCT portador, ',') AS portadores,
           count(*) FILTER (WHERE vencimento <= GREATEST(current_date, vencimento_min))
                                          AS qtd_parcelas_cobranca,
           -- arredonda parcela a parcela: o total cobrado é a soma exata das
           -- parcelas guardadas no lead (buscar_parcelas_cobranca)
           sum(
               CASE WHEN vencimento <= GREATEST(current_date, vencimento_min) THEN
                   round(CASE WHEN current_date - vencimento > :dias_min_juros
                              THEN valor + valor * :juros_dia * (current_date - vencimento) + valor * :multa
                              ELSE valor END, 2)
               END
           )                              AS valor_cobrar,
           -- só as já vencidas (antes de hoje): filtro "valor em atraso" da
           -- Cobrança e das Campanhas, sem e com multa/juros
           COALESCE(sum(valor) FILTER (WHERE vencimento < current_date), 0)
                                          AS valor_atraso_original,
           COALESCE(sum(
               round(CASE WHEN current_date - vencimento > :dias_min_juros
                          THEN valor + valor * :juros_dia * (current_date - vencimento) + valor * :multa
                          ELSE valor END, 2)
           ) FILTER (WHERE vencimento < current_date), 0)
                                          AS valor_atraso_juros
      FROM parcelas
     GROUP BY pessoa
),
candidatos AS (
    SELECT a.*, current_date - a.vencimento_mais_antigo AS dias_atraso
      FROM abertos a
     WHERE {filtro_dias}
       {filtro_vencimento}
),
base AS (
    SELECT c.*,
           trim(p.codigo)    AS codigo,
           trim(p.nome)      AS nome,
           trim(p.telefone2) AS telefone2,
           trim(p.telefone1) AS telefone1,
           trim(p.telefone3) AS telefone3,
           trim(p.telefone4) AS telefone4,
           trim(p.cpfcnpj)   AS cpfcnpj,
           p.status          AS status,
           trim(p.empresa)   AS loja_cadastro,
           p.faturamento     AS salario,
           p.credito         AS limite_rotativo,
           CASE WHEN p.nascimento BETWEEN DATE '1900-01-01' AND current_date
                THEN p.nascimento END AS nascimento,
           CASE WHEN p.cadastro BETWEEN DATE '1900-01-01' AND current_date
                THEN p.cadastro END   AS cadastro,
           CASE WHEN p.scpcresultado ~* 'RESTRI\S*\s*:\s*SIM' THEN 'sim'
                WHEN p.scpcresultado ~* 'RESTRI\S*\s*:\s*N'   THEN 'nao'
                ELSE 'indeterminado' END AS spc_restricao
      FROM candidatos c
      JOIN pessoas p ON p.codigo = c.pessoa
     WHERE p.cliente
       AND p.funcionario = false
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
       --AND COALESCE(ft.auxiliar, '') NOT LIKE 'RE%' /*Valores de renegociação deve contar como valor pago*/
       AND trim(ft.descricao) <> :descricao_seguro
     GROUP BY ft.pessoa
)
-- Compras (faixa de compra) não vêm daqui: ficam na cópia local do CRM
-- (services/compras_seta.py), atualizada de madrugada.
SELECT b.*,
       COALESCE(g.valor_pago, 0)  AS valor_pago
  FROM base b
  LEFT JOIN pagos g ON g.pessoa = b.pessoa
"""


# Compra no crediário: venda finalizada (status S) de condição tipo 4 (menos a
# 130) ou venda migrada do ERP antigo (condição 100 com CREDIARIO na obs).
_SQL_VENDA_CREDIARIO = """
    v.status = 'S'
    AND ((c.tipo = '4' AND c.codigo <> :condicao_ignorada)
         OR (v.condicoes = :condicao_migrada AND v.obs LIKE '%CREDIARIO%'))
"""
_PARAMS_VENDA = {"condicao_ignorada": CONDICAO_IGNORADA, "condicao_migrada": CONDICAO_MIGRADA}


_DIAS_ATRASO = "(current_date - a.vencimento_mais_antigo)"


def _sql_dias(dias_exatos: list[int] | None, faixas: list[tuple[int, int | None]]) -> str:
    """Predicado sobre os dias de atraso. Só recebe inteiros vindos de
    `cobranca_regras` (nunca texto do usuário), por isso vai direto no SQL."""

    if dias_exatos is not None:
        if not dias_exatos:
            return "false"
        return f"({_DIAS_ATRASO} IN (%s))" % ", ".join(str(int(d)) for d in dias_exatos)
    if not faixas:
        return "false"
    partes = []
    for dmin, dmax in faixas:
        partes.append(
            f"{_DIAS_ATRASO} >= {int(dmin)}" + (f" AND {_DIAS_ATRASO} <= {int(dmax)}" if dmax is not None else "")
        )
    # parênteses externos: o predicado vem seguido de AND (filtro de vencimento)
    return "((" + ") OR (".join(partes) + "))"


def buscar_base_cobranca(
    *,
    faixas: list[tuple[int, int | None]],
    dias_exatos: list[int] | None = None,
    lojas: list[str] | None = None,
    portadores: list[str] | None = None,
    status_cliente: list[str] | None = None,
    vencimento_de: date | None = None,
    vencimento_ate: date | None = None,
    bloqueados_codigos: list[str] | None = None,
    bloqueados_cpfs: list[str] | None = None,
    juros: ParametrosJuros = PARAMETROS_JUROS_PADRAO,
    codigos: list[str] | None = None,
) -> list[dict]:
    """Clientes (`pessoas.cliente`, status Especial/Ativo/Bloqueado) com
    parcela de recebimento em aberto (`rp='R'`, tipo 4/5, `valor > 0`), já com
    o valor pago em vendas para o cluster. Devolve linhas cruas: classificar em
    cluster/faixa e aplicar a matriz WhatsApp é com `cobranca_regras`.

    - `dias_atraso` = hoje − vencimento da parcela aberta mais antiga (ela
      define a faixa do cliente). A parcela de seguro entra normalmente.
    - `faixas` (intervalos de dias) e `dias_exatos` (só o primeiro dia de cada
      faixa) restringem quem volta; `dias_exatos` tem precedência.
    - `vencimento_de` / `vencimento_ate` filtram pelo vencimento da parcela mais
      antiga (a que define a faixa e aparece na tela).
    - `lojas` (`ft.empresa`) e `portadores` restringem **quais parcelas** contam:
      dias, valor e quantidade são calculados só sobre elas.
    - `qtd_titulos` / `valor_em_aberto` cobrem todas as parcelas abertas (RE e
      VE, inclusive as futuras) e alimentam os visuais, sem juros. Já
      `qtd_parcelas_cobranca` e `valor_cobrar` valem só para as parcelas da
      cobrança (`vencimento <= max(hoje, parcela mais antiga)`: as vencidas e,
      no lembrete, a que vence amanhã) e o valor leva multa e juros (`juros`).
    - `valor_pago` soma tudo que o cliente pagou (menos auxiliar `RE…`), sem seguro.
    - compras (faixa de compra) não vêm desta consulta: ver compras_de_clientes
      e a cópia local em services/compras_seta.py.
    - blacklist e o código ignorado ficam de fora, com ou sem atraso.
    - `codigos` restringe a esses clientes (remarketing), num CTE com VALUES
      em lotes de 1000, nunca uma consulta por cliente."""

    from .cobranca_regras import CODIGO_CLIENTE_IGNORADO

    engine = engine_ou_erro()
    params: dict = {
        "codigo_ignorado": CODIGO_CLIENTE_IGNORADO,
        "bl_codigos": bloqueados_codigos or [],
        "bl_cpfs": bloqueados_cpfs or [],
        "descricao_seguro": DESCRICAO_SEGURO,
        "dias_min_juros": juros.dias_min,
        "juros_dia": juros.juros_dia,
        "multa": juros.multa,
    }
    expanding: list[str] = []
    filtro_loja = filtro_portador = filtro_status = filtro_vencimento = ""
    if vencimento_de:
        filtro_vencimento += "AND a.vencimento_mais_antigo >= :vencimento_de "
        params["vencimento_de"] = vencimento_de
    if vencimento_ate:
        filtro_vencimento += "AND a.vencimento_mais_antigo <= :vencimento_ate "
        params["vencimento_ate"] = vencimento_ate
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

    def montar(qtd_alvo: int):
        cte_alvo = filtro_alvo = ""
        if qtd_alvo:
            cte_alvo = "alvo(pessoa) AS (VALUES %s), " % ", ".join(f"(:alvo{j})" for j in range(qtd_alvo))
            # coluna char(8) bruta, pra usar idx_financeiro_titulos_pessoa
            filtro_alvo = "AND ft.pessoa IN (SELECT CAST(pessoa AS char(8)) FROM alvo)"
        return text(
            _SQL_BASE_COBRANCA.format(
                cte_alvo=cte_alvo,
                filtro_loja_titulo=filtro_loja,
                filtro_portador=filtro_portador,
                filtro_alvo=filtro_alvo,
                filtro_status=filtro_status,
                filtro_vencimento=filtro_vencimento,
                filtro_dias=_sql_dias(dias_exatos, faixas),
            )
        ).bindparams(*(bindparam(nome, expanding=True) for nome in expanding))

    if codigos is not None and not codigos:
        return []
    lotes = [codigos[i : i + 1000] for i in range(0, len(codigos), 1000)] if codigos else [[]]

    try:
        rows = []
        with engine.connect() as conn:
            for lote in lotes:
                alvo = {f"alvo{j}": c for j, c in enumerate(lote)}
                rows.extend(conn.execute(montar(len(lote)), {**params, **alvo}).mappings().all())
    except SQLAlchemyError as exc:
        logger.warning("Falha ao consultar o SETA: %s", exc.__class__.__name__)
        raise SetaIndisponivel(f"Falha ao consultar o SETA ({exc.__class__.__name__})") from exc
    return [dict(r) for r in rows]


def buscar_spc(codigos: list[str]) -> dict[str, str]:
    """Texto bruto da consulta SPC de cada cliente. É pesado (~1 KB por cliente),
    então só se pede para quem vai aparecer na tela ou virar lead.
    Compara a coluna bruta 'codigo' (sem trim) para usar o índice pk_pessoas."""

    if not codigos:
        return {}
    engine = engine_ou_erro()
    # Compara a coluna bruta para usar o índice PK (bpchar ignora espaços à direita no =)
    stmt = text(
        "SELECT trim(codigo) AS codigo, scpcresultado FROM pessoas WHERE codigo IN :codigos AND funcionario = false"
    ).bindparams(bindparam("codigos", expanding=True))
    try:
        with engine.connect() as conn:
            return {r.codigo: r.scpcresultado for r in conn.execute(stmt, {"codigos": codigos})}
    except SQLAlchemyError as exc:
        logger.warning("Falha ao consultar o SETA: %s", exc.__class__.__name__)
        raise SetaIndisponivel(f"Falha ao consultar o SETA ({exc.__class__.__name__})") from exc


def compras_de_clientes(codigos: list[str]) -> dict[str, tuple[int, date | None]]:
    """Compras no crediário de cada cliente: código → (quantidade, data da mais
    recente). Vendas pelo índice de cliente, em lotes de 1000. Cliente sem
    compra volta com (0, None)."""

    resultado: dict[str, tuple[int, date | None]] = {c: (0, None) for c in codigos}
    if not codigos:
        return resultado
    engine = engine_ou_erro()
    try:
        with engine.connect() as conn:
            for i in range(0, len(codigos), 1000):
                lote = codigos[i : i + 1000]
                values = ", ".join(f"(:p{j})" for j in range(len(lote)))
                sql = f"""
                    WITH alvo(pessoa) AS (VALUES {values})
                    SELECT trim(v.cliente) AS codigo, count(*) AS qtd, max(v.data) AS ultima
                      FROM vendas v
                      JOIN condicoes c ON c.codigo = v.condicoes
                      -- char(8) bruto, pra usar idx_vendas_cliente
                      JOIN alvo a ON v.cliente = CAST(a.pessoa AS char(8))
                     WHERE {_SQL_VENDA_CREDIARIO}
                     GROUP BY v.cliente
                """
                params = {**_PARAMS_VENDA, **{f"p{j}": c for j, c in enumerate(lote)}}
                for r in conn.execute(text(sql), params):
                    resultado[r.codigo] = (int(r.qtd), r.ultima)
    except SQLAlchemyError as exc:
        logger.warning("Falha ao consultar compras no SETA: %s", exc.__class__.__name__)
        raise SetaIndisponivel(f"Falha ao consultar o SETA ({exc.__class__.__name__})") from exc
    return resultado


def clientes_com_venda_desde(desde: date) -> list[str]:
    """Clientes com qualquer venda (finalizada ou não) a partir da data: são os
    que podem ter mudado de faixa de compra. Índice de data de vendas."""

    engine = engine_ou_erro()
    try:
        with engine.connect() as conn:
            return [
                r[0]
                for r in conn.execute(
                    text("SELECT DISTINCT trim(cliente) FROM vendas WHERE data >= :desde AND cliente IS NOT NULL"),
                    {"desde": desde},
                )
                if r[0]
            ]
    except SQLAlchemyError as exc:
        logger.warning("Falha ao consultar vendas no SETA: %s", exc.__class__.__name__)
        raise SetaIndisponivel(f"Falha ao consultar o SETA ({exc.__class__.__name__})") from exc


def compras_de_todos() -> dict[str, tuple[int, date | None]]:
    """Compras no crediário de todos os clientes (carga completa semanal, de
    madrugada): uma leitura da tabela de vendas agrupada por cliente."""

    engine = engine_ou_erro()
    sql = f"""
        SELECT trim(v.cliente) AS codigo, count(*) AS qtd, max(v.data) AS ultima
          FROM vendas v
          JOIN condicoes c ON c.codigo = v.condicoes
         WHERE {_SQL_VENDA_CREDIARIO}
         GROUP BY v.cliente
    """
    try:
        with engine.connect() as conn:
            # Só de madrugada: lê a tabela de vendas inteira, passa do teto padrão por consulta
            conn.execute(text("SET statement_timeout = 900000"))
            return {r.codigo: (int(r.qtd), r.ultima) for r in conn.execute(text(sql), _PARAMS_VENDA) if r.codigo}
    except SQLAlchemyError as exc:
        logger.warning("Falha na carga de compras do SETA: %s", exc.__class__.__name__)
        raise SetaIndisponivel(f"Falha ao consultar o SETA ({exc.__class__.__name__})") from exc


def telefones_por_codigo(codigos: list[str]) -> dict[str, dict[str, str | None]]:
    """telefone1/2/3/4 do cadastro de cada cliente, pra tentar outro número quando
    o que veio (ex.: da planilha) não serve. Índice pk_pessoas, em lotes."""

    resultado: dict[str, dict[str, str | None]] = {}
    if not codigos:
        return resultado
    engine = engine_ou_erro()
    stmt = text(
        "SELECT trim(codigo) AS codigo, telefone1, telefone2, telefone3, telefone4 FROM pessoas WHERE codigo IN :codigos AND funcionario = false"
    ).bindparams(bindparam("codigos", expanding=True))
    try:
        with engine.connect() as conn:
            for i in range(0, len(codigos), 1000):
                for r in conn.execute(stmt, {"codigos": codigos[i : i + 1000]}):
                    resultado[r.codigo] = {
                        "telefone1": r.telefone1, "telefone2": r.telefone2, "telefone3": r.telefone3, "telefone4": r.telefone4
                    }
    except SQLAlchemyError as exc:
        logger.warning("Falha ao consultar o SETA: %s", exc.__class__.__name__)
        raise SetaIndisponivel(f"Falha ao consultar o SETA ({exc.__class__.__name__})") from exc
    return resultado


def codigos_por_cpf(cpfs: list[str]) -> dict[str, str]:
    """CPF (só dígitos) -> código do cliente, para planilhas de campanha que
    trazem só o CPF. Uma consulta só, com todos os CPFs num array."""

    if not cpfs:
        return {}
    engine = engine_ou_erro()
    stmt = text(
        "WITH alvo AS (SELECT DISTINCT unnest(CAST(:cpfs AS text[])) AS cpf) "
        "SELECT a.cpf, trim(p.codigo) AS codigo "
        # Mesma expressão do índice de CPF só com dígitos que já existe em pessoas;
        # com regexp_replace o SETA varria as ~930 mil pessoas a cada consulta
        "  FROM pessoas p JOIN alvo a ON translate(p.cpfcnpj::text, ' +-.,/\\*', '')::char(16) = CAST(a.cpf AS char(16)) "
        " WHERE p.cliente AND p.funcionario = false"
    )
    try:
        with engine.connect() as conn:
            return {r.cpf: r.codigo for r in conn.execute(stmt, {"cpfs": sorted(set(cpfs))})}
    except SQLAlchemyError as exc:
        logger.warning("Falha ao consultar o SETA: %s", exc.__class__.__name__)
        raise SetaIndisponivel(f"Falha ao consultar o SETA ({exc.__class__.__name__})") from exc


# --- Consulta de parcelas e situação para efetividade -----------------------

_SQL_PARCELAS_COBRANCA = r"""
WITH parcelas AS (
    SELECT trim(ft.pessoa)   AS pessoa,
           trim(ft.codigo)   AS titulo_codigo,
           trim(ft.empresa)  AS empresa,
           ft.vencimento,
           ft.valor,
           min(ft.vencimento) OVER (PARTITION BY ft.pessoa) AS vencimento_min
      FROM financeiro_titulos ft
     WHERE ft.rp = 'R'
       AND ft.status = 'A'
       AND ft.tipo IN ('4', '5')
       AND ft.valor > 0
       AND ft.pessoa IN :codigos
)
SELECT pessoa,
       titulo_codigo,
       empresa,
       vencimento,
       valor,
       round(
           CASE WHEN current_date - vencimento > :dias_min_juros
                THEN valor + valor * :juros_dia * (current_date - vencimento) + valor * :multa
                ELSE valor
           END, 2
       ) AS valor_cobrar
  FROM parcelas
 WHERE vencimento <= GREATEST(current_date, vencimento_min)
 ORDER BY pessoa, vencimento, titulo_codigo
"""


def buscar_parcelas_cobranca(
    codigos: list[str], juros: ParametrosJuros = PARAMETROS_JUROS_PADRAO
) -> dict[str, list[dict]]:
    """Por código de cliente, as parcelas que entram na cobrança (mesma regra
    da base de cobrança: rp='R', status='A', tipo 4/5, valor > 0, vencimento <=
    GREATEST(hoje, vencimento_min)). Cada dict tem titulo_codigo, empresa,
    vencimento, valor e valor_cobrar.
    Compara ft.pessoa bruto (sem trim) para usar o índice idx_financeiro_titulos_pessoa."""

    resultado: dict[str, list[dict]] = {c: [] for c in codigos}
    if not codigos:
        return resultado

    engine = engine_ou_erro()
    params_base = {
        "dias_min_juros": juros.dias_min,
        "juros_dia": juros.juros_dia,
        "multa": juros.multa,
    }
    CHUNK = 1000
    try:
        with engine.connect() as conn:
            for i in range(0, len(codigos), CHUNK):
                chunk = codigos[i : i + CHUNK]
                stmt = text(_SQL_PARCELAS_COBRANCA).bindparams(bindparam("codigos", expanding=True))
                params = {**params_base, "codigos": chunk}
                for r in conn.execute(stmt, params).mappings():
                    p_dict = {
                        "titulo_codigo": r["titulo_codigo"],
                        "empresa": r["empresa"],
                        "vencimento": r["vencimento"],
                        "valor": r["valor"],
                        "valor_cobrar": r["valor_cobrar"],
                    }
                    resultado.setdefault(r["pessoa"], []).append(p_dict)
    except SQLAlchemyError as exc:
        logger.warning("Falha ao consultar parcelas no SETA: %s", exc.__class__.__name__)
        raise SetaIndisponivel(f"Falha ao consultar o SETA ({exc.__class__.__name__})") from exc
    return resultado


def entradas_vencidas_em_aberto(referencias: list[str]) -> dict[str, date]:
    """Das referências de acordo (`ft.auxiliar`, ex.: "RE042851"), as que ainda
    existem no SETA com a entrada — a parcela de vencimento mais antigo —
    em aberto (status 'A') e já vencida. Devolve referência → vencimento da
    entrada. Uma consulta por lote (CTE + VALUES)."""

    if not referencias:
        return {}
    engine = engine_ou_erro()
    vencidas: dict[str, date] = {}
    try:
        with engine.connect() as conn:
            for i in range(0, len(referencias), 1000):
                lote = referencias[i : i + 1000]
                values = ", ".join(f"(:r{j})" for j in range(len(lote)))
                sql = f"""
                    WITH acordos(auxiliar) AS (VALUES {values}),
                    entradas AS (
                        SELECT DISTINCT ON (ft.auxiliar)
                               trim(ft.auxiliar) AS auxiliar, ft.status, ft.vencimento
                          FROM acordos a
                          -- auxiliar é char(10): compara bruto, como o JOIN de vendas acima
                          JOIN financeiro_titulos ft ON ft.auxiliar = CAST(a.auxiliar AS char(10))
                         WHERE ft.tipo IN ('4', '5')
                         ORDER BY ft.auxiliar, ft.vencimento, ft.documento
                    )
                    SELECT auxiliar, vencimento FROM entradas
                     WHERE status = 'A' AND vencimento < current_date
                """
                params = {f"r{j}": ref for j, ref in enumerate(lote)}
                vencidas.update({r[0]: r[1] for r in conn.execute(text(sql), params)})
    except SQLAlchemyError as exc:
        logger.warning("Falha ao consultar acordos no SETA: %s", exc.__class__.__name__)
        raise SetaIndisponivel(f"Falha ao consultar o SETA ({exc.__class__.__name__})") from exc
    return vencidas


def situacao_titulos(codigos: list[str]) -> dict[str, dict]:
    """Consulta no SETA a situação de liquidação dos títulos pelo código.
    Compara ft.codigo bruto (sem trim) para usar o índice pk_financeiro_titulos."""

    if not codigos:
        return {}

    engine = engine_ou_erro()
    resultado: dict[str, dict] = {}
    CHUNK = 1000
    # Compara a coluna bruta para usar o índice PK (bpchar ignora espaços à direita no =)
    stmt = text(
        "SELECT trim(ft.codigo) AS titulo_codigo, "
        "trim(ft.status) AS status, "
        "ft.pagamento, "
        "COALESCE(ft.valorpago, 0) AS valorpago, "
        "COALESCE(ft.valor, 0) AS valor "
        "FROM financeiro_titulos ft "
        "WHERE ft.codigo IN :codigos AND ft.tipo IN ('4', '5')"
    ).bindparams(bindparam("codigos", expanding=True))

    try:
        with engine.connect() as conn:
            for i in range(0, len(codigos), CHUNK):
                chunk = codigos[i : i + CHUNK]
                for r in conn.execute(stmt, {"codigos": chunk}).mappings():
                    pag = r["pagamento"]
                    if hasattr(pag, "date") and callable(pag.date):
                        pag = pag.date()
                    resultado[r["titulo_codigo"]] = {
                        "status": r["status"],
                        "pagamento": pag,
                        "valorpago": r["valorpago"],
                        "valor": r["valor"],
                    }
    except SQLAlchemyError as exc:
        logger.warning("Falha ao consultar situação dos títulos no SETA: %s", exc.__class__.__name__)
        raise SetaIndisponivel(f"Falha ao consultar o SETA ({exc.__class__.__name__})") from exc
    return resultado


LOTE_CLIENTES = 1000
# Leitura a partir de até esse tanto de dias atrás vai pelo índice de
# `pagamento`: lê só as baixas do período e cruza com os clientes em memória
# (hash), então o custo no SETA não cresce com o número de clientes. Mais
# antiga que isso, pelo índice de `pessoa` (lê o histórico do cliente).
# 150 dias: a primeira cópia de muitos clientes cobrados há meses continua numa
# consulta só, sem abrir o histórico de cada um no SETA.
JANELA_RECENTE_DIAS = 150
LOTE_RECENTE = 50000


def _linha_baixa(r) -> dict:
    linha = dict(r)
    if hasattr(linha["pagamento"], "date") and callable(linha["pagamento"].date):
        linha["pagamento"] = linha["pagamento"].date()
    # Horário do caixa só vale se for do próprio dia do pagamento
    pago_em = linha.get("pago_em")
    if pago_em is not None and pago_em.date() != linha["pagamento"]:
        linha["pago_em"] = None
    return linha


def plano_baixas(clientes: list[tuple[str, date]], hoje: date | None = None) -> list[tuple[str, list[tuple[str, date]]]]:
    """Divide [(codigo_cliente, desde)] nas consultas que baixas_de_clientes
    vai fazer: ("recente", lote) pelo índice de pagamento, ("historico", lote)
    pelo índice de pessoa."""

    from .timezone import hoje_br

    corte = (hoje or hoje_br()) - timedelta(days=JANELA_RECENTE_DIAS)
    recentes = sorted((c for c in clientes if c[1] >= corte), key=lambda c: (c[1], c[0]))
    antigos = [c for c in clientes if c[1] < corte]
    plano = [("recente", recentes[i : i + LOTE_RECENTE]) for i in range(0, len(recentes), LOTE_RECENTE)]
    plano += [("historico", antigos[i : i + LOTE_CLIENTES]) for i in range(0, len(antigos), LOTE_CLIENTES)]
    return plano


def baixas_de_clientes(clientes: list[tuple[str, date]]) -> list[dict]:
    """Títulos do crediário (tipo 4/5) quitados (status 'B') de cada cliente com pagamento a partir da
    data informada: [(codigo_cliente, desde)] → uma linha por título, com
    valor e rp brutos e o horário do caixa (pago_em) quando a baixa foi no caixa. Base da cópia local em services/pagamentos_seta.py.
    Consulta por lote, nunca em loop por cliente (ver plano_baixas)."""

    resultado: list[dict] = []
    if not clientes:
        return resultado

    engine = engine_ou_erro()
    try:
        with engine.connect() as conn:
            for tipo, lote in plano_baixas(clientes):
                if tipo == "recente":
                    # Lote ordenado por data: a menor data do lote é o início do
                    # intervalo; o corte exato de cada cliente é feito abaixo.
                    desde = dict(lote)
                    # trim(ft.pessoa) de propósito: evita o índice de pessoa e faz o
                    # Postgres ler só o intervalo de pagamento e cruzar por hash
                    sql = """
                        WITH clientes(pessoa) AS (SELECT unnest(CAST(:clientes AS text[])))
                        SELECT trim(ft.codigo) AS titulo_codigo,
                               trim(ft.pessoa) AS codigo_cliente,
                               ft.pagamento AS pagamento,
                               COALESCE(ft.valor, 0) AS valor,
                               COALESCE(trim(ft.rp), '') AS rp,
                               l.datahora AS pago_em
                          FROM financeiro_titulos ft
                          JOIN clientes c ON c.pessoa = trim(ft.pessoa)
                          LEFT JOIN caixa_lotes l ON l.codigo = ft.lote
                         WHERE ft.status = 'B'
                           -- 4 e 5: títulos do crediário (parcela, acréscimo, seguro...). Fora: venda à vista e o
                           -- registro de quitação do lote (PayHub, BAIXA DE TITULO), que repete a soma das parcelas
                           AND ft.tipo IN ('4', '5')
                           AND ft.pagamento >= :inicio
                    """
                    params = {"inicio": lote[0][1], "clientes": [c for c, _ in lote]}
                    for r in conn.execute(text(sql), params).mappings():
                        linha = _linha_baixa(r)
                        if linha["codigo_cliente"] in desde and linha["pagamento"] >= desde[linha["codigo_cliente"]]:
                            resultado.append(linha)
                    continue

                linhas_values = ", ".join(f"(:p{j}, CAST(:d{j} AS date))" for j in range(len(lote)))
                params = {}
                for j, (codigo, desde_cliente) in enumerate(lote):
                    params[f"p{j}"] = codigo
                    params[f"d{j}"] = desde_cliente
                sql = f"""
                    WITH clientes(pessoa, desde) AS (
                        VALUES {linhas_values}
                    )
                    SELECT trim(ft.codigo) AS titulo_codigo,
                           c.pessoa AS codigo_cliente,
                           ft.pagamento AS pagamento,
                           COALESCE(ft.valor, 0) AS valor,
                           COALESCE(trim(ft.rp), '') AS rp,
                           l.datahora AS pago_em
                      FROM clientes c
                      -- coluna char(8) bruta, pra usar idx_financeiro_titulos_pessoa
                      JOIN financeiro_titulos ft ON ft.pessoa = CAST(c.pessoa AS char(8))
                      LEFT JOIN caixa_lotes l ON l.codigo = ft.lote
                     WHERE ft.status = 'B'
                       AND ft.tipo IN ('4', '5')
                       AND ft.pagamento >= c.desde
                """
                for r in conn.execute(text(sql), params).mappings():
                    resultado.append(_linha_baixa(r))
    except SQLAlchemyError as exc:
        logger.warning("Falha ao consultar baixas no SETA: %s", exc.__class__.__name__)
        raise SetaIndisponivel(f"Falha ao consultar o SETA ({exc.__class__.__name__})") from exc
    return resultado
