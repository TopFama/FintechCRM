"""Pausar, retomar e parar o envio dos pendentes (Relatórios → Pendentes).
Liberado para qualquer usuário logado: quem e quando ficam registrados."""

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import models, pausas, schemas
from ..database import get_db
from ..deps import get_current_user
from ..timezone import hoje_br

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
    if payload.ate and payload.ate < hoje_br():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "A data final da pausa já passou")
    existente = next((p for p in pausas.ativas(db) if p.escopo == payload.escopo and p.valor == valor), None)
    if existente:
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe uma pausa ativa para esse item")
    pausa = models.PausaEnvio(
        escopo=payload.escopo, valor=valor, motivo=motivo, ate=payload.ate, created_by=user.email
    )
    db.add(pausa)
    db.commit()
    db.refresh(pausa)
    return _out(db, pausa)


@router.post("/{pausa_id}/retomar", response_model=schemas.PausaEnvioOut)
def retomar(pausa_id: str, db: Session = Depends(get_db), user: models.User = Depends(get_current_user)):
    pausa = db.get(models.PausaEnvio, pausa_id)
    if pausa is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Pausa não encontrada")
    if pausa.encerrada_em is None:
        pausa.encerrada_em = datetime.utcnow()
        pausa.encerrada_por = user.email
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
