from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import cache, campanhas as camp, cobranca_base, google_client, models, seta_client
from ..cobranca_regras import NOMES_FAIXA_COMPRA
from ..database import get_db
from ..deps import get_current_user
from ..regras_db import carregar_regras
from .cobranca import ClienteSortColumn, _ordenar_clientes
from .uploads import _ler_planilha_limitada

router = APIRouter(prefix="/campanhas", tags=["campanhas"])


class FiltrosCampanha(BaseModel):
    """Mesmos filtros (e nomes) de /cobranca/clientes."""

    apenas_primeiro_dia: bool = False
    somente_regra_whatsapp: bool = False
    faixa: list[str] = []
    cluster: list[str] = []
    faixa_compra: list[str] = []
    loja: list[str] = []
    regional: list[str] = []
    estado: list[str] = []
    cluster_inad: list[str] = []
    cluster_populacao: list[str] = []
    cobradora: list[str] = []
    status_cliente: list[str] = []
    restricao_spc: list[str] = []
    vencimento_de: date | None = None
    vencimento_ate: date | None = None
    valor_atraso_min: Decimal | None = Field(default=None, ge=0)
    valor_atraso_max: Decimal | None = Field(default=None, ge=0)
    valor_atraso_com_juros: bool = False


class CampanhaIn(BaseModel):
    nome: str = Field(min_length=1, max_length=80)
    ativa: bool = False
    modo: Literal["unica", "recorrente"] = "unica"
    data_inicio: date | None = None
    data_fim: date | None = None
    fonte_valores: Literal["seta", "planilha"] = "seta"
    recontato_dias: int | None = Field(default=None, ge=1, le=365)
    filtros: FiltrosCampanha = FiltrosCampanha()


def _contagens(db: Session, faixa_ids: list[str]) -> dict[str, dict[str, int]]:
    contagem: dict[str, dict[str, int]] = {fid: {} for fid in faixa_ids}
    if faixa_ids:
        for faixa_id, st, n in (
            db.query(models.QueueItem.faixa_id, models.QueueItem.status, func.count())
            .filter(models.QueueItem.faixa_id.in_(faixa_ids))
            .group_by(models.QueueItem.faixa_id, models.QueueItem.status)
        ):
            contagem[faixa_id][st.value] = n
    return contagem


def _out(c: models.Campanha, contagem: dict[str, int] | None = None) -> dict:
    envios = [e for e in c.faixa.envios if e.active]
    contagem = contagem or {}
    return {
        "id": c.id,
        "nome": c.nome,
        "faixa_id": c.faixa_id,
        "ativa": c.ativa,
        "modo": c.modo,
        "data_inicio": c.data_inicio,
        "data_fim": c.data_fim,
        "fonte_valores": c.fonte_valores,
        "recontato_dias": c.recontato_dias,
        "filtros": FiltrosCampanha(**(c.filtros or {})).model_dump(mode="json"),
        "clientes_total": len(c.clientes or []),
        "clientes_arquivo": c.clientes_arquivo,
        "planilha_colunas": c.planilha_colunas or [],
        "envios_ativos": len(envios),
        "templates": sorted({e.template.name for e in envios if e.template}),
        "ultima_execucao": c.ultima_execucao,
        "ultimo_resultado": c.ultimo_resultado or {},
        "enviados": contagem.get("sent", 0),
        "pendentes": contagem.get("pending", 0) + contagem.get("reserved", 0),
        "erros": contagem.get("error", 0),
        "created_at": c.created_at,
    }


def _get(db: Session, campanha_id: str) -> models.Campanha:
    c = db.get(models.Campanha, campanha_id)
    if c is None or c.arquivada_em is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Campanha não encontrada")
    return c


def _erro(msg: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, msg)


def _validar(db: Session, payload: CampanhaIn, atual: models.Campanha | None) -> str:
    if payload.ativa and payload.data_inicio is None:
        raise _erro("Informe a data" + (" de início" if payload.modo == "recorrente" else " da campanha"))
    if payload.modo == "recorrente" and payload.data_inicio and payload.data_fim and payload.data_fim < payload.data_inicio:
        raise _erro("A data final é antes da inicial")
    f = payload.filtros
    if f.valor_atraso_min is not None and f.valor_atraso_max is not None and f.valor_atraso_min > f.valor_atraso_max:
        raise _erro("O valor em atraso mínimo é maior que o máximo")
    if f.vencimento_de and f.vencimento_ate and f.vencimento_de > f.vencimento_ate:
        raise _erro("O vencimento inicial é depois do final")
    nome = " ".join(payload.nome.split())
    q = db.query(models.Campanha).filter(func.lower(models.Campanha.nome) == nome.lower())
    if atual is not None:
        q = q.filter(models.Campanha.id != atual.id)
    if q.first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe uma campanha com esse nome")
    outra_faixa = db.query(models.Faixa).filter(models.Faixa.name == camp.nome_faixa(nome))
    if atual is not None:
        outra_faixa = outra_faixa.filter(models.Faixa.id != atual.faixa_id)
    if outra_faixa.first() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Esse nome já é usado por uma faixa; escolha outro")
    regras = carregar_regras(db)
    f = payload.filtros
    invalidas = (
        [x for x in f.faixa if x not in regras.nomes_faixa]
        + [x for x in f.cluster if x not in regras.nomes_cluster]
        + [x for x in f.faixa_compra if x not in NOMES_FAIXA_COMPRA]
        + [x for x in f.restricao_spc if x not in ("sim", "nao", "indeterminado")]
        + [x for x in f.status_cliente if x not in seta_client.STATUS_CLIENTE]
    )
    if invalidas:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Filtro desconhecido: {', '.join(invalidas)}")
    if payload.fonte_valores == "planilha" and not (atual and atual.clientes):
        if payload.ativa:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Suba a planilha de clientes para usar os valores dela")
    return nome


def _aplicar(c: models.Campanha, payload: CampanhaIn, nome: str) -> None:
    c.nome = nome
    c.faixa.name = camp.nome_faixa(nome)
    c.ativa = payload.ativa
    c.modo = payload.modo
    c.data_inicio = payload.data_inicio
    c.data_fim = payload.data_fim if payload.modo == "recorrente" else None
    c.fonte_valores = payload.fonte_valores
    c.recontato_dias = payload.recontato_dias if payload.modo == "recorrente" else None
    c.filtros = payload.filtros.model_dump(mode="json")
    # Mudou a configuração: pode rodar de novo hoje com a nova regra.
    c.ultima_execucao_dia = None


@router.get("")
def listar(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    campanhas = (
        db.query(models.Campanha)
        .filter(models.Campanha.arquivada_em.is_(None))
        .order_by(models.Campanha.created_at.desc())
        .all()
    )
    contagens = _contagens(db, [c.faixa_id for c in campanhas])
    return [_out(c, contagens[c.faixa_id]) for c in campanhas]


@router.get("/opcoes")
def opcoes(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    """Todas as campanhas, arquivadas inclusive (o histórico continua nos
    relatórios), pro filtro "Campanha" da Efetividade e da exportação de leads."""

    return [
        {"id": c.id, "nome": c.nome, "arquivada": c.arquivada_em is not None}
        for c in db.query(models.Campanha).order_by(models.Campanha.arquivada_em.isnot(None), models.Campanha.nome)
    ]


@router.post("", status_code=status.HTTP_201_CREATED)
def criar(payload: CampanhaIn, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    nome = _validar(db, payload, None)
    faixa = models.Faixa(name=camp.nome_faixa(nome), active=True)
    db.add(faixa)
    db.flush()
    c = models.Campanha(faixa_id=faixa.id, created_by=user.id, clientes=[], planilha_colunas=[], planilha_linhas={}, ultimo_resultado={})
    c.faixa = faixa
    _aplicar(c, payload, nome)
    db.add(c)
    db.commit()
    db.refresh(c)
    return _out(c)


@router.get("/{campanha_id}")
def ver(campanha_id: str, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    c = _get(db, campanha_id)
    return _out(c, _contagens(db, [c.faixa_id])[c.faixa_id])


@router.put("/{campanha_id}")
def salvar(
    campanha_id: str, payload: CampanhaIn, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    c = _get(db, campanha_id)
    nome = _validar(db, payload, c)
    _aplicar(c, payload, nome)
    db.commit()
    db.refresh(c)
    return _out(c, _contagens(db, [c.faixa_id])[c.faixa_id])


@router.delete("/{campanha_id}", status_code=status.HTTP_204_NO_CONTENT)
def excluir(campanha_id: str, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    """Arquiva: some da lista e para de rodar, mas o histórico de envios da
    faixa continua nos relatórios. Os pendentes dela deixam de sair."""

    c = _get(db, campanha_id)
    c.ativa = False
    c.arquivada_em = datetime.utcnow()
    c.faixa.active = False
    for envio in c.faixa.envios:
        if envio.dispatch_config:
            envio.dispatch_config.active = False
    # libera o nome para uma campanha nova
    c.nome = f"{c.nome} (arquivada {c.id[:8]})"
    c.faixa.name = camp.nome_faixa(c.nome)
    db.commit()


@router.post("/{campanha_id}/clientes")
async def subir_clientes(
    campanha_id: str,
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Planilha .xlsx de clientes: a campanha passa a olhar só para eles
    (pela coluna Codigo ou, sem ela, CPF). As demais colunas ficam guardadas
    para quando a campanha usa os valores da planilha."""

    c = _get(db, campanha_id)
    content = await _ler_planilha_limitada(file)
    try:
        lido = camp.ler_clientes(file.filename or "", content)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except seta_client.SetaIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    if not lido["clientes"]:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Nenhum cliente identificado na planilha")
    c.clientes = lido["clientes"]
    c.planilha_linhas = lido["linhas"]
    c.planilha_colunas = lido["colunas"]
    c.clientes_arquivo = file.filename
    c.ultima_execucao_dia = None
    db.commit()
    return {
        "clientes": len(lido["clientes"]),
        "ignoradas": lido["ignoradas"],
        "coluna": lido["coluna"],
        "colunas": lido["colunas"],
    }


@router.delete("/{campanha_id}/clientes", status_code=status.HTTP_204_NO_CONTENT)
def remover_clientes(campanha_id: str, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    c = _get(db, campanha_id)
    c.clientes = []
    c.planilha_linhas = {}
    c.planilha_colunas = []
    c.clientes_arquivo = None
    c.fonte_valores = "seta"
    c.ultima_execucao_dia = None
    db.commit()


def _erro_base(exc: Exception) -> HTTPException:
    if isinstance(exc, cobranca_base.FiltroInvalido):
        return HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    return HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc))


_ERROS_BASE = (
    cobranca_base.FiltroInvalido,
    seta_client.SetaIndisponivel,
    cache.CacheIndisponivel,
    google_client.GoogleIndisponivel,
)


@router.get("/{campanha_id}/previa")
def previa(
    campanha_id: str,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    sort_by: ClienteSortColumn | None = Query(None),
    sort_dir: Literal["asc", "desc"] = Query("asc"),
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Quem entraria na fila se a campanha rodasse agora (sem colocar
    ninguém), paginado e ordenado no servidor. "processing" enquanto o SETA
    calcula a base; quem pediu tenta de novo em seguida."""

    c = _get(db, campanha_id)
    try:
        selecao = camp.selecionar(db, c)
    except _ERROS_BASE as exc:
        raise _erro_base(exc) from exc
    if selecao["status"] != "ready":
        return {"status": "processing", "data": None}
    clientes = selecao["clientes"]
    if c.fonte_valores == "planilha":
        clientes = [camp.com_valores_da_planilha(x, c) for x in clientes]
    if sort_by:
        clientes = _ordenar_clientes(clientes, sort_by, sort_dir, db)
    campos = ("codigo", "nome", "celular", "cpfcnpj", "cluster", "faixa", "dias_atraso", "valor_cobrar",
              "valor_atraso_original", "valor_atraso_juros", "vencimento_mais_antigo", "lojas")
    return {
        "status": "ready",
        "data": {
            "total_base": selecao["total_base"],
            "total": len(clientes),
            "itens": [{k: x.get(k) for k in campos} for x in clientes[offset : offset + limit]],
        },
    }


@router.post("/{campanha_id}/executar")
def executar_agora(campanha_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    """Coloca na fila agora quem entraria (o agendador faz isso sozinho no
    dia/período). Os envios saem dentro do horário de disparo."""

    c = _get(db, campanha_id)
    if not any(e.active for e in c.faixa.envios):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Atribua um número e um template à campanha antes de rodar")
    if c.fonte_valores == "planilha" and not c.clientes:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Suba a planilha de clientes para usar os valores dela")
    try:
        resultado = camp.executar(db, c, created_by=user.id)
    except _ERROS_BASE as exc:
        raise _erro_base(exc) from exc
    if resultado["status"] != "ready":
        return {"status": "processing", "data": None}
    return {"status": "ready", "data": {"encontrados": resultado["encontrados"], "na_fila": resultado["na_fila"]}}
