"""Fetch full SEC filing HTML documents from EDGAR.

Reuses the EDGAR rate limiter and User-Agent headers so we stay within
SEC's 10 req/sec policy.  Filing URLs come from the filings_cache table
(populated by edgar.parse_filings_from_submissions).
"""

import logging
import time

import httpx

from app.config import get_settings
from app.utils.rate_limiter import edgar_rate_limiter

logger = logging.getLogger(__name__)


class FilingFetchError(Exception):
    """Raised when a filing document cannot be retrieved."""


def _get_headers() -> dict:
    settings = get_settings()
    return {
        "User-Agent": settings.sec_edgar_user_agent,
        "Accept": "text/html, application/xhtml+xml, */*",
    }


async def fetch_filing_html(filing_url: str) -> str:
    """Fetch the full HTML content of an SEC filing from EDGAR.

    Args:
        filing_url: Direct URL to the filing document (from filings_cache.filing_url).

    Returns:
        Raw HTML string of the filing.

    Raises:
        FilingFetchError: On HTTP errors, timeouts, or non-HTML content.
    """
    await edgar_rate_limiter.acquire()
    start = time.time()

    async with httpx.AsyncClient() as client:
        try:
            resp = await client.get(filing_url, headers=_get_headers(), timeout=30, follow_redirects=True)
            resp.raise_for_status()
        except httpx.TimeoutException:
            raise FilingFetchError(f"Timeout fetching {filing_url}")
        except httpx.HTTPStatusError as e:
            raise FilingFetchError(f"HTTP {e.response.status_code} fetching {filing_url}")

    content_type = resp.headers.get("content-type", "")
    if "pdf" in content_type.lower():
        raise FilingFetchError(f"Skipping PDF filing: {filing_url}")

    html = resp.text
    elapsed = time.time() - start
    logger.info(f"Fetched {filing_url} in {elapsed:.1f}s ({len(html):,} bytes)")
    return html
