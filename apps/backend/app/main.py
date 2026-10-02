import logging
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from alembic import command
from alembic.config import Config
from cryptography.fernet import Fernet
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func

from . import cache, lojas as lojas_base, models, seta_client
from .config import settings
from .database import SessionLocal
from .routers import auth, blacklist, campanhas, chatwoot, cobranca, config_cobranca, dashboard, faixas, google, leads, lojas, meta_tokens, numbers, pausas, remarketing, reports, seta, templates, uploads, users
from .security import hash_password
from .segredos import recifrar_segredos
from .worker import start_scheduler

logging.basicConfig(level=logging.INFO)
# O APScheduler registra cada execução dos jobs (a cada poucos segundos): só avisos
logging.getLogger("apscheduler").setLevel(logging.WARNING)

BACKEND_DIR = Path(__file__).resolve().parent.parent

EXEMPLO_ENCRYPTION_KEY = "ZXhlbXBsb19jaGF2ZV9mZXJuZXRfMzJfYnl0ZXNfX18="


def _run_migrations() -> None:
    """Aplica as migrations do Alembic até a mais recente na subida do
    backend — substitui o antigo `Base.metadata.create_all()`, que só criava
    tabelas novas e nunca alterava as existentes."""

    alembic_cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    alembic_cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    command.upgrade(alembic_cfg, "head")


def _check_secrets() -> None:
    """Recusa subir com os valores padrão do `.env.example` — são públicos
    no repositório e, se esquecidos em produção, permitem login direto com
    a senha padrão do admin ou forjar um token JWT válido para qualquer
    usuário."""

    insecure_defaults = {
        "jwt_secret": "change-me-too",
        "admin_password": "change-me-admin",
    }
    leaked = [name for name, default in insecure_defaults.items() if getattr(settings, name) == default]
    if leaked:
        raise RuntimeError(
            "Configuração insegura: defina variáveis de ambiente reais para "
            f"{', '.join(leaked)} antes de subir o backend (ver README.md → "
            "'Configuração do ambiente (.env)'). Os valores padrão do "
            "`.env.example` são públicos e não podem ser usados fora de desenvolvimento local."
        )

    enc_key = (settings.encryption_key or "").strip()
    if not enc_key:
        raise RuntimeError(
            "Configuração insegura: ENCRYPTION_KEY não pode ser vazia. "
            "Gere uma chave com: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    if enc_key == EXEMPLO_ENCRYPTION_KEY:
        raise RuntimeError(
            "Configuração insegura: ENCRYPTION_KEY não pode ser o valor de exemplo do `.env.example`. "
            "Gere uma chave com: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        )
    try:
        Fernet(enc_key.encode())
    except Exception as exc:
        raise RuntimeError(
            "Configuração insegura: ENCRYPTION_KEY não é uma chave Fernet válida. "
            "Gere uma chave com: python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
        ) from exc


def _ensure_admin_user() -> None:
    db = SessionLocal()
    try:
        existing = (
            db.query(models.User)
            .filter(func.lower(models.User.email) == settings.admin_email.strip().lower())
            .first()
        )
        if not existing:
            db.add(
                models.User(
                    email=settings.admin_email,
                    password_hash=hash_password(settings.admin_password),
                    is_admin=True,
                )
            )
            db.commit()
        elif not existing.is_admin:
            # Garante que o e-mail configurado em ADMIN_EMAIL sempre tem
            # is_admin=True, mesmo em bancos que já existiam antes deste campo.
            existing.is_admin = True
            db.commit()
    finally:
        db.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    _check_secrets()
    _run_migrations()
    _ensure_admin_user()
    db = SessionLocal()
    try:
        recifrar_segredos(db)
        lojas_base.semear_se_vazio(db)
    finally:
        db.close()
    scheduler = start_scheduler()
    yield
    scheduler.shutdown(wait=False)


app = FastAPI(title="FintechCRM — Cobrança via WhatsApp", lifespan=lifespan)

_hosts_permitidos = [h.strip().lower() for h in settings.allowed_hosts.split(",") if h.strip()]


def _host_permitido(host: str | None) -> bool:
    host = (host or "").lower().rstrip(".")
    return bool(host) and any(host == h or (h.startswith("*.") and host.endswith(h[1:])) for h in _hosts_permitidos)


@app.middleware("http")
async def _somente_dominio_permitido(request: Request, call_next):
    """403 para quem não chegou por um domínio permitido (Host) e para requisição de
    navegador vinda de outro site (Origin). Sem Origin passa: webhook, /media e o
    healthcheck não mandam. Registrado antes do CORS: o 403 sai com os cabeçalhos dele."""

    origin = request.headers.get("origin")
    if not _host_permitido(request.url.hostname) or (origin is not None and not _host_permitido(urlparse(origin).hostname)):
        return JSONResponse({"detail": "Forbidden"}, status_code=403)
    return await call_next(request)


_cors_origins = [o.strip() for o in settings.cors_allowed_origins.split(",") if o.strip()]
if not _cors_origins:
    _cors_origins = ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    # necessário para o navegador mandar o cookie httpOnly de sessão em
    # requisições do frontend (ver app/routers/auth.py); mesmo com
    # allow_origins=["*"], o Starlette reflete a origem exata da requisição
    # em vez de "*" quando allow_credentials=True, como o CORS exige.
    allow_credentials=True,
    # sem isso o navegador esconde o nome do arquivo das exportações .xlsx
    expose_headers=["Content-Disposition"],
)



@app.exception_handler(seta_client.SetaOcupado)
@app.exception_handler(cache.CacheOcupado)
async def _consulta_ocupada(request: Request, exc: Exception):
    """Muitas consultas pesadas ao SETA em andamento (ou a mesma ainda sendo
    calculada): não é falha do ERP, é pedir de novo daqui a pouco (429, não 503)."""

    return JSONResponse({"detail": str(exc)}, status_code=429, headers={"Retry-After": "10"})


app.mount("/media", StaticFiles(directory=settings.media_dir), name="media")

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(meta_tokens.router)
app.include_router(numbers.router)
app.include_router(templates.router)
app.include_router(faixas.router)
app.include_router(uploads.router)
app.include_router(dashboard.router)
app.include_router(reports.router)
app.include_router(seta.router)
app.include_router(blacklist.router)
app.include_router(cobranca.router)
app.include_router(config_cobranca.router)
app.include_router(leads.router)
app.include_router(google.router)
app.include_router(lojas.router)
app.include_router(chatwoot.router)
app.include_router(remarketing.router)
app.include_router(campanhas.router)
app.include_router(pausas.router)


@app.get("/health")
def health():
    return {"status": "ok"}
