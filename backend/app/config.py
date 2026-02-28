from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    # Supabase
    supabase_url: str = ""
    supabase_publishable_key: str = ""
    supabase_secret_key: str = ""
    supabase_jwt_secret: str = ""  # JWT signing secret (Supabase dashboard → Settings → API → JWT Secret)
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

    # AI / OpenAI
    openai_api_key: str = ""          # Empty = AI features disabled (returns 503)
    openai_model: str = "gpt-4.1"
    ai_max_tokens: int = 4096

    # RAG / Filing indexing
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = 1536
    chunk_max_tokens: int = 512
    chunk_overlap_tokens: int = 50
    rag_max_context_tokens: int = 8000      # Max filing context tokens injected per tool call
    rag_max_tool_iterations: int = 3        # Max tool-call rounds per chat turn
    topic_extraction_model: str = "gpt-4o-mini"
    filing_index_max_10k: int = 3            # Most recent N annual filings to index
    filing_index_max_10q: int = 5            # Most recent N quarterly filings to index
    filing_index_max_8k: int = 10            # Most recent N current reports (small docs, material events)

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
