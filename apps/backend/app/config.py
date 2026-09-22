from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://fintechcrm:change-me@db:5432/fintechcrm"

    jwt_secret: str = "change-me-too"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12

    admin_email: str = "admin@topfama.com.br"
    admin_password: str = "change-me-admin"

    encryption_key: str = ""
    meta_graph_api_version: str = "v21.0"

    # SETA (ERP) — Postgres externo, só leitura. Vazio = integração desligada:
    # o backend sobe normalmente e os endpoints /seta respondem 503.
    seta_db_host: str = ""
    seta_db_port: int = 5432
    seta_db_name: str = "seta"
    seta_db_user: str = ""
    seta_db_password: str = ""
    seta_db_connect_timeout_seconds: int = 10
    # Teto por consulta: o ERP é produção e a tabela de títulos passa de 27M de linhas.
    seta_db_statement_timeout_seconds: int = 120

    # Google (OAuth2) — só para ler a planilha de lojas. Vazio = integração desligada.
    google_client_id: str = ""
    google_client_secret: str = ""
    # Precisa estar cadastrada, idêntica, nas "URIs de redirecionamento autorizadas" do cliente OAuth.
    google_redirect_uri: str = "http://localhost:8000/google/oauth/callback"
    # Para onde o navegador volta depois do consentimento.
    google_frontend_url: str = "http://localhost:5173"
    google_sheet_lojas_id: str = "1QYHjtEjmlJ_4WL_K95TOMV9X63wfF2V5bmK0LGOQ9F0"
    google_sheet_lojas_gid: int = 113434922

    media_dir: str = "/app/media"

    # Origens liberadas no CORS, separadas por vírgula. "*" (padrão) mantém o
    # comportamento atual para não quebrar quem já está rodando; em produção,
    # configure com o(s) domínio(s) real(is) do frontend.
    cors_allowed_origins: str = "*"

    # Cookie de sessão (ver app/routers/auth.py) só deve ir sem o atributo
    # Secure em desenvolvimento local sobre http puro — em produção (https)
    # mantenha True; o navegador ignora Set-Cookie com Secure fora de https.
    cookie_secure: bool = True

    dispatch_worker_interval_seconds: int = 5
    # Fuso horário usado para interpretar a janela de agendamento (dias/hora
    # início/fim) configurada em cada disparo — o servidor roda em UTC, mas
    # quem configura a janela pensa em horário de Brasília.
    business_timezone: str = "America/Sao_Paulo"

    # Cache dos relatórios pesados do SETA (ver app/cache.py).
    redis_url: str = "redis://redis:6379/0"


settings = Settings()
