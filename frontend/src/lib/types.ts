// Company
export interface CompanySearchResult {
  ticker: string
  name: string
  exchange?: string
}

export interface Company {
  id: number
  ticker: string
  name: string
  cik?: string
  sector?: string
  industry?: string
  exchange?: string
  fiscal_year_end?: string
  created_at: string
}

// Financial Statements
export interface FinancialStatement {
  period: string
  [key: string]: string | number | null
}

export interface FinancialStatementsResponse {
  ticker: string
  statement_type: string
  period_type: string
  statements: FinancialStatement[]
}

// Key Metrics
export interface KeyMetrics {
  ticker: string
  name?: string
  price?: number
  market_cap?: number
  pe_ratio?: number
  forward_pe?: number
  pb_ratio?: number
  ps_ratio?: number
  debt_to_equity?: number
  current_ratio?: number
  roe?: number
  roa?: number
  net_margin?: number
  gross_margin?: number
  operating_margin?: number
  eps?: number
  revenue_growth?: number
  free_cash_flow?: number
  total_revenue?: number
  dividend_yield?: number
  beta?: number
  book_value?: number
  fifty_two_week_high?: number
  fifty_two_week_low?: number
}

// Graham Score
export interface GrahamCriterion {
  name: string
  description: string
  passed: boolean
  value?: string
  threshold?: string
}

export interface GrahamScoreResponse {
  ticker: string
  score: number
  max_score: number
  criteria: GrahamCriterion[]
  graham_number?: number
  margin_of_safety?: number
}

// Growth Metrics
export interface GrowthMetrics {
  ticker: string
  revenue_growth_rates: { period: string; growth_rate: number }[]
  cash_on_hand?: number
  burn_rate?: number
  cash_runway_quarters?: number
  share_count_history: { period: string; shares: number }[]
  dilution_rate?: number
  rd_expense?: number
  rd_as_pct_revenue?: number
  insider_buys_6m?: number
  insider_sells_6m?: number
}

// Filings
export interface Filing {
  filing_type: string
  filing_date: string
  accession_number: string
  filing_url?: string
  description?: string
}

export interface FilingsResponse {
  ticker: string
  filings: Filing[]
  total_count: number
}

// Valuation
export interface DCFInput {
  growth_rate: number
  discount_rate: number
  terminal_growth_rate: number
  projection_years?: number
  fcf_override?: number
}

export interface DCFResult {
  ticker: string
  intrinsic_value_per_share: number
  current_price?: number
  margin_of_safety?: number
  projected_fcf: { year: number; fcf: number; present_value: number }[]
  terminal_value: number
  assumptions: DCFInput
}

export interface ScenarioInput {
  name: string
  revenue_growth_rate: number
  years_to_profitability?: number
  terminal_margin: number
  discount_rate: number
  annual_dilution?: number
  probability?: number
}

export interface ScenarioModelInput {
  scenarios: ScenarioInput[]
}

export interface ScenarioResult {
  ticker: string
  current_price?: number
  scenarios: {
    name: string
    implied_value: number
    probability: number
    projected_revenue_5y: number
    projected_earnings_5y: number
  }[]
  probability_weighted_value: number
  upside_downside?: number
}

// Watchlist
export interface WatchlistItem {
  id: number
  ticker: string
  company_name?: string
  notes?: string
  target_price?: number
  current_price?: number
  price_change_pct?: number
  added_at: string
}

export interface Alert {
  ticker: string
  company_name?: string
  current_price: number
  target_price: number
  distance_pct: number
  message: string
}

// Release Notes
export interface ReleaseNoteSection {
  type: 'new_feature' | 'enhancement' | 'bug_fix'
  label: string
  items: string[]
}

export interface ReleaseNote {
  version: string
  date: string
  title: string
  summary: string
  sections: ReleaseNoteSection[]
}

export interface ReleaseNotesResponse {
  releases: ReleaseNote[]
}
