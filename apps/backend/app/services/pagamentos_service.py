"""Relatório de quem pagou o que foi cobrado, por cliente: leads cobrados no
período de cobrança cruzados com as baixas do SETA copiadas em pagamentos_seta."""

from datetime import date
from decimal import Decimal

from sqlalchemy import and_
from sqlalchemy.orm import Session

from .. import cache, consultas_fila, google_client, lojas as lojas_base, models
from ..database import SessionLocal
from . import pagamentos_seta
from ..timezone import dia_br


def condicao_cobrados(cobrado_de: date | None, cobrado_ate: date | None):
    """Lead cobrado no período: a base de clientes_que_pagaram e, por isso,
    também dos clientes cobrados e da Frequência do Dashboard."""

    ini, fim = consultas_fila.limites_utc(cobrado_de, cobrado_ate)
    return and_(
        models.Lead.status == "cobrado",
        models.Lead.cobrado_em.isnot(None),
        consultas_fila.condicao_periodo(models.Lead.cobrado_em, ini, fim),
    )


def clientes_cobrados_por_faixa(
    db: Session, *, cobrado_de: date | None, cobrado_ate: date | None
) -> dict[str, set[str]]:
    """Clientes distintos cobrados no período, por faixa do lead: quem pagou
    numa faixa sempre está aqui."""

    por_faixa: dict[str, set[str]] = {}
    for faixa, codigo in (
        db.query(models.Lead.faixa, models.Lead.codigo_cliente)
        .filter(condicao_cobrados(cobrado_de, cobrado_ate))
        .distinct()
    ):
        por_faixa.setdefault(faixa, set()).add(codigo)
    return por_faixa


def clientes_que_pagaram(
    db: Session,
    *,
    cobrado_de: date | None = None,
    cobrado_ate: date | None = None,
    pago_de: date | None = None,
    pago_ate: date | None = None,
    faixa: list[str] | None = None,
    dias_janela: int | None = None,
    campanha: str | None = None,
    buscar_novos: bool = True,
) -> list[dict]:
    """Uma linha por cliente e data de cobrança, só de quem pagou. Com
    `dias_janela`, "pagou" segue exatamente pagamentos_seta.pagamentos_pos_cobranca
    (quitou qualquer título até data_cobranca + dias_janela), a mesma regra do
    Relatório de Efetividade e do card do Dashboard. Levanta
    seta_client.SetaIndisponivel se o SETA estiver fora (com `buscar_novos`,
    o padrão, quando algum cliente ainda não foi copiado do SETA)."""

    query = db.query(models.Lead).filter(condicao_cobrados(cobrado_de, cobrado_ate))
    if faixa:
        query = query.filter(models.Lead.faixa.in_(faixa))
    if campanha:
        # "regua" = cobranças da régua; id = clientes daquela campanha (como na Efetividade)
        query = query.filter(models.Lead.campanha_id == ("" if campanha == "regua" else campanha))

    # Mesmo cliente em mais de um lead no mesmo dia (faixas/vencimentos
    # diferentes) vira uma linha só, somando o valor cobrado.
    cobrancas: dict[tuple[str, date], dict] = {}
    for lead in query.all():
        chave = (lead.codigo_cliente, dia_br(lead.cobrado_em))
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

    pares = sorted(cobrancas)
    pagou, pagos = pagamentos_seta.analisar_pos_cobranca(db, pares, dias_janela, pago_de, pago_ate, buscar_novos)
    na_janela = pagou if dias_janela is not None else None

    try:
        nomes_loja = {l["filial"]: l.get("nome_com_cod") for l in lojas_base.listar_lojas(db)}
    except google_client.GoogleIndisponivel:
        nomes_loja = {}

    linhas = []
    for chave, c in cobrancas.items():
        p = pagos.get(chave)
        if na_janela is not None:
            data_pagou = na_janela.get(chave)
            if data_pagou is None or (pago_de and not p) or (pago_ate and not p):
                continue
            # quitou algo fora de contas a receber (sem valor): conta como pagou, valor zero
            p = p or {"valor_pago": 0, "qtd_titulos": 0, "primeiro_pagamento": data_pagou, "ultimo_pagamento": data_pagou}
        elif not p:
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


# 5 min frescos; o Quem pagou ainda serve a lista por mais 30 min (marcada
# desatualizada) enquanto uma só atualização roda em segundo plano, ou se o SETA falha.
PAGAMENTOS_TTL_SEGUNDOS = 300
PAGAMENTOS_VELHO_SEGUNDOS = 1800
_CAMPOS_DATA = ("data_cobranca", "primeiro_pagamento", "ultimo_pagamento")


def snapshot_pagamentos(
    *,
    cobrado_de: date | None = None,
    cobrado_ate: date | None = None,
    pago_de: date | None = None,
    pago_ate: date | None = None,
    faixa: list[str] | None = None,
    dias_janela: int | None = None,
    campanha: str | None = None,
    velho: int = 0,
) -> cache.Snapshot:
    """`clientes_que_pagaram` no Redis por conjunto de filtros, compartilhado
    entre usuários e telas: ordenar, paginar, exportar e o card "Pagaram em até 7
    dias" (mesmos filtros) leem a mesma lista sem refazer nada. `velho` é por
    quanto tempo, depois dos 5 min, ainda se serve a lista enquanto ela é
    atualizada. Levanta o que o cache e o SETA levantam."""

    filtros = dict(
        cobrado_de=cobrado_de, cobrado_ate=cobrado_ate, pago_de=pago_de, pago_ate=pago_ate, faixa=faixa,
        dias_janela=dias_janela, campanha=campanha,
    )

    def calcular():
        # pode rodar em segundo plano depois da requisição: sessão própria
        with SessionLocal() as db:
            return clientes_que_pagaram(db, **filtros)

    snap = cache.obter_snapshot(
        cache.chave("relatorio-pagamentos", filtros), calcular, ttl_segundos=PAGAMENTOS_TTL_SEGUNDOS, velho=velho
    )
    # o Redis guarda JSON: devolve datas e valores aos tipos originais
    for l in snap.data:
        for campo in _CAMPOS_DATA:
            if isinstance(l.get(campo), str):
                l[campo] = date.fromisoformat(l[campo])
        for campo in ("valor_cobrado", "valor_pago"):
            l[campo] = Decimal(str(l[campo]))
    return snap


COLUNAS_ORDENAVEIS = (
    "codigo_cliente", "nome", "loja", "faixa", "data_cobranca", "valor_cobrado", "valor_pago", "primeiro_pagamento",
)


def ordenar(linhas: list[dict], sort_by: str, sort_dir: str, faixas_ordem: list[str]) -> list[dict]:
    """Ordena o resultado inteiro antes da paginação. `faixa` segue a ordem de
    atraso (com mais de uma faixa, vale a menor); vazios vão sempre para o fim."""

    ordem = {nome: i for i, nome in enumerate(faixas_ordem)}

    def valor(l: dict):
        v = l.get(sort_by)
        if sort_by == "faixa":
            return min((ordem.get(f, len(ordem)) for f in (v or "").split(", ") if f), default=None)
        return v.upper() if isinstance(v, str) else v

    preenchidas = sorted((l for l in linhas if valor(l) is not None), key=valor, reverse=sort_dir == "desc")
    return preenchidas + [l for l in linhas if valor(l) is None]
