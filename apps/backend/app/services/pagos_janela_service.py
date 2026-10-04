"""Card de pagamentos do Dashboard: dos clientes cobrados no período, quantos
pagaram dentro da janela configurada em Indicadores
(`ParametrosCobranca.dias_janela_dashboard`; nulo = qualquer data após a
cobrança). Usa a mesma regra de "pagou" e a mesma lista do relatório Quem
pagou (pagamentos_service com dias_janela), pra o número do card ser
exatamente o total do relatório. A lista vem do mesmo
snapshot no Redis do relatório (`snapshot_pagamentos`), então abrir o card e o
relatório com o mesmo período e janela consulta o SETA uma vez só."""

from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from .. import models
from ..timezone import dia_br, hoje_br, inicio_do_dia_utc
from . import pagamentos_service


def resumo(db: Session, de: date | None, ate: date | None) -> dict:
    """Levanta seta_client.SetaIndisponivel se o SETA estiver fora e
    cache.CacheIndisponivel/CacheOcupado se o Redis estiver."""

    dias_janela = db.query(models.ParametrosCobranca.dias_janela_dashboard).scalar()

    query = db.query(models.Lead.codigo_cliente, models.Lead.cobrado_em).filter(
        models.Lead.status == "cobrado", models.Lead.cobrado_em.isnot(None)
    )
    if de:
        query = query.filter(models.Lead.cobrado_em >= inicio_do_dia_utc(de))
    if ate:
        query = query.filter(models.Lead.cobrado_em < inicio_do_dia_utc(ate + timedelta(days=1)))

    cobrados: set[str] = set()
    em_maturacao: set[str] = set()
    # cobrado há menos de `dias_janela` dias: ainda pode pagar dentro da janela
    # (sem janela não há prazo a esperar)
    limite = hoje_br() - timedelta(days=dias_janela) if dias_janela is not None else None
    for codigo, cobrado_em in query.all():
        cobrados.add(codigo)
        if limite is not None and dia_br(cobrado_em) > limite:
            em_maturacao.add(codigo)

    linhas = pagamentos_service.snapshot_pagamentos(cobrado_de=de, cobrado_ate=ate, dias_janela=dias_janela).data
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
