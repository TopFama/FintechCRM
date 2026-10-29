import asyncio
import calendar
import logging
import time
from datetime import date, timedelta
from decimal import Decimal
from typing import Literal

import redis
import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, HTTPException, Query, Response, WebSocket, WebSocketDisconnect, status
from sqlalchemy.orm import Session

from .. import models, schemas
from .. import cache, consultas_fila, painel_tempo_real
from ..services import custo_whatsapp, pagos_janela_service, painel_mensagens
from ..timezone import hoje_br
from ..config import settings
from ..database import SessionLocal, get_db
from ..deps import get_current_user, token_da_requisicao, usuario_do_token
from ..security import decode_access_token, origem_permitida
from ..utils.xlsx import XLSX_MEDIA_TYPE, build_xlsx

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


# A tela do Dashboard se atualiza sozinha (auto=true). Várias abas abertas no
# mesmo período fazem uma consulta só a cada TTL; abrir a tela, trocar o
# período ou clicar em "Atualizar agora" sempre recalcula.
RESUMO_TTL_SEGUNDOS = 15
ORCAMENTO_TTL_SEGUNDOS = 600


@router.get("/summary", response_model=schemas.DashboardSummary)
def summary(
    de: date | None = Query(None),
    ate: date | None = Query(None),
    auto: bool = Query(False),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    def calcular():
        return _resumo(db, de, ate).model_dump(mode="json")

    try:
        dados = cache.obter_ou_calcular(
            cache.chave("dashboard-resumo-v2", {"de": de, "ate": ate}), calcular, RESUMO_TTL_SEGUNDOS, reaproveitar=auto
        )
    except cache.CacheIndisponivel:
        # Sem Redis calcula direto: o resumo é só da fila local
        dados = _resumo(db, de, ate).model_dump(mode="json")
    return schemas.DashboardSummary(**dados)


# Fechamentos que a tela entende: período sem tempo real e sessão inválida não
# reconectam; o resto (backend reiniciando, Redis fora) tenta de novo depois.
WS_SEM_TEMPO_REAL = 4000
WS_NAO_AUTENTICADO = 4401
WS_SESSAO_A_CADA_SEGUNDOS = 30  # sessão encerrada (Sair, usuário excluído) para de receber em até isso


def _validar_sessao(token: str | None) -> None:
    with SessionLocal() as db:
        usuario_do_token(db, token)


@router.websocket("/ws")
async def tempo_real(websocket: WebSocket, de: date = Query(...), ate: date = Query(...)):
    """Cards da fila em tempo real (ver painel_tempo_real). A tela continua com
    o polling do /summary; isto só antecipa os números."""

    # o middleware de Host/Origin é só HTTP: o WebSocket confere aqui
    if not origem_permitida(websocket.url.hostname, websocket.headers.get("origin")):
        await websocket.close(code=1008)
        return
    token = token_da_requisicao(websocket, None)
    loop = asyncio.get_running_loop()

    def em_thread(funcao, *args):
        return loop.run_in_executor(painel_tempo_real.executor, funcao, *args)

    try:
        await em_thread(_validar_sessao, token)
    except HTTPException:
        # aceita antes de fechar: recusado no handshake o navegador só vê 403 e
        # 1006, e a tela reconectaria sem parar em vez de ler o 4401
        await websocket.accept()
        await websocket.close(code=WS_NAO_AUTENTICADO)
        return
    expira = decode_access_token(token)["exp"]
    await websocket.accept()
    cliente = redis_async.from_url(settings.redis_url, decode_responses=True)
    avisos = cliente.pubsub()
    codigo = WS_NAO_AUTENTICADO  # sai do laço sem break só quando a sessão vence
    try:
        await avisos.subscribe(painel_tempo_real.CANAL)
        enviado = None
        proxima_sessao = time.monotonic() + WS_SESSAO_A_CADA_SEGUNDOS
        while time.time() < expira:
            if time.monotonic() >= proxima_sessao:
                await em_thread(_validar_sessao, token)
                proxima_sessao = time.monotonic() + WS_SESSAO_A_CADA_SEGUNDOS
            atual = await em_thread(painel_tempo_real.numeros, de, ate)
            if atual is None:
                codigo = WS_SEM_TEMPO_REAL
                break
            # {} = dia sendo carregado pelo ouvinte: os números vêm no próximo aviso
            if atual and atual != enviado:
                await websocket.send_json(atual)
                enviado = atual
            if await avisos.get_message(ignore_subscribe_messages=True, timeout=25) is None:
                await websocket.send_json({})  # mantém a conexão viva no proxy
            else:
                await asyncio.sleep(1)  # junta a rajada de avisos (lote de envio) num envio só
                while await avisos.get_message(ignore_subscribe_messages=True, timeout=0):
                    pass
    except HTTPException:
        codigo = WS_NAO_AUTENTICADO
    except (painel_tempo_real.Indisponivel, cache.CacheIndisponivel, redis.RedisError):
        codigo = 1013
    except (WebSocketDisconnect, RuntimeError):
        return  # a tela fechou
    except Exception:  # noqa: BLE001 - a tela tenta de novo e, até lá, fica no polling
        logger.exception("Falha no Dashboard em tempo real")
        codigo = 1011
    finally:
        await avisos.aclose()
        await cliente.aclose()
    try:
        await websocket.close(code=codigo)
    except (WebSocketDisconnect, RuntimeError):
        pass  # a tela já tinha fechado


def _resumo(db: Session, de: date | None, ate: date | None) -> schemas.DashboardSummary:
    """Cards respeitam o período: enviado conta pela data do envio, o resto pela
    data em que entrou na fila."""

    periodo = consultas_fila.periodo_dos_cards(de, ate)

    return schemas.DashboardSummary(
        **consultas_fila.contar_cards(db, de, ate),
        total_pausados=consultas_fila.contar_pausados(db, periodo),
        total_telefones_invalidos=consultas_fila.contar_telefones_invalidos(db, de, ate),
    )


@router.get("/orcamento-progressao", response_model=schemas.OrcamentoProgressaoOut)
def orcamento_progressao(
    ano: int | None = Query(None, ge=2000, le=2100),
    mes: int | None = Query(None, ge=1, le=12),
    de: date | None = Query(None),
    ate: date | None = Query(None),
    auto: bool = Query(False),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Gasto real acumulado com WhatsApp (Meta, em BRL) vs. orçamento. Período
    = um mês (ano/mes, padrão o mês atual) ou personalizado (de/ate); no
    personalizado o orçado soma o orçamento de cada mês tocado."""

    inicio, fim = _periodo_orcamento(ano, mes, de, ate)

    def calcular():
        return _orcamento(db, inicio, fim).model_dump(mode="json")

    try:
        dados = cache.obter_ou_calcular(
            cache.chave("dashboard-orcamento", {"de": inicio, "ate": fim}),
            calcular,
            ORCAMENTO_TTL_SEGUNDOS,
            reaproveitar=auto,
            # Meta fora do ar ou sem permissão numa WABA: não segura o aviso por 10 min
            guardar_se=lambda d: d["valor_gasto_brl"] is not None and not d["avisos"],
        )
    except cache.CacheIndisponivel:
        dados = calcular()
    return schemas.OrcamentoProgressaoOut(**dados)


def _periodo_orcamento(ano, mes, de, ate) -> tuple[date, date]:
    if de or ate:
        if not (de and ate) or de > ate:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Informe data inicial e final válidas")
        return de, ate
    hoje = hoje_br()
    ano, mes = ano or hoje.year, mes or hoje.month
    return date(ano, mes, 1), date(ano, mes, calendar.monthrange(ano, mes)[1])


@router.get("/orcamento-progressao/exportar.xlsx")
def exportar_orcamento_por_dia(
    ano: int | None = Query(None, ge=2000, le=2100),
    mes: int | None = Query(None, ge=1, le=12),
    de: date | None = Query(None),
    ate: date | None = Query(None),
    categorias: list[Literal["utilitario", "marketing", "servico", "outras"]] = Query([]),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Gasto com WhatsApp por dia, WABA e número (mesmo período do card). Com
    categorias, conta só elas, como o filtro do gráfico; sem, o total da Meta."""

    inicio, fim = _periodo_orcamento(ano, mes, de, ate)
    custo = custo_whatsapp.custo_detalhado(db, inicio, fim)
    if custo.por_dia is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, custo.motivo or "Custo da Meta indisponível")
    por_dia_numero = custo.por_dia_numero
    if categorias:
        por_dia_numero = {
            (dia, waba, tel): [
                sum(custo.por_categoria.get((dia, tel, c), [Decimal("0"), 0])[i] for c in categorias) for i in (0, 1)
            ]
            for (dia, waba, tel) in por_dia_numero
        }
    linhas = [
        [dia, waba, telefone or "—", mensagens, float(gasto.quantize(Decimal("0.01")))]
        for (dia, waba, telefone), (gasto, mensagens) in sorted(por_dia_numero.items())
        if gasto or mensagens
    ]
    conteudo = build_xlsx(
        ["Data", "WABA", "Telefone", "Mensagens cobradas", "Valor cobrado (R$)"], linhas, {4: "#,##0.00"}
    )
    return Response(
        content=conteudo,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": f'attachment; filename="orcamento_por_dia_{inicio}_{fim}.xlsx"'},
    )


def _orcamento(db: Session, inicio: date, fim: date) -> schemas.OrcamentoProgressaoOut:
    meses = set()
    d = inicio.replace(day=1)
    while d <= fim:
        meses.add((d.year, d.month))
        d = (d + timedelta(days=32)).replace(day=1)
    valor_orcado = sum(
        (
            o.valor_orcado
            for o in db.query(models.OrcamentoMensal)
            if (o.ano, o.mes) in meses
        ),
        Decimal("0.00"),
    )

    custo = custo_whatsapp.custo_detalhado(db, inicio, fim)
    por_dia, motivo = custo.por_dia, custo.motivo
    dias: list[schemas.OrcamentoProgressaoDiaOut] = []
    valor_gasto_brl: Decimal | None = None
    if por_dia is not None:
        msgs_dia: dict[date, int] = {}
        for (dia, _waba, _tel), (_gasto, mensagens) in custo.por_dia_numero.items():
            msgs_dia[dia] = msgs_dia.get(dia, 0) + mensagens
        cat_dia = _somar_categorias(custo.por_categoria, lambda dia, _tel: dia)
        acumulado = Decimal("0.00")
        msgs = 0
        hoje = hoje_br()
        d = inicio
        while d <= fim:
            # Dia que ainda não aconteceu fica no eixo, mas sem valor: a linha pára em hoje
            if d > hoje:
                dias.append(schemas.OrcamentoProgressaoDiaOut(data=d, gasto_acumulado_brl=None))
            else:
                acumulado += por_dia.get(d, Decimal("0"))
                msgs += msgs_dia.get(d, 0)
                dias.append(
                    schemas.OrcamentoProgressaoDiaOut(
                        data=d,
                        gasto_acumulado_brl=acumulado.quantize(Decimal("0.01")),
                        mensagens_acumuladas=msgs,
                        por_categoria=cat_dia.get(d, {}),
                    )
                )
            d += timedelta(days=1)
        valor_gasto_brl = acumulado.quantize(Decimal("0.01"))
    cat_numero = _somar_categorias(custo.por_categoria, lambda _dia, tel: tel, Decimal("0.01"))
    msgs_numero: dict[str, int] = {}
    for (_dia, _waba, tel), (_gasto, mensagens) in custo.por_dia_numero.items():
        msgs_numero[tel] = msgs_numero.get(tel, 0) + mensagens

    return schemas.OrcamentoProgressaoOut(
        de=inicio,
        ate=fim,
        valor_orcado=valor_orcado,
        valor_gasto_brl=valor_gasto_brl,
        motivo_sem_gasto=motivo,
        dias=dias,
        avisos=[schemas.AvisoCustoWabaOut(waba_id=a.waba_id, numeros=a.numeros, motivo=a.motivo) for a in custo.avisos],
        gasto_por_numero=[
            schemas.GastoNumeroOut(
                numero=n,
                gasto_brl=v.quantize(Decimal("0.01")),
                qtd_mensagens=msgs_numero.get(n, 0),
                por_categoria=cat_numero.get(n, {}),
            )
            for n, v in sorted(custo.por_numero.items(), key=lambda kv: -kv[1])
        ],
    )


def _somar_categorias(por_categoria, agrupar, casas=Decimal("0.0001")) -> dict:
    """{grupo: {categoria: GastoCategoriaOut}} a partir de (dia, número, categoria)
    do custo da Meta; o grupo sai de agrupar(dia, número). O gasto do dia vai com
    4 casas para a soma das categorias no navegador bater com o total do dia."""

    somas: dict = {}
    for (dia, tel, categoria), (gasto, mensagens) in por_categoria.items():
        linha = somas.setdefault(agrupar(dia, tel), {}).setdefault(categoria, [Decimal("0"), 0])
        linha[0] += gasto
        linha[1] += mensagens
    return {
        g: {c: schemas.GastoCategoriaOut(gasto_brl=v.quantize(casas), qtd_mensagens=m) for c, (v, m) in cats.items()}
        for g, cats in somas.items()
    }


@router.get("/painel-mensagens", response_model=schemas.PainelMensagensOut)
def painel_mensagens_dashboard(
    de: date = Query(...),
    ate: date = Query(...),
    telefone: list[str] = Query([]),
    waba: list[str] = Query([]),
    template: list[str] = Query([]),
    campanha: str = Query(""),
    agrupar: Literal["template", "faixa", "campanha"] = Query("template"),
    tipo: list[Literal["marketing", "utilitario", "servico", "outras"]] = Query([]),
    auto: bool = Query(False),
    _user: models.User = Depends(get_current_user),
):
    """Mini-tabelas do analytics da Meta (em BRL) e a tabela por template, faixa
    de atraso ou campanha (`agrupar`), no
    período de/ate. Telefone = id do número. Com template ou campanha, os
    quadros vêm da fila (ver services/painel_mensagens)."""

    if de > ate:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Informe data inicial e final válidas")

    def calcular():
        # Sessão própria: a atualização em segundo plano roda depois da requisição
        with SessionLocal() as sessao:
            dados = painel_mensagens.montar(
                sessao, de, ate, telefones=telefone, wabas=waba, templates=template, campanha=campanha, agrupar=agrupar,
                tipos=tipo,
            )
        return schemas.PainelMensagensOut(**dados).model_dump(mode="json")

    filtros = dict(de=de, ate=ate, telefone=sorted(telefone), waba=sorted(waba), template=sorted(template), campanha=campanha, agrupar=agrupar, tipo=sorted(tipo))
    try:
        dados = cache.obter_snapshot(
            cache.chave("dashboard-painel-mensagens", filtros),
            calcular,
            painel_mensagens.PAINEL_TTL_SEGUNDOS,
            reaproveitar=auto,
            # Meta fora do ar ou sem permissão numa WABA: não segura o aviso por 10 min
            guardar_se=lambda d: not d["avisos"],
            velho=painel_mensagens.PAINEL_VELHO_SEGUNDOS,
        ).data
    except cache.CacheIndisponivel:
        dados = calcular()
    return schemas.PainelMensagensOut(**dados)


@router.get("/colunas-por-faixa", response_model=schemas.ColunasPorFaixa)
def colunas_por_faixa(user: models.User = Depends(get_current_user)):
    return schemas.ColunasPorFaixa(colunas=user.colunas_por_faixa or [])


@router.put("/colunas-por-faixa", response_model=schemas.ColunasPorFaixa)
def salvar_colunas_por_faixa(
    payload: schemas.ColunasPorFaixa,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Ordem das colunas da tabela do card Mensagens (por faixa) salva na conta: vale em qualquer
    navegador em que o usuário entrar."""
    user.colunas_por_faixa = payload.colunas or None
    db.commit()
    return payload


@router.get("/janela-pagamento", response_model=schemas.PagosJanelaOut)
def janela_pagamento(
    de: date | None = Query(None),
    ate: date | None = Query(None),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Clientes cobrados no período que pagaram dentro da janela configurada
    em Indicadores (regra da Tarefa 5). Usa a mesma lista em cache do relatório Quem
    pagou (5 min), então não consulta o SETA de novo para o mesmo período."""

    dados = pagos_janela_service.resumo(db, de, ate)
    return schemas.PagosJanelaOut(**dados)
