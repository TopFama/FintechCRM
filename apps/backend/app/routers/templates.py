import os
import uuid

from fastapi import APIRouter, Depends, HTTPException, UploadFile, status
from sqlalchemy.orm import Session, selectinload

from .. import models, schemas
from ..config import settings
from ..database import get_db
from ..deps import get_current_user
from ..meta_client import MetaAPIError, MetaClient

router = APIRouter(prefix="/templates", tags=["templates"])


def _with_variables(query):
    return query.options(selectinload(models.Template.variables))


@router.get("", response_model=list[schemas.TemplateOut])
def list_templates(
    db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)
):
    return _with_variables(db.query(models.Template)).order_by(
        models.Template.created_at.desc()
    ).all()


@router.get("/meta/sync", response_model=list[schemas.TemplateOut])
async def sync_from_meta(
    waba_id: str,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    """Puxa os templates aprovados/pendentes direto da Meta e faz upsert local,
    para que o cadastro de faixa sempre escolha a partir do que existe na Meta."""

    client = MetaClient()
    try:
        remote_templates = await client.list_templates(waba_id)
    except MetaAPIError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    for remote in remote_templates:
        existing = (
            db.query(models.Template)
            .filter(
                models.Template.meta_template_name == remote["name"],
                models.Template.language == remote["language"],
            )
            .first()
        )
        status_value = _map_meta_status(remote.get("status"))
        if existing:
            existing.status = status_value
            existing.meta_status_raw = remote.get("status")
            existing.meta_template_id = remote.get("id")
            existing.category = remote.get("category", existing.category)
            existing.waba_id = waba_id
        else:
            template = models.Template(
                name=remote["name"],
                meta_template_name=remote["name"],
                language=remote.get("language", "pt_BR"),
                category=remote.get("category", "UTILITY"),
                status=status_value,
                meta_status_raw=remote.get("status"),
                meta_template_id=remote.get("id"),
                waba_id=waba_id,
                body_text=_extract_body_text(remote),
            )
            db.add(template)
            db.flush()
            for i, name in enumerate(_extract_variable_count(remote), start=1):
                db.add(
                    models.TemplateVariable(
                        template_id=template.id, position=i, internal_name=name
                    )
                )
    db.commit()
    return _with_variables(db.query(models.Template)).filter(
        models.Template.waba_id == waba_id
    ).all()


def _map_meta_status(raw: str | None) -> models.TemplateStatus:
    mapping = {
        "APPROVED": models.TemplateStatus.approved,
        "PENDING": models.TemplateStatus.pending,
        "REJECTED": models.TemplateStatus.rejected,
    }
    return mapping.get((raw or "").upper(), models.TemplateStatus.draft)


def _extract_body_text(remote: dict) -> str:
    for component in remote.get("components", []):
        if component.get("type") == "BODY":
            return component.get("text", "")
    return ""


def _extract_variable_count(remote: dict) -> list[str]:
    body_text = _extract_body_text(remote)
    import re

    positions = sorted({int(m) for m in re.findall(r"\{\{(\d+)\}\}", body_text)})
    return [f"variavel_{p}" for p in positions]


@router.post("", response_model=schemas.TemplateOut, status_code=status.HTTP_201_CREATED)
async def create_template(
    payload: schemas.TemplateCreate,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    template = models.Template(
        name=payload.name,
        meta_template_name=payload.meta_template_name,
        language=payload.language,
        category=payload.category,
        header_type=payload.header_type,
        body_text=payload.body_text,
        waba_id=payload.waba_id,
        status=models.TemplateStatus.draft,
    )
    db.add(template)
    db.flush()
    for var in payload.variables:
        db.add(
            models.TemplateVariable(
                template_id=template.id, position=var.position, internal_name=var.internal_name
            )
        )
    db.flush()

    if payload.submit_to_meta:
        client = MetaClient()
        components = [{"type": "BODY", "text": payload.body_text}]
        if payload.header_type == models.TemplateHeaderType.image:
            components.insert(0, {"type": "HEADER", "format": "IMAGE"})
        try:
            result = await client.create_template(
                payload.waba_id,
                {
                    "name": payload.meta_template_name,
                    "language": payload.language,
                    "category": payload.category,
                    "components": components,
                },
            )
            template.meta_template_id = result.get("id")
            template.status = models.TemplateStatus.pending
            template.meta_status_raw = "PENDING"
        except MetaAPIError as exc:
            db.commit()
            raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc

    db.commit()
    db.refresh(template)
    return template


@router.post("/{template_id}/refresh-status", response_model=schemas.TemplateOut)
async def refresh_template_status(
    template_id: str,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    template = _with_variables(db.query(models.Template)).filter(
        models.Template.id == template_id
    ).first()
    if not template:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template não encontrado")
    if not template.meta_template_id:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Template ainda não foi submetido à Meta"
        )
    client = MetaClient()
    try:
        remote = await client.get_template_status(template.meta_template_id)
    except MetaAPIError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    template.status = _map_meta_status(remote.get("status"))
    template.meta_status_raw = remote.get("status")
    db.commit()
    db.refresh(template)
    return template


@router.post("/{template_id}/image", response_model=schemas.TemplateOut)
async def upload_template_image(
    template_id: str,
    file: UploadFile,
    db: Session = Depends(get_db),
    _user: models.User = Depends(get_current_user),
):
    template = _with_variables(db.query(models.Template)).filter(
        models.Template.id == template_id
    ).first()
    if not template:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Template não encontrado")

    os.makedirs(settings.media_dir, exist_ok=True)
    ext = os.path.splitext(file.filename or "")[1] or ".jpg"
    stored_name = f"{template.id}{ext}"
    dest_path = os.path.join(settings.media_dir, stored_name)
    content = await file.read()
    with open(dest_path, "wb") as f:
        f.write(content)

    template.image_url = f"/media/{stored_name}"
    template.header_type = models.TemplateHeaderType.image
    db.commit()
    db.refresh(template)
    return template
