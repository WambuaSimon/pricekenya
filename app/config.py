from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "sqlite:///./pricekenya.db"
    base_url: str = "http://localhost:8000"
    jumia_affiliate_id: str = ""
    scraper_user_agent: str = "PriceKenyaBot/0.1"
    scraper_request_delay_seconds: float = 2.0
    # Resend transactional email (used by alerts/dispatcher.py)
    resend_api_key: str = ""
    alerts_from_email: str = "PriceKenya Alerts <alerts@pricekenya.co.ke>"
    # HMAC key for signing one-click unsubscribe tokens. MUST be set in prod;
    # if empty, unsubscribe links won't verify. Generate with:
    #     python -c "import secrets; print(secrets.token_urlsafe(32))"
    secret_key: str = ""


settings = Settings()
