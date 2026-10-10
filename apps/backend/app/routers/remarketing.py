from datetime import date, datetime, timedelta
from decimal import Decimal

import httpx
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import crypto, itens_fila, models
from .. import remarketing as rmk
from ..database import get_db
from ..deps import get_current_user, require_admin
from ..regras_db import carregar_regras
from ..seta_client import SetaIndisponivel
from ..timezone import hoje_br

router = APIRouter(prefix="/remarketing", tags=["remarketing"])


class ConexaoIn(BaseModel):
    base_url: str = Field(min_length=8, max_length=300)
    chave: str | None = Field(default=None, max_length=300)


class SegmentoIn(BaseModel):
    ativo: bool
    janela_dias: int = Field(ge=1, le=rmk.MAX_JANELA_DIAS)
    recontato_dias: int = Field(ge=1, le=365)
    cobradoras: list[str] = []
    faixas_atraso: list[str] = []
    clusters: list[str] = []
    valor_min: Decimal | None = Field(default=None, ge=0)
    valor_max: Decimal | None = Field(default=None, ge=0)


def _conexao_out(config: models.IntegracaoRenegocie | None) -> dict:
    return {"configurado": config is not None, "base_url": config.base_url if config else None}


@router.get("/conexao")
def ver_conexao(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    return _conexao_out(db.query(models.IntegracaoRenegocie).first())


@router.put("/conexao")
def salvar_conexao(payload: ConexaoIn, db: Session = Depends(get_db), _user: models.User = Depends(require_admin)):
    config = db.query(models.IntegracaoRenegocie).first()
    base_url = payload.base_url.strip().rstrip("/")
    if not base_url.startswith(("http://", "https://")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O endereço precisa começar com http:// ou https://")
    if config is None:
        if not payload.chave:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Informe a chave gerada no admin do Renegocie")
        config = models.IntegracaoRenegocie(base_url=base_url, chave_cifrada=crypto.cifrar(payload.chave.strip()))
        db.add(config)
    else:
        # A chave guardada só vai para o endereço em que foi cadastrada: trocar o
        # endereço sem informar a chave de novo a mandaria para outro servidor.
        if base_url != config.base_url and not payload.chave:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Ao trocar o endereço, informe a chave de novo")
        config.base_url = base_url
        if payload.chave:
            config.chave_cifrada = crypto.cifrar(payload.chave.strip())
    db.commit()
    return _conexao_out(config)


@router.post("/conexao/testar")
def testar_conexao(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    try:
        clientes = rmk.buscar_no_renegocie(db, 1)
    except rmk.RemarketingErro as exc:
        return {"ok": False, "detalhe": str(exc)}
    except (httpx.HTTPError, ValueError) as exc:
        return {"ok": False, "detalhe": f"Resposta inesperada do Renegocie ({exc.__class__.__name__})"}
    return {"ok": True, "detalhe": f"Conectado. {len(clientes)} desistência(s) nas últimas 24 horas."}


def _segmento_out(regra: models.RemarketingSegmento) -> dict:
    envios_ativos = [e for e in regra.faixa.envios if e.active]
    return {
        "segmento": regra.segmento,
        "nome": rmk.SEGMENTOS[regra.segmento],
        "descricao": models.DESCRICOES_REMARKETING[regra.segmento],
        "faixa_id": regra.faixa_id,
        "faixa_nome": regra.faixa.name,
        "envios_ativos": len(envios_ativos),
        "ativo": regra.ativo,
        "janela_dias": regra.janela_dias,
        "recontato_dias": regra.recontato_dias,
        "cobradoras": regra.cobradoras or [],
        "faixas_atraso": regra.faixas_atraso or [],
        "clusters": regra.clusters or [],
        "valor_min": regra.valor_min,
        "valor_max": regra.valor_max,
        "ultima_execucao": regra.ultima_execucao,
        "ultimo_resultado": regra.ultimo_resultado or {},
    }


@router.get("/segmentos")
def listar_segmentos(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    return [_segmento_out(r) for r in rmk.garantir_segmentos(db)]


@router.put("/segmentos/{segmento}")
def salvar_segmento(
    segmento: str,
    payload: SegmentoIn,
    db: Session = Depends(get_db),
    _user: models.User = Depends(require_admin),
):
    if segmento not in rmk.SEGMENTOS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Segmento não encontrado")
    if payload.valor_min is not None and payload.valor_max is not None and payload.valor_min > payload.valor_max:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "O valor mínimo é maior que o máximo")
    regras = carregar_regras(db)
    invalidas = [f for f in payload.faixas_atraso if f not in regras.nomes_faixa_regua] + [
        c for c in payload.clusters if c not in regras.nomes_cluster
    ]
    if invalidas:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Filtro desconhecido: {', '.join(invalidas)}")
    rmk.garantir_segmentos(db)
    regra = db.get(models.RemarketingSegmento, segmento)
    for campo, valor in payload.model_dump().items():
        setattr(regra, campo, valor)
    db.commit()
    db.refresh(regra)
    return _segmento_out(regra)


def _linha_previa(c: dict) -> dict:
    return {
        "codigo": c["codigo"],
        "nome": c["nome"],
        "celular": c["celular"],
        "faixa": c["faixa"],
        "dias_atraso": c["dias_atraso"],
        "valor_cobrar": c["valor_cobrar"],
        "cluster": c["cluster"],
        "evento_em": c["evento_em"],
        # número da proposta gerado pelo Renegocie; existe mesmo quando o acordo não foi lançado no SETA
        "proposta": c["proposta"],
        # código do acordo no SETA (ft.auxiliar, "RE" + reparcelamento); só existe se chegou a ser lançado
        "referencia_seta": c["referencia_seta"],
        "entrada_vencimento": c["entrada_vencimento"],
    }


@router.post("/segmentos/{segmento}/previa")
def previa(
    segmento: str,
    de: date | None = None,
    ate: date | None = None,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Quem entraria hoje com os filtros salvos, sem colocar ninguém na fila.
    Com `de`/`ate`, olha os eventos desse período em vez da janela do segmento."""

    if segmento not in rmk.SEGMENTOS:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Segmento não encontrado")
    regra = next(r for r in rmk.garantir_segmentos(db) if r.segmento == segmento)
    periodo = None
    dias = regra.janela_dias
    if de or ate:
        hoje = hoje_br()
        periodo = (de or hoje - timedelta(days=rmk.MAX_JANELA_DIAS), ate or hoje)
        if periodo[0] > periodo[1]:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A data inicial é depois da final")
        dias = (hoje - periodo[0]).days + 1
    try:
        candidatos = rmk.buscar_no_renegocie(db, dias)
        selecionados = rmk.selecionar(db, candidatos, somente={segmento}, periodo=periodo)[segmento]
    except rmk.RemarketingErro as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except SetaIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return {
        "total_renegocie": sum(
            1
            for c in candidatos
            if c.get("segmento") == segmento
            and (periodo is None or periodo[0] <= rmk.dia_do_evento(c["evento_em"]) <= periodo[1])
        ),
        "total": len(selecionados),
        "clientes": [_linha_previa(c) for c in selecionados],
        "gerado_em": datetime.utcnow(),
    }


@router.post("/executar")
def executar_agora(db: Session = Depends(get_db), _user: models.User = Depends(require_admin)):
    """Busca e coloca na fila agora os segmentos ligados (o agendador faz isso sozinho todo dia)."""

    try:
        segmentos = rmk.executar(db)
    except rmk.RemarketingErro as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except SetaIndisponivel as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    com_fila = [seg for seg, r in segmentos.items() if r["na_fila"]]
    regras = db.query(models.RemarketingSegmento).filter(models.RemarketingSegmento.segmento.in_(com_fila))
    faixas = [r.faixa for r in regras]
    return {"segmentos": segmentos, "avisos_categoria": itens_fila.avisos_categoria_das_faixas(faixas)}
