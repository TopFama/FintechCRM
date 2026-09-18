from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import models, schemas
from ..database import get_db
from ..deps import get_current_user

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/summary", response_model=schemas.DashboardSummary)
def summary(db: Session = Depends(get_db), _user: models.User = Depends(get_current_user)):
    def count(status_value: models.QueueStatus) -> int:
        return (
            db.query(func.count(models.QueueItem.id))
            .filter(models.QueueItem.status == status_value)
            .scalar()
            or 0
        )

    por_faixa_rows = (
        db.query(models.Faixa.name, models.QueueItem.status, func.count(models.QueueItem.id))
        .join(models.QueueItem, models.QueueItem.faixa_id == models.Faixa.id, isouter=True)
        .group_by(models.Faixa.name, models.QueueItem.status)
        .all()
    )
    por_faixa: dict[str, dict] = {}
    for faixa_name, status_value, total in por_faixa_rows:
        entry = por_faixa.setdefault(faixa_name, {"faixa": faixa_name})
        entry[status_value.value if status_value else "sem_envios"] = total

    erros = (
        db.query(models.ErrorLog)
        .order_by(models.ErrorLog.created_at.desc())
        .limit(20)
        .all()
    )

    return schemas.DashboardSummary(
        total_pendentes=count(models.QueueStatus.pending),
        total_enviados=count(models.QueueStatus.sent),
        total_erros=count(models.QueueStatus.error),
        total_telefones_invalidos=count(models.QueueStatus.invalid_phone),
        por_faixa=list(por_faixa.values()),
        erros_recentes=[
            {"id": e.id, "faixa_id": e.faixa_id, "message": e.message, "created_at": e.created_at.isoformat()}
            for e in erros
        ],
    )
