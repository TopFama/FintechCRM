from datetime import date, datetime, time, timedelta
import re
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import case, false, or_
from sqlalchemy.orm import Session

from .. import google_client, lojas as lojas_base, models, schemas, seta_client
from ..database import get_db
from ..fila_automatica import enfileirar_leads
from ..deps import get_current_user
from ..leads_service import _em_lotes, gerar_leads_de_clientes
from ..regras_db import carregar_regras
from ..timezone import BUSINESS_TZ, hoje_br
from ..utils.leads_xlsx import gerar_xlsx_leads
from .blacklist import codigos_bloqueados
from .cobranca import buscar_base_ou_erro, filtros_base, sem_cobrados_hoje

router = APIRouter(prefix="/leads", tags=["leads"])


@router.post("/gerar", response_model=schemas.LeadsGerarAsyncOut)
def gerar_leads(
    filtros: dict = Depends(filtros_base),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Transforma em leads os clientes da base de cobrança que passam nos
    filtros (os mesmos de `/cobranca/clientes`). Quem já é lead da mesma
    faixa e parcela não é duplicado.

    A base de cobrança pode levar minutos pra calcular na primeira vez (ver
    `cobranca_base.buscar_base`) — enquanto isso, devolve "processing" sem
    criar lead nenhum; quem pediu tenta de novo em seguida."""

    job = buscar_base_ou_erro(db, filtros)
    if job["status"] != "ready":
        return schemas.LeadsGerarAsyncOut(status="processing")
    clientes = sem_cobrados_hoje(db, job["data"])

    try:
        criados, ja_existiam, sem_celular = gerar_leads_de_clientes(db, clientes, created_by=user.id)
        na_fila = enfileirar_leads(db, clientes)
    except seta_client.SetaIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    return schemas.LeadsGerarAsyncOut(
        status="ready",
        data=schemas.LeadsGerarResult(
            criados=criados, ja_existiam=ja_existiam, sem_celular=sem_celular, na_fila=na_fila
        ),
    )


def _inicio_utc(dia: date) -> datetime:
    return datetime.combine(dia, time.min, BUSINESS_TZ).astimezone(ZoneInfo("UTC")).replace(tzinfo=None)


def filtrar_leads(
    db: Session,
    *,
    loja: list[str] | None = None,
    faixa: list[str] | None = None,
    cluster: list[str] | None = None,
    lead_status: str | None = None,
    busca: str | None = None,
    com_celular: bool | None = None,
    criado_de: date | None = None,
    criado_ate: date | None = None,
    enviado_de: date | None = None,
    enviado_ate: date | None = None,
):
    """Query de leads com os filtros da aba; também serve à exportação. Leads
    de clientes que entraram na blacklist depois de criados ficam de fora."""

    query = db.query(models.Lead)
    if loja is not None:
        if loja:
            query = query.filter(or_(*(models.Lead.lojas.contains(f",{codigo},") for codigo in loja)))
        else:
            query = query.filter(false())  # os atributos de loja escolhidos não casaram com nenhuma
    if faixa:
        query = query.filter(models.Lead.faixa.in_(faixa))
    if cluster:
        query = query.filter(models.Lead.cluster.in_(cluster))
    if lead_status:
        query = query.filter(models.Lead.status == lead_status)
    if busca:
        digitos = "".join(ch for ch in busca if ch.isdigit())
        condicoes = [models.Lead.nome.ilike(f"%{busca.strip()}%")]
        if digitos:
            condicoes += [models.Lead.codigo_cliente.contains(digitos), models.Lead.cpf.contains(digitos)]
        query = query.filter(or_(*condicoes))
    if com_celular is True:
        query = query.filter(models.Lead.celular.isnot(None))
    elif com_celular is False:
        query = query.filter(models.Lead.celular.is_(None))
    # Datas do filtro são dias em GMT-3; o banco guarda UTC
    if criado_de:
        query = query.filter(models.Lead.created_at >= _inicio_utc(criado_de))
    if criado_ate:
        query = query.filter(models.Lead.created_at < _inicio_utc(criado_ate + timedelta(days=1)))
    if enviado_de:
        query = query.filter(models.Lead.cobrado_em >= _inicio_utc(enviado_de))
    if enviado_ate:
        query = query.filter(models.Lead.cobrado_em < _inicio_utc(enviado_ate + timedelta(days=1)))

    bl_codigos, bl_cpfs = codigos_bloqueados(db)
    if bl_codigos:
        query = query.filter(models.Lead.codigo_cliente.notin_(bl_codigos))
    if bl_cpfs:
        query = query.filter(or_(models.Lead.cpf.is_(None), models.Lead.cpf.notin_(bl_cpfs)))
    return query


def filtros_consulta_leads(
    loja: list[str] | None = Query(None, description="Código da loja do título"),
    regional: list[str] | None = Query(None),
    estado: list[str] | None = Query(None),
    cluster_inad: list[str] | None = Query(None),
    cluster_populacao: list[str] | None = Query(None),
    cobradora: list[str] | None = Query(None),
    faixa: list[str] | None = Query(None),
    cluster: list[str] | None = Query(None),
    busca: str | None = Query(None, description="Nome, código ou CPF"),
    com_celular: bool | None = Query(None),
    criado_de: date | None = Query(None),
    criado_ate: date | None = Query(None),
    enviado_de: date | None = Query(None, description="Data do envio (cobrado_em), GMT-3"),
    enviado_ate: date | None = Query(None),
) -> dict:
    return {
        "loja": loja,
        "regional": regional,
        "estado": estado,
        "cluster_inad": cluster_inad,
        "cluster_populacao": cluster_populacao,
        "cobradora": cobradora,
        "faixa": faixa,
        "cluster": cluster,
        "busca": busca,
        "com_celular": com_celular,
        "criado_de": criado_de,
        "criado_ate": criado_ate,
        "enviado_de": enviado_de,
        "enviado_ate": enviado_ate,
    }


def query_leads_filtrada(db: Session, filtros: dict, lead_status: str | None):
    try:
        codigos_loja = lojas_base.combinar_lojas(
            db,
            filtros["loja"],
            regional=filtros["regional"],
            estado=filtros["estado"],
            cluster_inad=filtros["cluster_inad"],
            cluster_populacao=filtros["cluster_populacao"],
            cobradora=filtros["cobradora"],
        )
    except google_client.GoogleIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return filtrar_leads(
        db,
        loja=codigos_loja,
        faixa=filtros["faixa"],
        cluster=filtros["cluster"],
        lead_status=lead_status,
        busca=filtros["busca"],
        com_celular=filtros["com_celular"],
        criado_de=filtros["criado_de"],
        criado_ate=filtros["criado_ate"],
        enviado_de=filtros["enviado_de"],
        enviado_ate=filtros["enviado_ate"],
    )


def _nome_faixas_arquivo(faixas: list[str] | None) -> str:
    if not faixas:
        return "todas"
    limpos = [re.sub(r"[^A-Za-z0-9+-]", "", f) for f in faixas]
    limpos = [f for f in limpos if f]
    return "_".join(limpos) if limpos else "todas"


@router.get("/exportar.xlsx")
def exportar_leads_xlsx(
    filtros: dict = Depends(filtros_consulta_leads),
    lead_status: str | None = Query("cobrado", alias="status", pattern="^(novo|cobrado)$"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Exporta os leads para planilha Excel (.xlsx) com colunas Codigo, Nome, Celular e CPF."""
    query = query_leads_filtrada(db, filtros, lead_status)
    regras = carregar_regras(db)
    nomes_faixa = regras.nomes_faixa

    if nomes_faixa:
        ordem_faixa = case(
            {nome: i for i, nome in enumerate(nomes_faixa)},
            value=models.Lead.faixa,
            else_=len(nomes_faixa),
        )
        leads = query.order_by(ordem_faixa, models.Lead.nome).all()
    else:
        leads = query.order_by(models.Lead.nome).all()

    ordem_map = {n: i for i, n in enumerate(nomes_faixa)}
    leads.sort(key=lambda l: (ordem_map.get(l.faixa, len(nomes_faixa)), l.nome or ""))

    conteudo = gerar_xlsx_leads(leads)
    nome_faixas = _nome_faixas_arquivo(filtros["faixa"])
    hoje = hoje_br().isoformat()
    filename = f"leads_{nome_faixas}_{hoje}.xlsx"

    return Response(
        content=conteudo,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


LeadSortColumn = Literal[
    "codigo_cliente",
    "cpf",
    "nome",
    "celular",
    "vencimento_mais_antigo",
    "valor_cobrar",
    "qtd_parcelas",
    "dias_atraso",
    "faixa",
    "cluster",
    "status",
    "cobrado_em",
]

_LEAD_SORT_COLUNAS = {
    "codigo_cliente": models.Lead.codigo_cliente,
    "cpf": models.Lead.cpf,
    "nome": models.Lead.nome,
    "celular": models.Lead.celular,
    "vencimento_mais_antigo": models.Lead.vencimento_mais_antigo,
    "valor_cobrar": models.Lead.valor_cobrar,
    "qtd_parcelas": models.Lead.qtd_parcelas,
    "dias_atraso": models.Lead.dias_atraso,
    "cluster": models.Lead.cluster,
    "status": models.Lead.status,
    "cobrado_em": models.Lead.cobrado_em,
}


def _lead_sort_coluna(db: Session, sort_by: str):
    """Coluna (ou expressão) usada em ORDER BY. `faixa` ordena pela progressão
    do atraso (mesma ordem de `RegrasCobranca.faixas`), não alfabeticamente."""
    if sort_by == "faixa":
        nomes_faixa = carregar_regras(db).nomes_faixa
        if not nomes_faixa:
            return models.Lead.faixa
        return case({nome: i for i, nome in enumerate(nomes_faixa)}, value=models.Lead.faixa, else_=len(nomes_faixa))
    return _LEAD_SORT_COLUNAS.get(sort_by)


@router.get("", response_model=schemas.LeadsPage)
def listar_leads(
    filtros: dict = Depends(filtros_consulta_leads),
    lead_status: str | None = Query(None, alias="status", pattern="^(novo|cobrado)$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: LeadSortColumn | None = Query(None),
    sort_dir: Literal["asc", "desc"] = Query("asc"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    query = query_leads_filtrada(db, filtros, lead_status)
    total = query.count()
    coluna = _lead_sort_coluna(db, sort_by) if sort_by else None
    if coluna is not None:
        # id como desempate: mantém a ordem estável entre páginas
        query = query.order_by(coluna.desc() if sort_dir == "desc" else coluna.asc(), models.Lead.id)
    else:
        query = query.order_by(models.Lead.created_at.desc(), models.Lead.dias_atraso.desc(), models.Lead.codigo_cliente)
    itens = query.offset(offset).limit(limit).all()
    return schemas.LeadsPage(total=total, itens=itens)



@router.post("/marcar-cobrados", response_model=dict)
def marcar_cobrados(
    payload: schemas.LeadsMarcarCobrados,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    agora = datetime.utcnow()
    atualizados = 0
    for lote in _em_lotes(payload.ids):
        atualizados += (
            db.query(models.Lead)
            .filter(models.Lead.id.in_(lote), models.Lead.status != "cobrado")
            .update({"status": "cobrado", "cobrado_em": agora}, synchronize_session=False)
        )
    db.commit()
    return {"atualizados": atualizados}


@router.post("/enfileirar-pendentes", response_model=dict)
def enfileirar_pendentes_de_hoje(
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Coloca na fila de disparo os leads pendentes gerados hoje (horário de
    Brasília) — para os que foram gerados antes de "Gerar leads" já enfileirar.
    Mesma regra de sempre: não duplica quem já está na fila ou foi cobrado hoje."""

    leads_hoje = (
        db.query(models.Lead.codigo_cliente, models.Lead.faixa, models.Lead.vencimento_mais_antigo)
        .filter(models.Lead.status == "novo", models.Lead.created_at >= _inicio_utc(hoje_br()))
        .all()
    )
    clientes = [{"codigo": c, "faixa": f, "vencimento_mais_antigo": v} for c, f, v in leads_hoje]
    return {"pendentes": len(clientes), "na_fila": enfileirar_leads(db, clientes)}


@router.post("/excluir", response_model=dict)
def excluir_leads(
    payload: schemas.LeadsExcluir,
    filtros: dict = Depends(filtros_consulta_leads),
    lead_status: str | None = Query(None, alias="status", pattern="^(novo|cobrado)$"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Exclui leads ainda não enviados. Com `ids`, exclui só esses; sem
    `ids`, exclui todos que casam com os filtros aplicados na tela. Nunca
    exclui lead já marcado como enviado (histórico usado na Efetividade)."""

    if payload.ids:
        base = db.query(models.Lead).filter(models.Lead.id.in_(payload.ids))
        ja_enviados = base.filter(models.Lead.status != "novo").count()
        if ja_enviados:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"{ja_enviados} lead(s) selecionado(s) já foram enviados e não podem ser excluídos. "
                "Selecione só leads pendentes.",
            )
    else:
        base = query_leads_filtrada(db, filtros, lead_status)

    total_alvo = base.count()
    excluidos = base.filter(models.Lead.status == "novo").delete(synchronize_session=False)
    db.commit()
    return {"excluidos": excluidos, "ignorados_ja_enviados": total_alvo - excluidos}
