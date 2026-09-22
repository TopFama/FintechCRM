from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import false, or_
from sqlalchemy.orm import Session

from .. import google_client, lojas as lojas_base, models, schemas, seta_client
from ..database import get_db
from ..deps import get_current_user
from ..utils.spc import parse_spc
from .blacklist import codigos_bloqueados
from .cobranca import buscar_base_ou_erro, filtros_base

router = APIRouter(prefix="/leads", tags=["leads"])

LOTE = 1000  # tamanho dos lotes de IN (...) ao consultar o banco


def _em_lotes(itens: list, tamanho: int = LOTE):
    for i in range(0, len(itens), tamanho):
        yield itens[i : i + tamanho]


@router.post("/gerar", response_model=schemas.LeadsGerarResult)
def gerar_leads(
    filtros: dict = Depends(filtros_base),
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Transforma em leads os clientes da base de cobrança que passam nos
    filtros (os mesmos de `/cobranca/clientes`). Quem já é lead da mesma
    faixa e parcela não é duplicado."""

    clientes = buscar_base_ou_erro(db, filtros)

    ja_existem: set[tuple[str, str, date]] = set()
    for lote in _em_lotes([c["codigo"] for c in clientes]):
        rows = db.query(
            models.Lead.codigo_cliente, models.Lead.faixa, models.Lead.vencimento_mais_antigo
        ).filter(models.Lead.codigo_cliente.in_(lote))
        ja_existem.update((r[0], r[1], r[2]) for r in rows)

    novos = [c for c in clientes if (c["codigo"], c["faixa"], c["vencimento_mais_antigo"]) not in ja_existem]

    # a data da consulta SPC só existe no texto bruto: busca só de quem vira lead
    datas_spc: dict[str, date | None] = {}
    try:
        for lote in _em_lotes([c["codigo"] for c in novos], 5000):
            for codigo, texto in seta_client.buscar_spc(lote).items():
                datas_spc[codigo] = parse_spc(texto)[1]
    except seta_client.SetaIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    db.add_all(
        models.Lead(
            codigo_cliente=c["codigo"],
            nome=c["nome"],
            cpf=c["cpfcnpj"],
            celular=c["celular"],
            celular_origem=c["celular_origem"],
            celular_original=c["celular_original"],
            cluster=c["cluster"],
            faixa=c["faixa"],
            faixa_compra=c["faixa_compra"],
            qtd_compras=c["qtd_compras"],
            dias_atraso=c["dias_atraso"],
            qtd_parcelas=c["qtd_parcelas_cobranca"],
            valor_em_aberto=c["valor_em_aberto"],
            valor_cobrar=c["valor_cobrar"],
            vencimento_mais_antigo=c["vencimento_mais_antigo"],
            lojas="," + ",".join(c["lojas"]) + ",",
            portadores="," + ",".join(c["portadores"]) + ",",
            status_cliente=c["status"],
            spc_restricao=c["spc_restricao"],
            spc_data_consulta=datas_spc.get(c["codigo"]),
            created_by=user.id,
        )
        for c in novos
    )
    db.commit()
    return schemas.LeadsGerarResult(
        criados=len(novos),
        ja_existiam=len(clientes) - len(novos),
        sem_celular=sum(1 for c in novos if not c["celular"]),
    )


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
    if criado_de:
        query = query.filter(models.Lead.created_at >= datetime.combine(criado_de, datetime.min.time()))
    if criado_ate:
        query = query.filter(models.Lead.created_at <= datetime.combine(criado_ate, datetime.max.time()))

    bl_codigos, bl_cpfs = codigos_bloqueados(db)
    if bl_codigos:
        query = query.filter(models.Lead.codigo_cliente.notin_(bl_codigos))
    if bl_cpfs:
        query = query.filter(or_(models.Lead.cpf.is_(None), models.Lead.cpf.notin_(bl_cpfs)))
    return query


@router.get("", response_model=schemas.LeadsPage)
def listar_leads(
    loja: list[str] | None = Query(None, description="Código da loja do título"),
    regional: list[str] | None = Query(None),
    estado: list[str] | None = Query(None),
    cluster_inad: list[str] | None = Query(None),
    cluster_populacao: list[str] | None = Query(None),
    faixa: list[str] | None = Query(None),
    cluster: list[str] | None = Query(None),
    lead_status: str | None = Query(None, alias="status", pattern="^(novo|cobrado)$"),
    busca: str | None = Query(None, description="Nome, código ou CPF"),
    com_celular: bool | None = Query(None),
    criado_de: date | None = Query(None),
    criado_ate: date | None = Query(None),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    try:
        codigos_loja = lojas_base.combinar_lojas(
            db, loja, regional=regional, estado=estado, cluster_inad=cluster_inad, cluster_populacao=cluster_populacao
        )
    except google_client.GoogleIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    query = filtrar_leads(
        db,
        loja=codigos_loja,
        faixa=faixa,
        cluster=cluster,
        lead_status=lead_status,
        busca=busca,
        com_celular=com_celular,
        criado_de=criado_de,
        criado_ate=criado_ate,
    )
    total = query.count()
    itens = (
        query.order_by(models.Lead.created_at.desc(), models.Lead.dias_atraso.desc(), models.Lead.codigo_cliente)
        .offset(offset)
        .limit(limit)
        .all()
    )
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
