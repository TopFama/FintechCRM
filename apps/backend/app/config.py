from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://fintechcrm:change-me@db:5432/fintechcrm"

    jwt_secret: str = "change-me-too"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 12

    admin_email: str = "admin@topfama.com.br"
    admin_password: str = "change-me-admin"

    meta_access_token: str = ""
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

    media_dir: str = "/app/media"

    dispatch_worker_interval_seconds: int = 5


settings = Settings()
