"""Cópia local das baixas do SETA de quem já foi cobrado.

Dashboard, Efetividade e Quem pagou precisam saber, por (cliente, data da
cobrança), se o cliente quitou algum título depois e quanto entrou. Antes isso
ia ao SETA (produção) a cada tela aberta; agora vem da tabela pagamentos_seta,
e o SETA só é lido aqui, de forma incremental:

- cliente cobrado pela primeira vez: busca as baixas dele desde a primeira
  cobrança (na hora em que uma tela precisa dele, ou na rodada do worker);
- rodada do worker (só com alguém usando o CRM, no máximo 1 a cada 30 min):
  relê as baixas de cada cliente a partir da marca d'água dele (última
  leitura) menos SOBREPOSICAO_DIAS, pra pegar baixa lançada com
  data retroativa e estorno recente. Cliente sem cobrança nos últimos
  JANELA_ATIVA_DIAS é relido só uma vez por dia.
"""

import logging
import threading
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, seta_client
from ..timezone import BUSINESS_TZ, hoje_br

logger = logging.getLogger(__name__)

SOBREPOSICAO_DIAS = 7
# Cliente com cobrança nos últimos N dias é relido em toda rodada; os demais, uma vez por dia
JANELA_ATIVA_DIAS = 60
LOTE = 1000

# Um processo só (worker e rotas no mesmo backend): evita duas cópias ao mesmo tempo
_trava = threading.Lock()

# A rodada do worker só acontece com alguém usando o CRM: sem ninguém, o SETA
# não é lido. Relógio monotônico do processo; zera quando o backend reinicia.
ATIVIDADE_JANELA_SEGUNDOS = 15 * 60
_ultima_atividade: float | None = None
_ultima_rodada: float | None = None


def registrar_atividade() -> None:
    """Chamado a cada requisição autenticada de um usuário (ver deps.py)."""
    global _ultima_atividade
    _ultima_atividade = time.monotonic()


def rodada_devida(intervalo_segundos: int) -> bool:
    """Alguém usou o CRM nos últimos ATIVIDADE_JANELA_SEGUNDOS e a última
    rodada completa foi há mais de `intervalo_segundos` (ou nunca houve)."""
    agora = time.monotonic()
    if _ultima_atividade is None or agora - _ultima_atividade > ATIVIDADE_JANELA_SEGUNDOS:
        return False
    return _ultima_rodada is None or agora - _ultima_rodada >= intervalo_segundos


def _dia_br(dt: datetime) -> date:
    return dt.replace(tzinfo=ZoneInfo("UTC")).astimezone(BUSINESS_TZ).date()


def _cobrancas(db: Session, codigos: set[str] | None = None) -> dict[str, tuple[date, date]]:
    """codigo_cliente → (primeira, última) data de cobrança, no fuso de negócio."""
    query = db.query(
        models.Lead.codigo_cliente, func.min(models.Lead.cobrado_em), func.max(models.Lead.cobrado_em)
    ).filter(
        models.Lead.status == "cobrado", models.Lead.cobrado_em.isnot(None)
    )
    resultado: dict[str, tuple[date, date]] = {}
    if codigos is None:
        lotes = [None]
    else:
        lista = sorted(codigos)
        lotes = [lista[i : i + LOTE] for i in range(0, len(lista), LOTE)]
    for lote in lotes:
        q = query if lote is None else query.filter(models.Lead.codigo_cliente.in_(lote))
        for codigo, primeira, ultima in q.group_by(models.Lead.codigo_cliente):
            resultado[codigo] = (_dia_br(primeira), _dia_br(ultima))
    return resultado


def _em_lotes(itens: list, tamanho: int = LOTE):
    for i in range(0, len(itens), tamanho):
        yield itens[i : i + tamanho]


def sincronizar(db: Session, codigos: set[str] | None = None) -> int:
    """Sem `codigos`: rodada completa (novos inteiros + incremental dos já
    copiados). Com `codigos`: só busca, desses, os que ainda não foram
    copiados; se todos já foram, não toca o SETA. Devolve quantos títulos
    vieram do SETA. Levanta seta_client.SetaIndisponivel."""

    if codigos is not None:
        # Tela aberta: só importa quem ainda não foi copiado. Cobrança anterior à
        # cópia de quem já foi copiado fica pra rodada completa (a cada 30 min).
        # Lista inteira numa leitura: IN com mil códigos já varre a tabela
        # (pequena) de qualquer jeito, uma vez por lote
        ja_copiados = {c for (c,) in db.query(models.PagamentoSetaCliente.codigo_cliente)}
        codigos = set(codigos) - ja_copiados
        if not codigos:
            return 0

    with _trava:
        hoje = hoje_br()
        cobrancas = _cobrancas(db, codigos)
        cobrados = {c: primeira for c, (primeira, _) in cobrancas.items()}
        if codigos is None:
            copiados = {c.codigo_cliente: c for c in db.query(models.PagamentoSetaCliente) if c.codigo_cliente in cobrados}
        else:
            copiados = {
                c.codigo_cliente: c
                for lote in _em_lotes(sorted(cobrados))
                for c in db.query(models.PagamentoSetaCliente).filter(
                    models.PagamentoSetaCliente.codigo_cliente.in_(lote)
                )
            }
        # Cliente novo (ou com cobrança anterior ao que já foi copiado): lê tudo desde a primeira cobrança
        leituras = {c: d for c, d in cobrados.items() if c not in copiados or d < copiados[c].desde}
        if codigos is None:
            ativos_desde = hoje - timedelta(days=JANELA_ATIVA_DIAS)
            for c, copia in copiados.items():
                # Cobrado há muito tempo: basta reler uma vez por dia
                if c not in leituras and (cobrancas[c][1] >= ativos_desde or copia.marca_dagua < hoje):
                    leituras[c] = max(copia.desde, copia.marca_dagua - timedelta(days=SOBREPOSICAO_DIAS))
        if codigos is None:
            global _ultima_rodada
            _ultima_rodada = time.monotonic()
        if not leituras:
            if codigos is None:
                logger.info("Pagamentos do SETA (rodada): nenhum cliente a reler")
            return 0

        t0 = time.monotonic()
        baixas = seta_client.baixas_de_clientes(sorted(leituras.items()))
        segundos_seta = time.monotonic() - t0

        # Troca o trecho relido pelo que o SETA respondeu agora (some o que foi estornado)
        por_inicio: dict[date, list[str]] = defaultdict(list)
        for c, inicio in leituras.items():
            por_inicio[inicio].append(c)
        for inicio, clientes in por_inicio.items():
            for lote in _em_lotes(sorted(clientes)):
                db.query(models.PagamentoSeta).filter(
                    models.PagamentoSeta.codigo_cliente.in_(lote), models.PagamentoSeta.pagamento >= inicio
                ).delete(synchronize_session=False)
        por_titulo = {b["titulo_codigo"]: b for b in baixas}
        for lote in _em_lotes(sorted(por_titulo)):
            db.query(models.PagamentoSeta).filter(models.PagamentoSeta.titulo_codigo.in_(lote)).delete(
                synchronize_session=False
            )
        db.bulk_insert_mappings(
            models.PagamentoSeta,
            [
                {
                    "titulo_codigo": b["titulo_codigo"],
                    "codigo_cliente": b["codigo_cliente"],
                    "pagamento": b["pagamento"],
                    "valor": Decimal(str(b["valor"] or 0)),
                    "rp": b["rp"] or "",
                    "pago_em": b.get("pago_em"),
                }
                for b in por_titulo.values()
            ],
        )
        for codigo in leituras:
            copia = copiados.get(codigo)
            if copia is None:
                db.add(models.PagamentoSetaCliente(codigo_cliente=codigo, desde=cobrados[codigo], marca_dagua=hoje))
            else:
                copia.desde = min(copia.desde, cobrados[codigo])
                copia.marca_dagua = hoje
        db.commit()
        logger.info(
            "Pagamentos do SETA sincronizados (%s): %d clientes em %d consulta(s), %d títulos, SETA %.1f s, total %.1f s",
            "rodada" if codigos is None else "clientes novos",
            len(leituras), len(seta_client.plano_baixas(sorted(leituras.items()), hoje)), len(por_titulo),
            segundos_seta, time.monotonic() - t0,
        )
        return len(por_titulo)


def _inicio_dia_utc(dia: date) -> datetime:
    """Meia-noite de Brasília do dia, em UTC ingênuo (como `cobrado_em` é gravado)."""
    return datetime.combine(dia, datetime.min.time(), BUSINESS_TZ).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def _horarios_envio(db: Session, pares: list[tuple[str, date]]) -> dict[tuple[str, date], datetime]:
    """(codigo_cliente, data_cobranca) → primeiro envio naquele dia, na hora de
    Brasília (mesma referência do horário do caixa do SETA)."""
    if not pares:
        return {}
    codigos = {c for c, _ in pares}
    dias = [d for _, d in pares]
    horarios: dict[tuple[str, date], datetime] = {}
    # Só os dias das cobranças pedidas (índice de cobrado_em); filtra os clientes aqui
    for codigo, cobrado_em in db.query(models.Lead.codigo_cliente, models.Lead.cobrado_em).filter(
        models.Lead.status == "cobrado",
        models.Lead.cobrado_em >= _inicio_dia_utc(min(dias)),
        models.Lead.cobrado_em < _inicio_dia_utc(max(dias) + timedelta(days=1)),
    ):
        if codigo not in codigos:
            continue
        local = cobrado_em.replace(tzinfo=ZoneInfo("UTC")).astimezone(BUSINESS_TZ).replace(tzinfo=None)
        chave = (codigo, local.date())
        if chave not in horarios or local < horarios[chave]:
            horarios[chave] = local
    return horarios


def _baixas_por_cliente(
    db: Session, pares: list[tuple[str, date]], buscar_novos: bool, ate: date | None = None
) -> dict[str, list]:
    """Baixas copiadas dos clientes, só a partir da cobrança mais antiga pedida
    (e até `ate`): antes disso nenhuma conta, e o histórico inteiro pesa."""
    codigos = {c for c, _ in pares}
    # Quem foi cobrado depois da última rodada ainda não está copiado: busca só esses
    if buscar_novos:
        sincronizar(db, codigos)
    inicio = min(d for _, d in pares)
    colunas = (
        models.PagamentoSeta.codigo_cliente,
        models.PagamentoSeta.pagamento,
        models.PagamentoSeta.valor,
        models.PagamentoSeta.rp,
        models.PagamentoSeta.pago_em,
    )
    # Uma leitura só pelo intervalo de datas, filtrando os clientes aqui: a cópia
    # é pequena, e cliente IN (...) + data em lotes fazia o Postgres escolher o
    # índice de data e varrer o período inteiro a cada lote.
    q = db.query(*colunas).filter(models.PagamentoSeta.pagamento >= inicio)
    if ate is not None:
        q = q.filter(models.PagamentoSeta.pagamento <= ate)
    baixas: dict[str, list] = defaultdict(list)
    for b in q:
        if b.codigo_cliente in codigos:
            baixas[b.codigo_cliente].append(b)
    return baixas


def _na_janela(
    b: models.PagamentoSeta, data_cobranca: date, dias_janela: int | None, envio: datetime | None = None
) -> bool:
    if b.pagamento < data_cobranca:
        return False
    # Pago no dia da cobrança, antes da mensagem sair: não foi efeito da cobrança.
    # Sem horário do caixa (baixa fora da loja) não dá pra saber e continua valendo.
    if b.pagamento == data_cobranca and b.pago_em is not None and envio is not None and b.pago_em < envio:
        return False
    return dias_janela is None or b.pagamento <= data_cobranca + timedelta(days=dias_janela)


def analisar_pos_cobranca(
    db: Session,
    pares: list[tuple[str, date]],
    dias_janela: int | None = None,
    pago_de: date | None = None,
    pago_ate: date | None = None,
    buscar_novos: bool = True,
) -> tuple[dict[tuple[str, date], date], dict[tuple[str, date], dict]]:
    """Pra cada (codigo_cliente, data_cobranca): (1) a primeira data em que o
    cliente quitou QUALQUER título (status 'B') a partir da cobrança (e até
    data_cobranca + dias_janela, se informado) — só entra quem pagou; (2) quanto
    pagou: soma dos títulos a receber (rp 'R', valor > 0) quitados na mesma
    janela e dentro de [pago_de, pago_ate]. Lê baixas e horários uma vez só.
    `buscar_novos=False` não vai ao SETA nem para cliente ainda não copiado."""

    if not pares:
        return {}, {}
    # Com janela, nada depois da última cobrança + janela conta
    ate = max(d for _, d in pares) + timedelta(days=dias_janela) if dias_janela is not None else None
    baixas = _baixas_por_cliente(db, pares, buscar_novos, ate)
    envios = _horarios_envio(db, pares)
    pagou: dict[tuple[str, date], date] = {}
    valores: dict[tuple[str, date], dict] = {}
    for codigo, data_cobranca in pares:
        envio = envios.get((codigo, data_cobranca))
        na_janela = [b for b in baixas.get(codigo, []) if _na_janela(b, data_cobranca, dias_janela, envio)]
        if not na_janela:
            continue
        pagou[(codigo, data_cobranca)] = min(b.pagamento for b in na_janela)
        titulos = [
            b
            for b in na_janela
            if b.rp == "R"
            and b.valor > 0
            and (pago_de is None or b.pagamento >= pago_de)
            and (pago_ate is None or b.pagamento <= pago_ate)
        ]
        if titulos:
            valores[(codigo, data_cobranca)] = {
                "valor_pago": sum((Decimal(str(b.valor)) for b in titulos), Decimal("0")),
                "qtd_titulos": len(titulos),
                "primeiro_pagamento": min(b.pagamento for b in titulos),
                "ultimo_pagamento": max(b.pagamento for b in titulos),
            }
    return pagou, valores


def pagamentos_pos_cobranca(
    db: Session, pares: list[tuple[str, date]], dias_janela: int | None = None, buscar_novos: bool = True
) -> dict[tuple[str, date], date]:
    """Só a primeira parte de analisar_pos_cobranca (quem pagou e quando)."""
    return analisar_pos_cobranca(db, pares, dias_janela, buscar_novos=buscar_novos)[0]


def valores_pagos_pos_cobranca(
    db: Session,
    pares: list[tuple[str, date]],
    pago_de: date | None = None,
    pago_ate: date | None = None,
    dias_janela: int | None = None,
    buscar_novos: bool = True,
) -> dict[tuple[str, date], dict]:
    """Só a segunda parte de analisar_pos_cobranca (quanto pagou)."""
    return analisar_pos_cobranca(db, pares, dias_janela, pago_de, pago_ate, buscar_novos)[1]
