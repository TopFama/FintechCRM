from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session, selectinload

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user
from ..utils.spreadsheet import build_model_csv

router = APIRouter(prefix="/faixas", tags=["faixas"])


def _full_query(db: Session):
    return db.query(models.Faixa).options(
        selectinload(models.Faixa.template).selectinload(models.Template.variables),
        selectinload(models.Faixa.variable_mappings),
        selectinload(models.Faixa.dispatch_config),
    )


@router.get("", response_model=list[schemas.FaixaOut])
def list_faixas(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    return _full_query(db).order_by(models.Faixa.created_at.desc()).all()


@router.get("/{faixa_id}", response_model=schemas.FaixaOut)
def get_faixa(
    faixa_id: str, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    faixa = _full_query(db).filter(models.Faixa.id == faixa_id).first()
    if not faixa:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faixa não encontrada")
    return faixa


@router.post("", response_model=schemas.FaixaOut, status_code=status.HTTP_201_CREATED)
def create_faixa(
    payload: schemas.FaixaCreate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    template = (
        db.query(models.Template)
        .options(selectinload(models.Template.variables))
        .filter(models.Template.id == payload.template_id)
        .first()
    )
    if not template:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template não encontrado")
    if db.query(models.Faixa).filter(models.Faixa.name == payload.name).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "Já existe uma faixa com esse nome")
    if not payload.whatsapp_number_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Selecione ao menos um número de envio")

    template_variable_ids = {v.id for v in template.variables}
    mapped_ids = {m.template_variable_id for m in payload.variable_mappings}
    if template_variable_ids != mapped_ids:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Toda variável do template precisa de uma coluna de planilha mapeada",
        )

    faixa = models.Faixa(name=payload.name, template_id=payload.template_id)
    db.add(faixa)
    db.flush()

    for number_id in payload.whatsapp_number_ids:
        number = db.query(models.WhatsappNumber).get(number_id)
        if not number:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Número {number_id} não encontrado")
        db.add(models.FaixaNumber(faixa_id=faixa.id, whatsapp_number_id=number_id))

    for mapping in payload.variable_mappings:
        db.add(
            models.FaixaVariableMapping(
                faixa_id=faixa.id,
                template_variable_id=mapping.template_variable_id,
                column_name=mapping.column_name,
            )
        )

    db.add(models.DispatchConfig(faixa_id=faixa.id, active=False))

    db.commit()
    return _full_query(db).filter(models.Faixa.id == faixa.id).first()


@router.get("/{faixa_id}/spreadsheet-model")
def download_spreadsheet_model(
    faixa_id: str, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    faixa = _full_query(db).filter(models.Faixa.id == faixa_id).first()
    if not faixa:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faixa não encontrada")
    variable_names = [
        next(v.internal_name for v in faixa.template.variables if v.id == m.template_variable_id)
        for m in faixa.variable_mappings
    ]
    content = build_model_csv(variable_names)
    return Response(
        content=content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="modelo_{faixa.name}.csv"'
        },
    )


@router.put("/{faixa_id}/dispatch-config", response_model=schemas.DispatchConfigOut)
def update_dispatch_config(
    faixa_id: str,
    payload: schemas.DispatchConfigUpdate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    faixa = db.query(models.Faixa).filter(models.Faixa.id == faixa_id).first()
    if not faixa:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faixa não encontrada")
    config = db.query(models.DispatchConfig).filter(models.DispatchConfig.faixa_id == faixa_id).first()
    if not config:
        config = models.DispatchConfig(faixa_id=faixa_id)
        db.add(config)
    for field, value in payload.model_dump().items():
        setattr(config, field, value)
    db.commit()
    db.refresh(config)
    return config


@router.post("/{faixa_id}/dispatch-now", status_code=status.HTTP_202_ACCEPTED)
def dispatch_now(
    faixa_id: str, db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    """Marca a faixa para ser processada pelo worker na próxima varredura,
    ignorando o agendamento configurado — equivalente ao antigo 'cobrar agora'."""

    config = db.query(models.DispatchConfig).filter(models.DispatchConfig.faixa_id == faixa_id).first()
    if not config:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Faixa sem configuração de disparo")
    config.force_run = True
    db.commit()
    return {"status": "agendado para a próxima varredura do worker"}
