"""Relatório de quem pagou o que foi cobrado, por cliente: leads cobrados no
período de cobrança cruzados com os pagamentos no SETA (uma consulta em lote)."""

from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from .. import google_client, lojas as lojas_base, models, seta_client
from ..timezone import BUSINESS_TZ


def _inicio_utc(dia: date) -> datetime:
    return datetime.combine(dia, time.min, BUSINESS_TZ).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def _dia_br(dt: datetime) -> date:
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(BUSINESS_TZ).date()


def clientes_que_pagaram(
    db: Session,
    *,
    cobrado_de: date | None = None,
    cobrado_ate: date | None = None,
    pago_de: date | None = None,
    pago_ate: date | None = None,
    faixa: list[str] | None = None,
) -> list[dict]:
    """Uma linha por cliente e data de cobrança, só de quem pagou. Levanta
    seta_client.SetaIndisponivel se o SETA estiver fora."""

    query = db.query(models.Lead).filter(models.Lead.status == "cobrado", models.Lead.cobrado_em.isnot(None))
    if cobrado_de:
        query = query.filter(models.Lead.cobrado_em >= _inicio_utc(cobrado_de))
    if cobrado_ate:
        query = query.filter(models.Lead.cobrado_em < _inicio_utc(cobrado_ate + timedelta(days=1)))
    if faixa:
        query = query.filter(models.Lead.faixa.in_(faixa))

    # Mesmo cliente em mais de um lead no mesmo dia (faixas/vencimentos
    # diferentes) vira uma linha só, somando o valor cobrado.
    cobrancas: dict[tuple[str, date], dict] = {}
    for lead in query.all():
        chave = (lead.codigo_cliente, _dia_br(lead.cobrado_em))
        linha = cobrancas.get(chave)
        lojas = {l for l in (lead.lojas or "").split(",") if l}
        if linha is None:
            cobrancas[chave] = {
                "codigo_cliente": lead.codigo_cliente,
                "nome": lead.nome,
                "cpf": lead.cpf,
                "faixas": {lead.faixa},
                "lojas": lojas,
                "data_cobranca": chave[1],
                "valor_cobrado": Decimal(lead.valor_cobrar or 0),
            }
        else:
            linha["faixas"].add(lead.faixa)
            linha["lojas"] |= lojas
            linha["valor_cobrado"] += Decimal(lead.valor_cobrar or 0)

    pagos = seta_client.valores_pagos_pos_cobranca(sorted(cobrancas), pago_de, pago_ate)

    try:
        nomes_loja = {l["filial"]: l.get("nome_com_cod") for l in lojas_base.listar_lojas(db)}
    except google_client.GoogleIndisponivel:
        nomes_loja = {}

    linhas = []
    for chave, c in cobrancas.items():
        p = pagos.get(chave)
        if not p:
            continue
        linhas.append(
            {
                "codigo_cliente": c["codigo_cliente"],
                "nome": c["nome"],
                "cpf": c["cpf"],
                "loja": ", ".join(nomes_loja.get(l) or l for l in sorted(c["lojas"])),
                "faixa": ", ".join(sorted(c["faixas"])),
                "data_cobranca": c["data_cobranca"],
                "valor_cobrado": c["valor_cobrado"].quantize(Decimal("0.01")),
                "valor_pago": Decimal(str(p["valor_pago"] or 0)).quantize(Decimal("0.01")),
                "qtd_titulos_pagos": int(p["qtd_titulos"]),
                "primeiro_pagamento": p["primeiro_pagamento"],
                "ultimo_pagamento": p["ultimo_pagamento"],
            }
        )
    linhas.sort(key=lambda l: (l["data_cobranca"], l["nome"] or ""), reverse=True)
    return linhas
