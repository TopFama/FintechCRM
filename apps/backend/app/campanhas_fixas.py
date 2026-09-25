"""Remarketing do Renegocie como campanha fixa: cada segmento é uma campanha
que sempre existe (não se cria nem se exclui na tela Campanhas). O id dela,
"remarketing:<SEGMENTO>", vai em Lead.campanha_id e nos filtros "Campanha",
então Efetividade, exportação de leads, Relatórios e a ida para a régua no dia
seguinte tratam o remarketing como qualquer campanha."""

from sqlalchemy.orm import Session

from . import models

PREFIXO = "remarketing:"


def id_campanha(segmento: str) -> str:
    return PREFIXO + segmento


def eh_fixa(campanha_id: str | None) -> bool:
    return bool(campanha_id) and campanha_id.startswith(PREFIXO)


def listar(db: Session) -> list[dict]:
    """Um item por segmento: id, nome (o da faixa, "Remarketing: …"), faixa_id,
    segmento e se o envio automático está ligado."""

    linhas = (
        db.query(models.RemarketingSegmento, models.Faixa.name)
        .join(models.Faixa, models.Faixa.id == models.RemarketingSegmento.faixa_id)
        .order_by(models.Faixa.name)
    )
    return [
        {"id": id_campanha(r.segmento), "nome": nome, "faixa_id": r.faixa_id, "segmento": r.segmento, "ativo": r.ativo}
        for r, nome in linhas
    ]


def faixa_id(db: Session, campanha_id: str) -> str | None:
    regra = db.get(models.RemarketingSegmento, campanha_id.removeprefix(PREFIXO))
    return regra.faixa_id if regra else None
