from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Supabase
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_secret_key: str = ""
    database_url: str = ""

    # SEC EDGAR
    sec_edgar_user_agent: str = "Investron research@investron.app"

    # App
    app_name: str = "Investron"
    debug: bool = False
    cors_origins: str = "http://localhost:5173"

    # Cache TTLs (seconds)
    cache_ttl_financials: int = 86400  # 24 hours
    cache_ttl_filings: int = 86400  # 24 hours
    cache_ttl_prices: int = 900  # 15 minutes
    cache_ttl_company_info: int = 604800  # 7 days

    # Value Screener background scanner settings
    # All configurable via env vars (e.g. SCANNER_ENABLED=false for local dev)
    scanner_enabled: bool = True          # Set False to disable background scanning
    scanner_batch_size: int = 10          # Tickers fetched per batch
    scanner_batch_delay: float = 5.0      # Seconds between batches (respects rate limiter)
    scanner_interval_seconds: int = 3600  # Seconds between full scans (1 hour)
    scanner_ticker_timeout: int = 15      # Per-ticker yfinance fetch timeout

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
