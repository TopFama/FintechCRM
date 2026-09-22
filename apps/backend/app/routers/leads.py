from datetime import date, datetime
import re

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import case, false, or_
from sqlalchemy.orm import Session

from .. import google_client, lojas as lojas_base, models, schemas, seta_client
from ..database import get_db
from ..deps import get_current_user
from ..regras_db import carregar_regras
from ..utils.leads_xlsx import gerar_xlsx_leads
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
    parcelas_map: dict[str, list[dict]] = {}
    if novos:
        codigos_novos = [c["codigo"] for c in novos]
        try:
            for lote in _em_lotes(codigos_novos, 5000):
                for codigo, texto in seta_client.buscar_spc(lote).items():
                    datas_spc[codigo] = parse_spc(texto)[1]
            parcelas_map = seta_client.buscar_parcelas_cobranca(
                codigos_novos, juros=carregar_regras(db).juros
            )
        except seta_client.SetaIndisponivel as exc:
            raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc

    leads_para_salvar = []
    for c in novos:
        lead = models.Lead(
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
        vistos_titulos = set()
        for p in parcelas_map.get(c["codigo"], []):
            t_cod = str(p["titulo_codigo"]).strip()
            if t_cod in vistos_titulos:
                continue
            vistos_titulos.add(t_cod)
            lead.parcelas.append(
                models.LeadParcela(
                    titulo_codigo=t_cod,
                    empresa=str(p["empresa"]).strip(),
                    vencimento=p["vencimento"],
                    valor=p["valor"],
                    valor_cobrar=p["valor_cobrar"],
                )
            )
        leads_para_salvar.append(lead)

    db.add_all(leads_para_salvar)
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


def filtros_consulta_leads(
    loja: list[str] | None = Query(None, description="Código da loja do título"),
    regional: list[str] | None = Query(None),
    estado: list[str] | None = Query(None),
    cluster_inad: list[str] | None = Query(None),
    cluster_populacao: list[str] | None = Query(None),
    faixa: list[str] | None = Query(None),
    cluster: list[str] | None = Query(None),
    busca: str | None = Query(None, description="Nome, código ou CPF"),
    com_celular: bool | None = Query(None),
    criado_de: date | None = Query(None),
    criado_ate: date | None = Query(None),
) -> dict:
    return {
        "loja": loja,
        "regional": regional,
        "estado": estado,
        "cluster_inad": cluster_inad,
        "cluster_populacao": cluster_populacao,
        "faixa": faixa,
        "cluster": cluster,
        "busca": busca,
        "com_celular": com_celular,
        "criado_de": criado_de,
        "criado_ate": criado_ate,
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
    """Exporta os leads para planilha Excel (.xlsx) com colunas Codigo, Nome, CPF e Celular."""
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
    hoje = date.today().isoformat()
    filename = f"leads_{nome_faixas}_{hoje}.xlsx"

    return Response(
        content=conteudo,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("", response_model=schemas.LeadsPage)
def listar_leads(
    filtros: dict = Depends(filtros_consulta_leads),
    lead_status: str | None = Query(None, alias="status", pattern="^(novo|cobrado)$"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    query = query_leads_filtrada(db, filtros, lead_status)
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
    else:
        base = query_leads_filtrada(db, filtros, lead_status)

    total_alvo = base.count()
    excluidos = base.filter(models.Lead.status == "novo").delete(synchronize_session=False)
    db.commit()
    return {"excluidos": excluidos, "ignorados_ja_enviados": total_alvo - excluidos}
