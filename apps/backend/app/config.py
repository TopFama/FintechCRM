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

    media_dir: str = "/app/media"

    dispatch_worker_interval_seconds: int = 5


settings = Settings()
