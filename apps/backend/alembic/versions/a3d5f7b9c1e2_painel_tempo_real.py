"""avisos do Dashboard em tempo real (triggers com pg_notify)

Revision ID: a3d5f7b9c1e2
Revises: e9c4a1f7b2d6
Create Date: 2026-10-03

Toda mudança em cobranca_fila e telefones_invalidos avisa no canal "painel"
o saldo do comando, agrupado por status e hora (UTC) de entrada e de envio,
com o id da transação; pausas_envio só avisa que mudou. Um aviso por comando,
mesmo em massa, e só no COMMIT. Quem ouve é app/painel_tempo_real.py. Só Postgres.
"""

from collections.abc import Sequence

from alembic import op


revision: str = "a3d5f7b9c1e2"
down_revision: str | None = "e9c4a1f7b2d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Saldo do comando: +1 por linha nova, -1 por linha antiga; linha que não mudou
# status, entrada nem envio se anula. Acima do limite do NOTIFY (8000 bytes),
# pede recontagem. "u" deixa cada aviso único: o Postgres junta avisos de texto
# igual na mesma transação (o ORM manda um UPDATE por item), o que perderia saldo.
_AVISAR = """
    IF saldo IS NULL THEN RETURN NULL; END IF;
    PERFORM pg_notify('painel', CASE WHEN length(saldo) > 7900 THEN '{"recontar": true}' ELSE saldo END);
    RETURN NULL;
"""
_SALDO = """
    SELECT CASE WHEN count(*) > 0 THEN json_build_object(
               'x', pg_current_xact_id()::text, 'u', random(),
               'd', json_agg(json_build_object('s', s, 'c', c, 'e', e, 'n', n)))::text END
      FROM (SELECT s, c, e, sum(n) AS n FROM ({linhas}) l GROUP BY s, c, e HAVING sum(n) <> 0) g
"""
_FILA = "SELECT status::text AS s, date_trunc('hour', created_at) AS c, date_trunc('hour', sent_at) AS e, {n} AS n FROM {tabela}"
_INVALIDOS = "SELECT 'invalido' AS s, date_trunc('hour', created_at) AS c, NULL::timestamp AS e, {n} AS n FROM {tabela}"


def _funcao(nome: str, linha: str) -> str:
    novas, antigas = linha.format(n=1, tabela="novas"), linha.format(n=-1, tabela="antigas")
    return f"""
    CREATE FUNCTION {nome}() RETURNS trigger LANGUAGE plpgsql AS $$
    DECLARE saldo text;
    BEGIN
        IF TG_OP = 'INSERT' THEN {_SALDO.format(linhas=novas)} INTO saldo;
        ELSIF TG_OP = 'DELETE' THEN {_SALDO.format(linhas=antigas)} INTO saldo;
        ELSE {_SALDO.format(linhas=f"{novas} UNION ALL {antigas}")} INTO saldo;
        END IF;
        {_AVISAR}
    END $$;
    """


def _triggers(tabela: str, funcao: str, eventos: tuple[str, ...]) -> None:
    # tabela de transição só aceita um evento por trigger
    for evento in eventos:
        referencias = {"INSERT": "NEW TABLE AS novas", "DELETE": "OLD TABLE AS antigas", "UPDATE": "OLD TABLE AS antigas NEW TABLE AS novas"}
        op.execute(
            f"CREATE TRIGGER painel_{evento.lower()} AFTER {evento} ON {tabela} "
            f"REFERENCING {referencias[evento]} FOR EACH STATEMENT EXECUTE FUNCTION {funcao}()"
        )


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(_funcao("painel_fila", _FILA))
    op.execute(_funcao("painel_invalidos", _INVALIDOS))
    op.execute(
        "CREATE FUNCTION painel_pausas() RETURNS trigger LANGUAGE plpgsql AS $$ "
        "BEGIN PERFORM pg_notify('painel', json_build_object('pausas', true, 'u', random())::text); RETURN NULL; END $$"
    )
    _triggers("cobranca_fila", "painel_fila", ("INSERT", "UPDATE", "DELETE"))
    _triggers("telefones_invalidos", "painel_invalidos", ("INSERT", "UPDATE", "DELETE"))
    _triggers("pausas_envio", "painel_pausas", ("INSERT", "UPDATE", "DELETE"))


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for tabela in ("cobranca_fila", "telefones_invalidos", "pausas_envio"):
        for evento in ("insert", "update", "delete"):
            op.execute(f"DROP TRIGGER IF EXISTS painel_{evento} ON {tabela}")
    for funcao in ("painel_fila", "painel_invalidos", "painel_pausas"):
        op.execute(f"DROP FUNCTION IF EXISTS {funcao}()")
