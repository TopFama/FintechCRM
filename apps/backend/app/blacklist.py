"""Blacklist: clientes que nunca entram na cobrança. Consultada na extração do
SETA, no remarketing, no upload de planilha e, antes de cada envio, no worker."""

from sqlalchemy.orm import Session

from . import models


def codigos_bloqueados(db: Session) -> tuple[list[str], list[str]]:
    """(códigos SETA, CPFs) bloqueados — a extração do SETA exclui esses
    clientes direto na consulta."""

    rows = db.query(models.ClienteBloqueado.tipo, models.ClienteBloqueado.valor).all()
    return [v for t, v in rows if t == "seta"], [v for t, v in rows if t == "cpf"]


class Blacklist:
    """Códigos SETA e CPFs da blacklist, para conferir itens que não vieram da
    base do SETA (planilha subida na faixa) e, no envio, quem entrou na
    blacklist depois de estar na fila."""

    def __init__(self, db: Session):
        codigos, cpfs = codigos_bloqueados(db)
        self.codigos = set(codigos)
        self.cpfs = set(cpfs)

    def contem(self, codigo: str | None, cpf: str | None) -> bool:
        digitos_cpf = "".join(ch for ch in (cpf or "") if ch.isdigit())
        return (codigo or "") in self.codigos or (bool(digitos_cpf) and digitos_cpf.zfill(11) in self.cpfs)
