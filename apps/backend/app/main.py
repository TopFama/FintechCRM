import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from . import models
from .config import settings
from .database import Base, SessionLocal, engine
from .routers import auth, dashboard, faixas, numbers, templates, uploads
from .security import hash_password
from .worker import start_scheduler

logging.basicConfig(level=logging.INFO)


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
    Base.metadata.create_all(bind=engine)
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


@app.get("/health")
def health():
    return {"status": "ok"}
