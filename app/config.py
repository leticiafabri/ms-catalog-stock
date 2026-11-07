from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = (
        "postgresql+psycopg://catalog:catalog@localhost:5432/catalog_db"
    )
    rabbitmq_url: str = "amqp://catalog:catalog@localhost:5672/"
    rabbitmq_exchange: str = "app.events"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
