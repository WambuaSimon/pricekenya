from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./pricekenya.db"
    base_url: str = "http://localhost:8000"
    jumia_affiliate_id: str = ""
    scraper_user_agent: str = "PriceKenyaBot/0.1"
    scraper_request_delay_seconds: float = 2.0
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    alerts_from_email: str = "alerts@pricekenya.example"


settings = Settings()
