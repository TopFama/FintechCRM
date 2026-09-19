import logging
from contextlib import asynccontextmanager
from pathlib import Path

from alembic import command
from alembic.config import Config
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import models
from .config import settings
from .database import SessionLocal
from .routers import auth, dashboard, faixas, numbers, reports, templates, uploads
from .security import hash_password
from .worker import start_scheduler

logging.basicConfig(level=logging.INFO)

BACKEND_DIR = Path(__file__).resolve().parent.parent


def _run_migrations() -> None:
    """Aplica as migrations do Alembic até a mais recente na subida do
    backend — substitui o antigo `Base.metadata.create_all()`, que só criava
    tabelas novas e nunca alterava as existentes."""

    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(alembic_cfg, "head")


def _ensure_admin_user() -> None:
    db = SessionLocal()
    try:
        existing = db.query(models.User).filter(models.User.email == settings.admin_email).first()
        if not existing:
            db.add(
                models.User(
                    email=settings.admin_email,
                    password_hash=hash_password(settings.admin_password),
                )
            )
            db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _run_migrations()
    _ensure_admin_user()
    scheduler = start_scheduler()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="FintechCRM — Cobrança via WhatsApp", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")

app.include_router(auth.router)
app.include_router(numbers.router)
app.include_router(templates.router)
app.include_router(faixas.router)
app.include_router(uploads.router)
app.include_router(dashboard.router)
app.include_router(reports.router)


@app.get("/health")
def health():
    return {"status": "ok"}
