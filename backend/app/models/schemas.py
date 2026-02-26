from pydantic import BaseModel
from datetime import datetime, date
from typing import Optional


# --- Company ---

class CompanyBase(BaseModel):
    ticker: str
    name: str
    cik: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None
    exchange: Optional[str] = None
    fiscal_year_end: Optional[str] = None


class CompanyResponse(CompanyBase):
    id: int
    created_at: datetime


class CompanySearchResult(BaseModel):
    ticker: str
    name: str
    exchange: Optional[str] = None


# --- Financial Data ---

class FinancialStatement(BaseModel):
    period: str  # e.g., "2024-12-31"
    period_type: str  # "annual" | "quarterly"
    data: dict  # Key-value pairs of financial line items


class FinancialStatementsResponse(BaseModel):
    ticker: str
    statement_type: str  # "income_statement" | "balance_sheet" | "cash_flow"
    period_type: str
    statements: list[FinancialStatement]


class KeyMetrics(BaseModel):
    ticker: str
    price: Optional[float] = None
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    forward_pe: Optional[float] = None
    pb_ratio: Optional[float] = None
    ps_ratio: Optional[float] = None
    debt_to_equity: Optional[float] = None
    current_ratio: Optional[float] = None
    roe: Optional[float] = None
    roa: Optional[float] = None
    net_margin: Optional[float] = None
    gross_margin: Optional[float] = None
    operating_margin: Optional[float] = None
    eps: Optional[float] = None
    eps_growth: Optional[float] = None
    revenue_growth: Optional[float] = None
    free_cash_flow: Optional[float] = None
    fcf_yield: Optional[float] = None
    dividend_yield: Optional[float] = None
    beta: Optional[float] = None


# --- Graham Score ---

class GrahamCriterion(BaseModel):
    name: str
    description: str
    passed: bool
    value: Optional[str] = None
    threshold: Optional[str] = None


class GrahamScoreResponse(BaseModel):
    ticker: str
    score: int  # 0-7
    max_score: int  # 7
    criteria: list[GrahamCriterion]
    graham_number: Optional[float] = None
    margin_of_safety: Optional[float] = None  # % above/below intrinsic value


# --- Growth Lens ---

class GrowthMetrics(BaseModel):
    ticker: str
    revenue_growth_rates: list[dict]  # [{period, growth_rate}]
    cash_on_hand: Optional[float] = None
    burn_rate: Optional[float] = None  # Quarterly cash burn
    cash_runway_quarters: Optional[float] = None
    share_count_history: list[dict]  # [{period, shares_outstanding}]
    dilution_rate: Optional[float] = None  # Annual % dilution
    rd_expense: Optional[float] = None
    rd_as_pct_revenue: Optional[float] = None
    insider_buys_6m: Optional[int] = None
    insider_sells_6m: Optional[int] = None


# --- Filings ---

class Filing(BaseModel):
    filing_type: str
    filing_date: date
    accession_number: str
    filing_url: Optional[str] = None
    description: Optional[str] = None


class FilingsResponse(BaseModel):
    ticker: str
    filings: list[Filing]
    total_count: int


# --- Valuation ---

class DCFInput(BaseModel):
    growth_rate: float  # e.g., 0.10 for 10%
    discount_rate: float  # e.g., 0.10 for 10%
    terminal_growth_rate: float  # e.g., 0.03 for 3%
    projection_years: int = 10
    fcf_override: Optional[float] = None  # Override current FCF


class DCFResult(BaseModel):
    ticker: str
    intrinsic_value_per_share: float
    current_price: Optional[float] = None
    margin_of_safety: Optional[float] = None
    projected_fcf: list[dict]  # [{year, fcf}]
    terminal_value: float
    assumptions: DCFInput


class ScenarioInput(BaseModel):
    name: str  # "Bull", "Base", "Bear"
    revenue_growth_rate: float
    years_to_profitability: Optional[int] = None
    terminal_margin: float
    discount_rate: float
    annual_dilution: float = 0.0
    probability: float = 0.333  # Weight for probability-weighted value


class ScenarioModelInput(BaseModel):
    scenarios: list[ScenarioInput]


class ScenarioResult(BaseModel):
    ticker: str
    current_price: Optional[float] = None
    scenarios: list[dict]  # [{name, implied_value, probability}]
    probability_weighted_value: float
    upside_downside: Optional[float] = None  # % vs current price


# --- Watchlist ---

class WatchlistItemCreate(BaseModel):
    ticker: str
    notes: Optional[str] = None
    target_price: Optional[float] = None


class WatchlistItemUpdate(BaseModel):
    notes: Optional[str] = None
    target_price: Optional[float] = None


class WatchlistItemResponse(BaseModel):
    id: int
    ticker: str
    company_name: Optional[str] = None
    notes: Optional[str] = None
    target_price: Optional[float] = None
    current_price: Optional[float] = None
    price_change_pct: Optional[float] = None
    added_at: datetime


class AlertResponse(BaseModel):
    ticker: str
    current_price: float
    target_price: float
    distance_pct: float  # How close to target (%)
    message: str


# --- Release Notes ---

class ReleaseNoteSection(BaseModel):
    type: str  # "new_feature" | "enhancement" | "bug_fix"
    label: str
    items: list[str]


class ReleaseNote(BaseModel):
    version: str
    date: str
    title: str
    summary: str
    sections: list[ReleaseNoteSection]


class ReleaseNotesResponse(BaseModel):
    releases: list[ReleaseNote]


# --- Value Screener ---

class ScreenerWarning(BaseModel):
    """A single warning flag on a screened stock (e.g., high debt, negative earnings)."""
    code: str               # Machine-readable identifier (e.g., "high_debt")
    severity: str           # "high" | "medium" | "low"
    message: str            # Human-readable explanation for tooltip display


class ScreenerScoreResponse(BaseModel):
    """A single stock's screener result — displayed as one row in the Value Screener table."""
    ticker: str
    company_name: Optional[str] = None
    sector: Optional[str] = None
    industry: Optional[str] = None

    # Key metrics for display columns
    price: Optional[float] = None
    market_cap: Optional[float] = None
    pe_ratio: Optional[float] = None
    pb_ratio: Optional[float] = None
    roe: Optional[float] = None
    debt_to_equity: Optional[float] = None
    dividend_yield: Optional[float] = None

    # Value indicators
    graham_number: Optional[float] = None
    margin_of_safety: Optional[float] = None  # % — positive = undervalued
    fcf_yield: Optional[float] = None
    earnings_yield: Optional[float] = None

    # Composite ranking
    composite_score: float          # 0-100 weighted blend
    rank: Optional[int] = None      # 1 = best value

    # Warning flags (informational, not filters)
    warnings: list[ScreenerWarning] = []

    scored_at: Optional[datetime] = None


class ScreenerResultsResponse(BaseModel):
    """Paginated response from GET /api/screener/results."""
    results: list[ScreenerScoreResponse]
    total_count: int
    last_scan_completed_at: Optional[datetime] = None


class ScannerStatusResponse(BaseModel):
    """Current state of the background scanner — for progress display."""
    is_running: bool
    tickers_scanned: int
    tickers_total: int
    current_ticker: Optional[str] = None
    last_full_scan_started_at: Optional[datetime] = None
    last_full_scan_completed_at: Optional[datetime] = None
    last_error: Optional[str] = None
