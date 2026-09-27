"""Pausar, retomar e parar o envio dos pendentes (Relatórios → Pendentes).
Liberado para qualquer usuário logado: quem e quando ficam registrados."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from .. import fila_automatica, models, pausas, schemas
from ..database import get_db
from ..deps import get_current_user
from ..regras_db import carregar_regras

router = APIRouter(prefix="/pausas", tags=["pausas"])


def _valor_legivel(db: Session, escopo: str, valor: str) -> str:
    if escopo == "faixa":
        faixa = db.get(models.Faixa, valor)
        return faixa.name if faixa else valor
    if escopo == "loja":
        loja = db.query(models.Loja).filter(models.Loja.filial == valor).first()
        return loja.nome_com_cod if loja and loja.nome_com_cod else valor
    lead = db.query(models.Lead).filter(models.Lead.codigo_cliente == valor).order_by(models.Lead.created_at.desc()).first()
    item = None if lead else db.query(models.QueueItem).filter(models.QueueItem.codigo_cliente == valor).first()
    nome = (lead.nome if lead else item.nome if item else "") or ""
    return f"{valor} · {nome}" if nome else valor


def _out(db: Session, p: models.PausaEnvio) -> schemas.PausaEnvioOut:
    return schemas.PausaEnvioOut(
        id=p.id,
        escopo=p.escopo,
        valor=p.valor,
        valor_legivel=_valor_legivel(db, p.escopo, p.valor),
        motivo=p.motivo,
        ate=p.ate,
        created_by=p.created_by,
        created_at=p.created_at,
        qtd_retidos=pausas.pendentes_do_escopo(db, p.escopo, p.valor).count(),
    )


def _validar(db: Session, escopo: str, valor: str) -> str:
    valor = pausas.normalizar_valor(escopo, valor)
    if not valor:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Informe o cliente, a faixa ou a loja")
    if escopo == "faixa" and db.get(models.Faixa, valor) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faixa não encontrada")
    return valor


@router.get("", response_model=list[schemas.PausaEnvioOut])
def listar_ativas(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    return [_out(db, p) for p in pausas.ativas(db)]


@router.get("/opcoes-fila", response_model=schemas.OpcoesFilaOut)
def opcoes_fila(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    """Faixas e lojas que têm pendentes na fila agora, pra escolher o que pausar."""

    ativas = pausas.ativas(db)
    faixas_pausadas = {p.valor for p in ativas if p.escopo == "faixa"}
    lojas_pausadas = {p.valor for p in ativas if p.escopo == "loja"}
    pendente = models.QueueItem.status.in_(pausas.STATUS_PENDENTE)

    faixas = [
        schemas.OpcaoFilaOut(valor=fid, rotulo=nome, qtd_pendentes=qtd, pausado=fid in faixas_pausadas)
        for fid, nome, qtd in db.query(models.Faixa.id, models.Faixa.name, func.count(models.QueueItem.id))
        .join(models.QueueItem, models.QueueItem.faixa_id == models.Faixa.id)
        .filter(pendente)
        .group_by(models.Faixa.id, models.Faixa.name)
    ]
    ordem = _ordem_faixa(db)
    faixas.sort(key=lambda o: ordem.get(o.rotulo, len(ordem)))

    por_loja: dict[str, int] = {}
    for lojas, qtd in db.query(models.QueueItem.lojas, func.count(models.QueueItem.id)).filter(pendente).group_by(
        models.QueueItem.lojas
    ):
        for loja in {l for l in (lojas or "").split(",") if l}:
            por_loja[loja] = por_loja.get(loja, 0) + qtd
    nomes = {l.filial: l.nome_com_cod for l in db.query(models.Loja)}
    lojas_out = [
        schemas.OpcaoFilaOut(valor=l, rotulo=nomes.get(l) or l, qtd_pendentes=q, pausado=l in lojas_pausadas)
        for l, q in sorted(por_loja.items())
    ]
    return schemas.OpcoesFilaOut(faixas=faixas, lojas=lojas_out)


def _ordem_faixa(db: Session) -> dict[str, int]:
    return {nome: i for i, nome in enumerate(carregar_regras(db).nomes_faixa)}


@router.post("/lote", response_model=list[schemas.PausaEnvioOut], status_code=status.HTTP_201_CREATED)
def pausar_lote(
    payload: schemas.PausaLoteIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    """Pausa várias faixas ou lojas de uma vez; o que já está pausado fica como está."""

    motivo = payload.motivo.strip()
    if not motivo:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Informe o motivo da pausa")
    if not payload.valores:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Escolha ao menos uma faixa ou loja")
    if pausas.data_final_passou(payload.ate):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A data final da pausa já passou")
    ja_pausados = {p.valor for p in pausas.ativas(db) if p.escopo == payload.escopo}
    criadas = []
    for bruto in dict.fromkeys(payload.valores):
        valor = _validar(db, payload.escopo, bruto)
        if valor in ja_pausados:
            continue
        criadas.append(pausas.pausar(db, payload.escopo, valor, motivo, payload.ate, user.email))
        ja_pausados.add(valor)
    db.commit()
    return [_out(db, p) for p in criadas]


@router.post("", response_model=schemas.PausaEnvioOut, status_code=status.HTTP_201_CREATED)
def pausar(
    payload: schemas.PausaEnvioCreate,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    valor = _validar(db, payload.escopo, payload.valor)
    motivo = payload.motivo.strip()
    if not motivo:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Informe o motivo da pausa")
    if pausas.data_final_passou(payload.ate):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A data final da pausa já passou")
    if pausas.ativa_do_escopo(db, payload.escopo, valor):
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe uma pausa ativa para esse item")
    pausa = pausas.pausar(db, payload.escopo, valor, motivo, payload.ate, user.email)
    db.commit()
    db.refresh(pausa)
    return _out(db, pausa)


@router.post("/{pausa_id}/retomar", response_model=schemas.PausaEnvioOut)
def retomar(pausa_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    pausa = db.get(models.PausaEnvio, pausa_id)
    if pausa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pausa não encontrada")
    if pausa.encerrada_em is None:
        pausas.retomar(pausa, user.email)
        db.commit()
    return _out(db, pausa)


@router.get("/parar/previa", response_model=schemas.PararEnvioOut)
def previa_parar(
    escopo: schemas.EscopoPausa,
    valor: str,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Quantos pendentes seriam cancelados, pra confirmação na tela."""
    valor = _validar(db, escopo, valor)
    return schemas.PararEnvioOut(qtd=pausas.pendentes_do_escopo(db, escopo, valor).count())


@router.post("/parar", response_model=schemas.PararEnvioOut)
def parar(
    payload: schemas.PararEnvioIn,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    valor = _validar(db, payload.escopo, payload.valor)
    return schemas.PararEnvioOut(qtd=pausas.parar(db, payload.escopo, valor, user.email))


@router.post("/faixa/{faixa_id}/reaplicar-variaveis", response_model=schemas.ReaplicarVariaveisOut)
def reaplicar_variaveis(faixa_id: str, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    """Depois de editar as variáveis do template da faixa, atualiza os
    pendentes que já estavam na fila com o mapeamento novo."""

    faixa = (
        db.query(models.Faixa)
        .options(selectinload(models.Faixa.envios), selectinload(models.Faixa.variable_mappings))
        .filter(models.Faixa.id == faixa_id)
        .first()
    )
    if faixa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faixa não encontrada")
    atualizados, sem_cadastro = fila_automatica.reaplicar_variaveis(db, faixa)
    return schemas.ReaplicarVariaveisOut(atualizados=atualizados, sem_cadastro=sem_cadastro)
