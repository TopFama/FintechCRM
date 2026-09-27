"""Pausar, retomar e parar o envio dos pendentes por cliente, faixa (régua)
ou loja. A pausa não muda o status do item: o worker só deixa de pegar o que
está retido, então ela vale também para o que entrar na fila depois (inclusive
no dia seguinte, quando expirar_nao_enviados já apagou os pendentes antigos).
Parar é definitivo: marca os pendentes do escopo como cancelados."""

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import false, or_
from sqlalchemy.orm import Session

from . import models
from .timezone import BUSINESS_TZ, hoje_br
from .utils.document import normalize_seta_code

ESCOPOS = ("cliente", "faixa", "loja")
STATUS_PENDENTE = (models.QueueStatus.pending, models.QueueStatus.reserved)


def normalizar_valor(escopo: str, valor: str) -> str:
    valor = (valor or "").strip()
    if escopo == "cliente":
        return normalize_seta_code(valor) or valor
    if escopo == "loja":
        return valor.zfill(2) if valor.isdigit() else valor.upper()
    return valor


def ativas(db: Session) -> list[models.PausaEnvio]:
    hoje = hoje_br()
    return (
        db.query(models.PausaEnvio)
        .filter(
            models.PausaEnvio.encerrada_em.is_(None),
            or_(models.PausaEnvio.ate.is_(None), models.PausaEnvio.ate >= hoje),
        )
        .order_by(models.PausaEnvio.created_at.desc())
        .all()
    )


def ativa_do_escopo(db: Session, escopo: str, valor: str) -> models.PausaEnvio | None:
    return next((p for p in ativas(db) if p.escopo == escopo and p.valor == valor), None)


def data_final_passou(ate) -> bool:
    return bool(ate) and ate < hoje_br()


def pausar(db: Session, escopo: str, valor: str, motivo: str, ate, usuario: str) -> models.PausaEnvio:
    """Cria a pausa (sem commit: quem chama decide, para pausar em lote numa transação só)."""
    pausa = models.PausaEnvio(escopo=escopo, valor=valor, motivo=motivo, ate=ate, created_by=usuario)
    db.add(pausa)
    return pausa


def retomar(pausa: models.PausaEnvio, usuario: str) -> None:
    """Encerra a pausa, se ainda estiver aberta (sem commit)."""
    if pausa.encerrada_em is None:
        pausa.encerrada_em = datetime.utcnow()
        pausa.encerrada_por = usuario


def retomar_escopo(db: Session, escopo: str, valor: str, usuario: str) -> None:
    """Encerra toda pausa ativa do escopo (sem commit)."""
    for p in ativas(db):
        if p.escopo == escopo and p.valor == valor:
            retomar(p, usuario)


def _lojas_do_item(lojas: str | None) -> set[str]:
    return {l for l in (lojas or "").split(",") if l}


@dataclass
class Retencao:
    """Pausas ativas carregadas uma vez (por ciclo do worker ou por request)."""

    clientes: set[str] = field(default_factory=set)
    faixas: set[str] = field(default_factory=set)
    lojas: set[str] = field(default_factory=set)

    @classmethod
    def carregar(cls, db: Session) -> "Retencao":
        r = cls()
        for p in ativas(db):
            {"cliente": r.clientes, "faixa": r.faixas, "loja": r.lojas}[p.escopo].add(p.valor)
        return r

    def __bool__(self) -> bool:
        return bool(self.clientes or self.faixas or self.lojas)

    def retido(self, item: models.QueueItem) -> bool:
        return (
            item.codigo_cliente in self.clientes
            or item.faixa_id in self.faixas
            or bool(_lojas_do_item(item.lojas) & self.lojas)
        )

    def condicao(self):
        """Filtro SQL de item retido (pra excluir da busca ou contar)."""
        conds = []
        if self.clientes:
            conds.append(models.QueueItem.codigo_cliente.in_(self.clientes))
        if self.faixas:
            conds.append(models.QueueItem.faixa_id.in_(self.faixas))
        for loja in self.lojas:
            conds.append(models.QueueItem.lojas.like(f"%,{loja},%"))
        return or_(*conds) if conds else false()


def condicao_escopo(escopo: str, valor: str):
    if escopo == "cliente":
        return models.QueueItem.codigo_cliente == valor
    if escopo == "faixa":
        return models.QueueItem.faixa_id == valor
    return models.QueueItem.lojas.like(f"%,{valor},%")


def pendentes_do_escopo(db: Session, escopo: str, valor: str):
    return db.query(models.QueueItem).filter(
        models.QueueItem.status.in_(STATUS_PENDENTE), condicao_escopo(escopo, valor)
    )


def parar(db: Session, escopo: str, valor: str, usuario: str) -> int:
    """Cancela os pendentes do escopo sem apagar o registro. Item já reservado
    por um envio em andamento também é cancelado; o worker confere o status
    de novo antes de enviar."""

    quando = datetime.now(BUSINESS_TZ).strftime("%d/%m/%Y %H:%M")
    total = (
        pendentes_do_escopo(db, escopo, valor)
        .update(
            {
                models.QueueItem.status: models.QueueStatus.cancelled,
                models.QueueItem.error_message: f"Envio parado por {usuario} em {quando}",
            },
            synchronize_session=False,
        )
    )
    db.commit()
    return total


def lojas_formatadas(lojas) -> str:
    """Lista/str de lojas → ",01,07," (mesmo formato de Lead.lojas)."""
    if isinstance(lojas, str):
        lojas = lojas.split(",")
    codigos = sorted({normalizar_valor("loja", l) for l in (lojas or []) if l and l.strip()})
    return "," + ",".join(codigos) + "," if codigos else ","



