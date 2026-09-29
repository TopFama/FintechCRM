"""Quem pode entrar na fila e quem pode sair agora. É aqui que mora a regra
fixa de no máximo UMA comunicação por cliente por dia (GMT-3), em qualquer
caminho de envio (régua, campanha, remarketing, planilha):

- entrada: `clientes_bloqueados_hoje` (quem está pendente/reservado ou já foi
  cobrado hoje) e a blacklist;
- saída: `conferir_saida`, chamada pelo worker item a item logo antes de
  enviar (pausa, blacklist e cobrança de hoje por outro caminho)."""

from sqlalchemy import and_, or_, text
from sqlalchemy.orm import Session

from . import models
from .blacklist import Blacklist
from .pausas import Retencao
from .timezone import inicio_hoje_utc

# Status que "ocupam" o cliente: vai sair (pendente/reservado) ou saiu
# (enviado). Erro, telefone inválido, parado, descartado e expirado não
# contam: quem não foi cobrado pode entrar de novo em outra base.
STATUS_OCUPA_CLIENTE = (models.QueueStatus.pending, models.QueueStatus.reserved, models.QueueStatus.sent)


def ocupa_cliente():
    """Filtro de STATUS_OCUPA_CLIENTE. Erro incerto ou falha na Meta
    agora liberam o cliente para nova tentativa ou fluxo."""
    return models.QueueItem.status.in_(STATUS_OCUPA_CLIENTE)


def _cobrado_hoje():
    """Enviado hoje (GMT-3). Falhas de envio (qualquer erro)
    não bloqueiam o cliente."""
    return and_(
        models.QueueItem.status == models.QueueStatus.sent,
        models.QueueItem.sent_at >= inicio_hoje_utc(),
    )


# Chave do lock do Postgres que serializa quem coloca clientes na fila.
TRAVA_ENTRADA_FILA = 72_010_001


def travar_entrada_na_fila(db: Session) -> None:
    """Uma entrada na fila por vez (régua, campanha, remarketing, planilha).
    Sem isso, duas rotinas ao mesmo tempo liam a fila antes de uma gravar e o
    mesmo cliente entrava duas vezes. O lock vale até o commit ou rollback."""

    if db.get_bind().dialect.name == "postgresql":
        db.execute(text("SELECT pg_advisory_xact_lock(:chave)"), {"chave": TRAVA_ENTRADA_FILA})


def clientes_bloqueados_hoje(db: Session) -> set[str]:
    """Códigos que não podem entrar na fila agora, em QUALQUER faixa: quem já
    está pendente/reservado (vai sair) e quem já foi cobrado hoje (GMT-3).
    Cliente cobrado em dia anterior pode voltar, e quem entrou na fila mas
    não foi cobrado (erro, parado, descartado, expirado) também.

    Trava a entrada na fila até o commit de quem chamou: quem chama tem que
    gravar os itens e dar commit na mesma transação."""

    travar_entrada_na_fila(db)
    return {
        codigo
        for (codigo,) in db.query(models.QueueItem.codigo_cliente).filter(
            or_(
                models.QueueItem.status.in_([models.QueueStatus.pending, models.QueueStatus.reserved]),
                _cobrado_hoje(),
            )
        )
    }


def cobrados_hoje(db: Session) -> set[str]:
    """Códigos que já receberam cobrança hoje (GMT-3), em qualquer faixa."""

    return {
        codigo
        for (codigo,) in db.query(models.QueueItem.codigo_cliente).filter(_cobrado_hoje())
    }


def sem_cobrados_hoje(db: Session, clientes: list[dict]) -> list[dict]:
    """Tira da lista quem já recebeu cobrança hoje (GMT-3, qualquer faixa).
    Cobrado em dia anterior aparece normalmente."""

    bloqueados = cobrados_hoje(db)
    return [c for c in clientes if c["codigo"] not in bloqueados]


def ja_cobrado_hoje(db: Session, item: models.QueueItem) -> bool:
    """Checagem final antes do envio: outro item do mesmo cliente já saiu hoje (qualquer faixa)."""

    return (
        db.query(models.QueueItem.id)
        .filter(
            models.QueueItem.codigo_cliente == item.codigo_cliente,
            models.QueueItem.id != item.id,
            _cobrado_hoje(),
        )
        .first()
        is not None
    )


# Resultado de `conferir_saida` quando o item está só retido por pausa: volta
# a pendente e sai quando a pausa acabar.
RETIDO = "retido"


def conferir_saida(db: Session, item: models.QueueItem, blacklist: Blacklist) -> str | None:
    """Checagem final antes do envio, na ordem: pausa (relida agora, pega
    pausa criada depois da reserva), blacklist e cobrança de hoje em outra
    faixa ou envio. Devolve None se pode sair, RETIDO se está pausado, ou o
    motivo do erro que fica gravado no item."""

    if Retencao.carregar(db).retido(item):
        return RETIDO
    # Entrou na blacklist depois de estar na fila (ou veio de planilha antiga)
    if blacklist.contem(item.codigo_cliente, item.cpf):
        return "Cliente na blacklist; não enviado"
    # Última barreira: o mesmo cliente pode ter entrado em duas filas antes de sair em uma.
    if ja_cobrado_hoje(db, item):
        return "Cliente já cobrado hoje em outra faixa ou envio; não reenviado"
    return None
