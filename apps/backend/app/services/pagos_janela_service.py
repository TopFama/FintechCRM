"""Card "Pagaram em até 7 dias" do Dashboard: dos clientes cobrados no
período, quantos pagaram dentro da janela. Usa a mesma regra de "pagou" e a
mesma lista do relatório Quem pagou (pagamentos_service com dias_janela), pra
o número do card ser exatamente o total do relatório."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from .. import models
from ..timezone import hoje_br
from . import pagamentos_service


def resumo(db: Session, de: date | None, ate: date | None, dias_janela: int = 7) -> dict:
    """Levanta seta_client.SetaIndisponivel se o SETA estiver fora."""

    query = db.query(models.Lead.codigo_cliente, models.Lead.cobrado_em).filter(
        models.Lead.status == "cobrado", models.Lead.cobrado_em.isnot(None)
    )
    if de:
        query = query.filter(models.Lead.cobrado_em >= pagamentos_service._inicio_utc(de))
    if ate:
        query = query.filter(models.Lead.cobrado_em < pagamentos_service._inicio_utc(ate + timedelta(days=1)))

    cobrados: set[str] = set()
    em_maturacao: set[str] = set()
    # cobrado há menos de `dias_janela` dias: ainda pode pagar dentro da janela
    limite = hoje_br() - timedelta(days=dias_janela)
    for codigo, cobrado_em in query.all():
        cobrados.add(codigo)
        if pagamentos_service._dia_br(cobrado_em) > limite:
            em_maturacao.add(codigo)

    linhas = pagamentos_service.clientes_que_pagaram(db, cobrado_de=de, cobrado_ate=ate, dias_janela=dias_janela)
    pagaram = {l["codigo_cliente"] for l in linhas}
    valor_pago = sum((Decimal(str(l["valor_pago"])) for l in linhas), Decimal("0.00"))
    percentual = (
        (Decimal(len(pagaram)) * 100 / Decimal(len(cobrados))).quantize(Decimal("0.1")) if cobrados else Decimal("0.0")
    )
    return {
        "qtd_cobrados": len(cobrados),
        "qtd_pagaram": len(pagaram),
        "percentual": percentual,
        "valor_pago": valor_pago.quantize(Decimal("0.01")),
        # quem já pagou não está mais "esperando" a janela
        "qtd_em_maturacao": len(em_maturacao - pagaram),
        "dias_janela": dias_janela,
    }
