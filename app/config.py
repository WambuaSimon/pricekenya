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

    # --- LLM matching fallback (Phase 0, matching/llm_extract.py) ---
    # Master switch. Off by default; flip via env var to activate the Gemini
    # fallback when the regex parser can't extract from a title.
    llm_fallback_enabled: bool = False
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash-lite"
    gemini_timeout_seconds: float = 3.0
    # Guardrail against a broken scraper burning the free-tier daily budget.
    # Applied per category (utc-day-window count against llmextractionlog).
    llm_daily_cap_per_category: int = 500

    # --- Embedding-based reconciliation (Phase 1, matching/embeddings.py) ---
    # Master switch. Off by default; only scraper/CLI entrypoints call the
    # encoder so the web app never loads sentence-transformers.
    embedding_enabled: bool = False

    # --- Admin ---
    # Shared secret for /admin/* routes (merge-review). Sent as X-Admin-Key.
    # Leave empty to gate the routes shut in prod.
    admin_key: str = ""

    # --- Reviews ---
    # Post-moderation is the default (matches Prisjakt). Flip to True if
    # a spam problem develops: reviews still email-verify but stay pending
    # until an admin explicitly publishes them from /admin/reviews.
    reviews_require_approval: bool = False


settings = Settings()
