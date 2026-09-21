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

from sqlalchemy import create_engine, text
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
