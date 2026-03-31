/**
 * BuffettCard — Buffett 4-Rules Intrinsic Value Calculator dashboard card.
 *
 * Evaluates a selected stock against Warren Buffett's four investing rules:
 *   Rule 1 — Vigilant Leadership (D/E, Current Ratio, ROE, P/B)
 *   Rule 2 — Long-Term Prospects (EPS & Revenue trends, AI deep-dive)
 *   Rule 3 — Stable & Understandable (multi-year sparkline trends)
 *   Rule 4 — Intrinsic Value (BuffettsBooks.com BV DCF formula)
 *
 * Data comes from GET /api/buffett/{ticker} (yfinance + EDGAR, cached 15min).
 * The Rule 2 AI analysis streams on-demand from POST /api/buffett/{ticker}/ai-analysis.
 * The treasury rate can be overridden locally — IV updates in real-time without a server call.
 */

import { useState, useRef, useCallback, useMemo } from 'react'
import { createPortal } from 'react-dom'
import { LineChart, Line, Tooltip, ResponsiveContainer } from 'recharts'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  BookOpen, Sparkles, TrendingUp, TrendingDown, Minus,
  AlertTriangle, RefreshCw, Square, Loader2, GripHorizontal, Info,
} from 'lucide-react'
import { useBuffettAnalysis, useBuffettAI, useBuffettValuationAI } from '@/hooks/useBuffett'
import { TickerAutocomplete } from '@/components/search/TickerAutocomplete'
import { useResizable } from '@/hooks/useResizable'
import type { BuffettHistoryPoint, BuffettRule4 } from '@/lib/types'

// ============================================================================
// Formatting helpers
// ============================================================================

function fmtCurrency(v?: number | null): string {
  if (v == null) return 'N/A'
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', minimumFractionDigits: 2 }).format(v)
}

function fmtPct(v?: number | null, decimals = 1): string {
  if (v == null) return 'N/A'
  return `${(v * 100).toFixed(decimals)}%`
}

function fmtRatio(v?: number | null, decimals = 2): string {
  if (v == null) return 'N/A'
  return `${v.toFixed(decimals)}x`
}

// ============================================================================
// Pass/fail helpers
// ============================================================================

type PassFail = 'pass' | 'warn' | 'fail' | 'na'

function ruleStatusBadge(status: PassFail) {
  if (status === 'pass') return <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-gain/15 text-gain">PASS</span>
  if (status === 'warn') return <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400">MIXED</span>
  if (status === 'fail') return <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-loss/15 text-loss">FAIL</span>
  return <span className="text-xs font-semibold px-2 py-0.5 rounded-full bg-[var(--muted)] text-[var(--muted-foreground)]">N/A</span>
}

function metricStatus(status: PassFail) {
  if (status === 'pass') return <span className="text-gain text-sm">✓</span>
  if (status === 'warn') return <span className="text-amber-400 text-sm">⚠</span>
  if (status === 'fail') return <span className="text-loss text-sm">✗</span>
  return null
}

function deStatus(de?: number | null): PassFail {
  // yfinance D/E is in % form (42.3 = 0.423 ratio). Threshold: <50 = pass, <100 = warn, >=100 = fail
  if (de == null) return 'na'
  if (de < 0) return 'fail'      // negative equity
  if (de < 50) return 'pass'
  if (de < 100) return 'warn'
  return 'fail'
}

function crStatus(cr?: number | null): PassFail {
  if (cr == null) return 'na'
  if (cr > 1.5) return 'pass'
  if (cr >= 1.0) return 'warn'
  return 'fail'
}

function roeStatus(roe?: number | null): PassFail {
  if (roe == null) return 'na'
  if (roe > 0.15) return 'pass'
  if (roe >= 0.10) return 'warn'
  return 'fail'
}

function rule1Overall(de?: number | null, cr?: number | null, roe?: number | null): PassFail {
  const statuses = [deStatus(de), crStatus(cr), roeStatus(roe)]
  if (statuses.every(s => s === 'pass' || s === 'na')) return 'pass'
  if (statuses.some(s => s === 'fail')) return 'fail'
  return 'warn'
}

/** Determine trend direction from a history series: up/flat/down */
function trendDir(series: BuffettHistoryPoint[]): 'up' | 'flat' | 'down' {
  if (series.length < 2) return 'flat'
  const first = series[0].value
  const last = series[series.length - 1].value
  if (first === 0) return 'flat'
  const change = (last - first) / Math.abs(first)
  if (change > 0.05) return 'up'
  if (change < -0.05) return 'down'
  return 'flat'
}

/**
 * Rule 3 pass/fail logic: all four trends must be going in the "right" direction.
 * - BV/share: up is good
 * - D/E: down is good (less leverage over time)
 * - EPS: up is good
 * - ROE: up or stable is good
 */
function rule3Overall(
  bv: BuffettHistoryPoint[],
  de: BuffettHistoryPoint[],
  eps: BuffettHistoryPoint[],
  roe: BuffettHistoryPoint[],
): PassFail {
  const bvGood = trendDir(bv) === 'up'
  const deGood = trendDir(de) !== 'up'   // flat or declining is good
  const epsGood = trendDir(eps) === 'up'
  const roeGood = trendDir(roe) !== 'down'
  const passCount = [bvGood, deGood, epsGood, roeGood].filter(Boolean).length
  if (passCount === 4) return 'pass'
  if (passCount >= 2) return 'warn'
  return 'fail'
}

// ============================================================================
// Tooltip component — portal-based so it escapes overflow containers
// ============================================================================

function MetricTooltip({ text }: { text: string }) {
  const [pos, setPos] = useState<{ top: number; left: number } | null>(null)
  const triggerRef = useRef<HTMLSpanElement>(null)

  const show = useCallback(() => {
    const el = triggerRef.current
    if (!el) return
    const rect = el.getBoundingClientRect()
    setPos({ top: rect.top - 8, left: rect.left + rect.width / 2 })
  }, [])

  const hide = useCallback(() => setPos(null), [])

  return (
    <>
      <span
        ref={triggerRef}
        onMouseEnter={show}
        onMouseLeave={hide}
        className="inline-flex items-center cursor-help text-[var(--muted-foreground)] opacity-50 hover:opacity-100 ml-1 transition-opacity"
        aria-label="More information"
      >
        <Info className="w-3 h-3" />
      </span>
      {pos && createPortal(
        <div
          style={{ position: 'fixed', top: pos.top, left: pos.left, transform: 'translate(-50%, -100%)' }}
          className="z-50 max-w-xs bg-[var(--card)] border border-[var(--border)] rounded-lg px-3 py-2 text-xs text-[var(--muted-foreground)] shadow-xl pointer-events-none leading-relaxed"
        >
          {text}
        </div>,
        document.body,
      )}
    </>
  )
}

// ============================================================================
// Section header — rule title + pass/fail badge
// ============================================================================

function RuleHeader({ number, title, status }: { number: number; title: string; status: PassFail }) {
  return (
    <div className="flex items-center justify-between pb-2 border-b border-[var(--border)]">
      <div className="flex items-center gap-2">
        <span className="text-xs font-bold text-[var(--accent)] uppercase tracking-wider">Rule {number}</span>
        <span className="text-sm font-semibold">{title}</span>
      </div>
      {ruleStatusBadge(status)}
    </div>
  )
}

// ============================================================================
// Metric row — label + tooltip + value + status icon
// ============================================================================

function MetricRow({
  label, tooltip, value, status, subtext,
}: {
  label: string
  tooltip: string
  value: React.ReactNode
  status?: PassFail
  subtext?: string
}) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-xs text-[var(--muted-foreground)] flex items-center gap-0 shrink-0">
        {label}
        <MetricTooltip text={tooltip} />
      </span>
      <div className="flex items-center gap-2 ml-2">
        {subtext && <span className="text-xs text-[var(--muted-foreground)]">{subtext}</span>}
        <span className="text-sm font-mono font-medium">{value}</span>
        {status && metricStatus(status)}
      </div>
    </div>
  )
}

// ============================================================================
// Mini sparkline — stripped-down LineChart for trend visualization
// ============================================================================

function Sparkline({
  data,
  color,
  height = 44,
  showDots = false,
}: {
  data: { value: number }[]
  color: string
  height?: number
  showDots?: boolean
}) {
  if (!data.length) return <div style={{ height }} className="flex items-center justify-center text-[var(--muted-foreground)] text-xs">no data</div>

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={data} margin={{ top: 2, bottom: 2, left: 2, right: 2 }}>
          <Tooltip
            formatter={(v: number | undefined) => v != null ? v.toFixed(2) : '—'}
            contentStyle={{ fontSize: 10, padding: '2px 6px', background: 'var(--card)', border: '1px solid var(--border)' }}
          />
          <Line
            type="monotone"
            dataKey="value"
            stroke={color}
            strokeWidth={1.5}
            dot={showDots ? { r: 2, fill: color } : false}
            activeDot={{ r: 3 }}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

// Trend arrow icon + last value display
function TrendCell({
  series,
  goodDir,
  formatVal,
}: {
  series: BuffettHistoryPoint[]
  goodDir: 'up' | 'down' | 'either'
  formatVal: (v: number) => string
}) {
  const dir = trendDir(series)
  const last = series.length ? series[series.length - 1].value : null

  const isGood = goodDir === 'either' ? dir !== 'flat' : dir === goodDir
  const isBad = goodDir === 'either' ? false : dir === (goodDir === 'up' ? 'down' : 'up')
  const color = isGood ? 'text-gain' : isBad ? 'text-loss' : 'text-[var(--muted-foreground)]'

  return (
    <div className={`flex items-center gap-1 text-xs ${color}`}>
      {dir === 'up' ? <TrendingUp className="w-3 h-3" /> : dir === 'down' ? <TrendingDown className="w-3 h-3" /> : <Minus className="w-3 h-3" />}
      <span className="font-mono">{last != null ? formatVal(last) : '—'}</span>
    </div>
  )
}

// ============================================================================
// Rule 4 override IV computation — recomputes IV with a custom treasury rate
// ============================================================================

function computeIV(
  currentBV: number,
  bvGrowthRate: number,
  annualDividend: number,
  treasuryRate: number,
): { bvFuture: number; pvOfBV: number; pvOfDivs: number; iv: number } {
  const r = Math.max(0.001, treasuryRate)
  const bvFuture = currentBV * (1 + bvGrowthRate) ** 10
  const pvOfBV = bvFuture / (1 + r) ** 10
  const pvOfDivs = annualDividend * (1 - (1 + r) ** -10) / r
  return {
    bvFuture: Math.round(bvFuture * 100) / 100,
    pvOfBV: Math.round(pvOfBV * 100) / 100,
    pvOfDivs: Math.round(pvOfDivs * 100) / 100,
    iv: Math.round((pvOfBV + pvOfDivs) * 100) / 100,
  }
}

// ============================================================================
// Rule 4 section — IV calculation with live treasury rate override
// ============================================================================

function Rule4Section({ rule4 }: { rule4: BuffettRule4 }) {
  const [rateInput, setRateInput] = useState<string>(
    rule4.treasury_rate != null ? (rule4.treasury_rate * 100).toFixed(2) : '',
  )

  const overrideRate = useMemo(() => {
    const parsed = parseFloat(rateInput)
    return isNaN(parsed) ? rule4.treasury_rate : parsed / 100
  }, [rateInput, rule4.treasury_rate])

  // Recompute IV with potentially overridden rate
  const computed = useMemo(() => {
    if (
      rule4.current_bv != null &&
      rule4.bv_growth_rate != null &&
      rule4.annual_dividend != null &&
      overrideRate != null
    ) {
      return computeIV(rule4.current_bv, rule4.bv_growth_rate, rule4.annual_dividend, overrideRate)
    }
    return null
  }, [rule4.current_bv, rule4.bv_growth_rate, rule4.annual_dividend, overrideRate])

  const iv = computed?.iv ?? rule4.intrinsic_value
  const pvOfBV = computed?.pvOfBV ?? rule4.pv_of_bv
  const pvOfDivs = computed?.pvOfDivs ?? rule4.pv_of_divs
  const bvFuture = computed?.bvFuture ?? rule4.bv_future

  const mos = iv != null && rule4.current_price
    ? (iv - rule4.current_price) / rule4.current_price * 100
    : rule4.margin_of_safety_pct

  const ivStatus: PassFail = mos == null ? 'na' : mos >= 0 ? 'pass' : 'fail'

  const isCustomRate = Math.abs((parseFloat(rateInput) / 100) - (rule4.treasury_rate ?? 0)) > 0.0001

  return (
    <div className="space-y-1.5">
      <RuleHeader number={4} title="Intrinsic Value" status={rule4.inapplicable ? 'na' : ivStatus} />

      {rule4.inapplicable && (
        <div className="flex items-start gap-2 p-2 rounded bg-amber-500/10 text-xs text-amber-400">
          <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <span>{rule4.inapplicable_reason}</span>
        </div>
      )}

      {rule4.high_growth_warning && (
        <div className="flex items-start gap-2 p-2 rounded bg-blue-500/10 text-xs text-blue-400">
          <Info className="w-3.5 h-3.5 shrink-0 mt-0.5" />
          <span>BV growth rate &gt;20%/yr — stability assumption may not hold for high-growth companies. IV may be overstated.</span>
        </div>
      )}

      <MetricRow
        label="BV Growth Rate / yr"
        tooltip={`Annualized book value growth: (Current BV ÷ Oldest BV)^(1 ÷ Years) − 1. This rate is used to project where book value will be in 10 years. The longer the history, the more reliable the estimate. Based on ${rule4.years_between ?? '?'} years of EDGAR balance sheet history.`}
        value={rule4.bv_growth_rate != null ? fmtPct(rule4.bv_growth_rate) : 'N/A'}
        subtext={rule4.oldest_bv != null ? `${fmtCurrency(rule4.oldest_bv)} → ${fmtCurrency(rule4.current_bv)}` : undefined}
      />

      <MetricRow
        label="Annual Dividend"
        tooltip={`Cash paid to shareholders per share per year (${rule4.dividend_source === 'dividendRate' ? 'dividendRate from yfinance' : rule4.dividend_source === 'price × yield' ? 'computed as Current Price × Dividend Yield (dividendRate not available)' : 'no dividend — PV of dividends will be $0'}). This is the income stream you receive while holding the stock. Used in the present value of annuity calculation.`}
        value={rule4.annual_dividend ? fmtCurrency(rule4.annual_dividend) : '$0.00'}
        subtext={rule4.dividend_yield ? `yield: ${fmtPct(rule4.dividend_yield)}` : undefined}
      />

      {/* Treasury rate with override input */}
      <div className="flex items-center justify-between py-1.5">
        <span className="text-xs text-[var(--muted-foreground)] flex items-center gap-0 shrink-0">
          10Y Treasury Rate
          <MetricTooltip text="The current yield on 10-Year U.S. Treasury Notes (risk-free rate). Used as the discount rate in the intrinsic value formula — represents what your money could safely earn elsewhere. Buffett uses this as the hurdle rate. Source: yfinance ^TNX (cached 24h). You can override this value to model different rate scenarios." />
        </span>
        <div className="flex items-center gap-1.5">
          {isCustomRate && <span className="text-[10px] text-amber-400 font-medium">custom</span>}
          <div className="flex items-center gap-1">
            <input
              type="number"
              value={rateInput}
              onChange={e => setRateInput(e.target.value)}
              step="0.1"
              min="0.1"
              max="20"
              className="input w-20 text-xs text-right font-mono py-0.5 px-1.5"
            />
            <span className="text-xs text-[var(--muted-foreground)]">%</span>
          </div>
          {isCustomRate && (
            <button
              onClick={() => setRateInput((rule4.treasury_rate * 100).toFixed(2))}
              className="p-0.5 hover:text-[var(--accent)] text-[var(--muted-foreground)] transition-colors"
              title="Reset to live rate"
            >
              <RefreshCw className="w-3 h-3" />
            </button>
          )}
        </div>
      </div>

      {!rule4.inapplicable && iv != null && (
        <>
          <div className="border-t border-[var(--border)] pt-2 mt-1 space-y-1.5">
            {/* Formula breakdown — show the work */}
            <div className="space-y-1 pb-1">
              <p className="text-[10px] text-[var(--muted-foreground)] font-medium uppercase tracking-wider">IV Calculation</p>
              <div className="grid grid-cols-2 gap-x-3 gap-y-0.5 text-xs text-[var(--muted-foreground)]">
                <span>BV projected (yr 10)</span>
                <span className="text-right font-mono">{bvFuture != null ? fmtCurrency(bvFuture) : '—'}</span>
                <span>PV of BV</span>
                <span className="text-right font-mono">{pvOfBV != null ? fmtCurrency(pvOfBV) : '—'}</span>
                <span>PV of dividends (10yr)</span>
                <span className="text-right font-mono">{pvOfDivs != null ? fmtCurrency(pvOfDivs) : '—'}</span>
              </div>
            </div>

            <MetricRow
              label="Intrinsic Value"
              tooltip={`IV = PV of Book Value in 10 years + PV of Dividend Annuity over 10 years. Step 1: BV_future = Current BV × (1 + BV Growth Rate)^10. Step 2: PV_of_BV = BV_future ÷ (1 + Treasury Rate)^10. Step 3: PV_of_divs = Annual Dividend × [1 − (1 + Rate)^−10] ÷ Rate. IV = PV_of_BV + PV_of_divs. Methodology: BuffettsBooks.com Rule 4 calculator.`}
              value={<span className="text-base font-bold text-[var(--foreground)]">{fmtCurrency(iv)}</span>}
            />

            <MetricRow
              label="Current Price"
              tooltip="The latest market price from yfinance. Compared against Intrinsic Value to determine margin of safety."
              value={fmtCurrency(rule4.current_price)}
            />

            {mos != null && (
              <div className="flex items-center justify-between py-1.5">
                <span className="text-xs text-[var(--muted-foreground)] flex items-center gap-0 shrink-0">
                  Margin of Safety
                  <MetricTooltip text="(Intrinsic Value − Current Price) ÷ Current Price × 100. Positive = stock is trading below estimated IV (potential buy zone). Negative = stock is above estimated IV (overvalued by this model). Buffett typically wants at least 15–25% margin of safety to account for estimation error in the growth rate." />
                </span>
                <div className="flex items-center gap-2">
                  <span className={`text-sm font-bold font-mono ${mos >= 0 ? 'text-gain' : 'text-loss'}`}>
                    {mos >= 0 ? '+' : ''}{mos.toFixed(1)}%
                  </span>
                  <span className={`text-xs font-semibold px-2 py-0.5 rounded-full ${mos >= 15 ? 'bg-gain/15 text-gain' : mos >= 0 ? 'bg-amber-500/15 text-amber-400' : 'bg-loss/15 text-loss'}`}>
                    {mos >= 15 ? 'UNDERVALUED' : mos >= 0 ? 'NEAR IV' : 'OVERVALUED'}
                  </span>
                </div>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  )
}

// ============================================================================
// Main BuffettCard component
// ============================================================================

interface BuffettCardProps {
  height?: number
  onResizeMouseDown?: (e: React.MouseEvent) => void
}

export function BuffettCard({ height, onResizeMouseDown }: BuffettCardProps) {
  const { height: resizeHeight, handleMouseDown: handleResizeMouseDown } = useResizable('buffett', 700)

  const effectiveHeight = height ?? resizeHeight

  // Ticker selection — persisted to localStorage so it survives page reloads
  const [ticker, setTicker] = useState<string | null>(() => {
    return localStorage.getItem('buffett-ticker') || null
  })
  // Separate input state so the autocomplete field responds to typing
  // (ticker = last confirmed selection; inputValue = live text in the input box)
  const [inputValue, setInputValue] = useState<string>(() => {
    return localStorage.getItem('buffett-ticker') || ''
  })

  const { data, isLoading, error, refetch } = useBuffettAnalysis(ticker)
  const aiAnalysis = useBuffettAI(ticker)
  const valuationAI = useBuffettValuationAI(ticker)

  // Stable refs so selectTicker can call resets without stale closures
  const aiResetRef = useRef(aiAnalysis.reset)
  aiResetRef.current = aiAnalysis.reset
  const valuationResetRef = useRef(valuationAI.reset)
  valuationResetRef.current = valuationAI.reset

  const selectTicker = useCallback((t: string) => {
    const upper = t.toUpperCase().trim()
    if (!upper) return
    setTicker(upper)
    setInputValue(upper)
    localStorage.setItem('buffett-ticker', upper)
    aiResetRef.current()        // clear Rule 2 AI result when ticker changes
    valuationResetRef.current() // clear Option B valuation result when ticker changes
  }, [])

  const rule1 = data?.rule1
  const rule2 = data?.rule2
  const rule3 = data?.rule3
  const rule4 = data?.rule4

  // Format year from YYYY-MM-DD period string
  const yr = (period: string) => period.slice(0, 4)

  return (
    <div
      className="card flex flex-col"
      style={effectiveHeight ? { height: effectiveHeight } : undefined}
    >
      {/* Header */}
      <div className="flex items-center justify-between pb-3 border-b border-[var(--border)] shrink-0">
        <div className="flex items-center gap-2">
          <BookOpen className="w-4 h-4 text-[var(--accent)]" />
          <h2 className="font-semibold text-sm">Buffett Scorecard</h2>
        </div>
        <div className="flex items-center gap-2">
          {data && (
            <button
              onClick={() => refetch()}
              className="p-1 rounded hover:bg-[var(--muted)] text-[var(--muted-foreground)] hover:text-[var(--foreground)] transition-colors"
              title="Refresh data"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          )}
          <div className="w-52">
            <TickerAutocomplete
              value={inputValue}
              onChange={setInputValue}
              onSelect={(r) => selectTicker(r.ticker)}
              placeholder="Select a ticker..."
              showIcon={false}
              clearOnSelect={false}
              allowRawTicker={true}
            />
          </div>
        </div>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-auto min-h-0">
        {!ticker ? (
          <div className="flex flex-col items-center justify-center h-full text-center text-[var(--muted-foreground)] gap-2 py-8">
            <BookOpen className="w-8 h-8 opacity-30" />
            <p className="text-sm">Select a ticker to evaluate against Buffett's 4 investing rules</p>
          </div>
        ) : isLoading ? (
          <div className="flex items-center justify-center h-full gap-2 text-[var(--muted-foreground)]">
            <Loader2 className="w-4 h-4 animate-spin" />
            <span className="text-sm">Loading {ticker} data...</span>
          </div>
        ) : error ? (
          <div className="flex flex-col items-center justify-center h-full gap-2 text-[var(--muted-foreground)] py-8">
            <AlertTriangle className="w-6 h-6 text-amber-400" />
            <p className="text-sm text-center">{error instanceof Error ? error.message : 'Failed to load data'}</p>
            <button onClick={() => refetch()} className="btn-primary text-xs mt-1">Retry</button>
          </div>
        ) : data && rule1 && rule2 && rule3 && rule4 ? (
          <div className="py-4 space-y-5">

            {/* ── Rule 1: Vigilant Leadership ───────────────────────────── */}
            <div className="space-y-1.5">
              <RuleHeader
                number={1}
                title="Vigilant Leadership"
                status={rule1.negative_equity ? 'fail' : rule1Overall(rule1.debt_to_equity, rule1.current_ratio, rule1.roe)}
              />

              {rule1.financial_sector_warning && (
                <div className="flex items-start gap-2 p-2 rounded bg-amber-500/10 text-xs text-amber-400">
                  <AlertTriangle className="w-3.5 h-3.5 shrink-0 mt-0.5" />
                  <span>Financial sector company — D/E thresholds don't apply (banks/insurance carry high leverage by design).</span>
                </div>
              )}

              <MetricRow
                label="D/E Ratio"
                tooltip="Debt-to-Equity = Total Long-Term Debt ÷ Shareholders' Equity. Measures financial leverage. Buffett prefers < 0.50 — companies with low debt survive recessions and don't pay excess interest. Source: yfinance debtToEquity."
                value={rule1.debt_to_equity != null ? fmtRatio(rule1.debt_to_equity / 100) : 'N/A'}
                subtext={rule1.debt_to_equity != null ? `target < 0.50x` : undefined}
                status={deStatus(rule1.debt_to_equity)}
              />
              <MetricRow
                label="Current Ratio"
                tooltip="Current Assets ÷ Current Liabilities. Measures short-term liquidity. A ratio > 1.50 means the company can comfortably cover near-term obligations. Buffett wants management that keeps the books clean. Source: yfinance currentRatio."
                value={rule1.current_ratio != null ? fmtRatio(rule1.current_ratio) : 'N/A'}
                subtext={rule1.current_ratio != null ? `target > 1.50x` : undefined}
                status={crStatus(rule1.current_ratio)}
              />
              <MetricRow
                label="ROE"
                tooltip="Return on Equity = Net Income ÷ Shareholders' Equity. Shows how efficiently management turns equity into profit. Buffett's threshold is > 15% — consistently high ROE signals a durable competitive advantage. Source: yfinance returnOnEquity."
                value={rule1.roe != null ? fmtPct(rule1.roe) : 'N/A'}
                subtext={rule1.roe != null ? `target > 15%` : undefined}
                status={roeStatus(rule1.roe)}
              />
              <MetricRow
                label="P/B Ratio"
                tooltip="Price-to-Book = Market Price per Share ÷ Book Value per Share. Shows the premium investors pay over the company's net asset value. Context only — there is no strict Buffett threshold. A high P/B may mean the market already prices in future growth, leaving less margin of safety. Lower is generally more conservative. Source: yfinance priceToBook."
                value={rule1.pb_ratio != null ? fmtRatio(rule1.pb_ratio) : 'N/A'}
                subtext="context only"
              />
            </div>

            {/* ── Rule 2: Long-Term Prospects ───────────────────────────── */}
            <div className="space-y-2">
              <RuleHeader number={2} title="Long-Term Prospects" status="na" />

              <div className="text-xs text-[var(--muted-foreground)]">
                {rule2.sector}{rule2.industry ? ` / ${rule2.industry}` : ''}
              </div>

              {/* EPS sparkline */}
              <div className="space-y-0.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-[var(--muted-foreground)] flex items-center gap-0">
                    EPS (Diluted)
                    <MetricTooltip text="Earnings Per Share = Net Income ÷ Diluted Shares Outstanding. Buffett's Rule 2 looks for consistent, growing EPS over 5–10 years — erratic or negative earnings signal an unpredictable business. Source: EDGAR annual income statements." />
                  </span>
                  <div className="flex items-center gap-2 text-xs">
                    {rule2.consecutive_positive_eps_years > 0 && (
                      <span className="text-[var(--muted-foreground)]">{rule2.consecutive_positive_eps_years} consecutive positive yrs</span>
                    )}
                    {rule2.eps_cagr != null && (
                      <span className={`font-mono font-medium ${rule2.eps_cagr > 0 ? 'text-gain' : 'text-loss'}`}>
                        CAGR: {rule2.eps_cagr >= 0 ? '+' : ''}{fmtPct(rule2.eps_cagr)}
                        <MetricTooltip text={`Compound Annual Growth Rate of EPS = (EPS_latest / EPS_oldest)^(1 / ${rule2.years_of_data - 1} years) − 1. Smooths out year-to-year noise to show the true growth trajectory over the available history.`} />
                      </span>
                    )}
                  </div>
                </div>
                <Sparkline
                  data={rule2.eps_history.map(e => ({ value: e.value, name: yr(e.period) }))}
                  color={trendDir(rule2.eps_history) === 'up' ? '#22c55e' : trendDir(rule2.eps_history) === 'down' ? '#ef4444' : '#64748b'}
                  height={48}
                />
              </div>

              {/* Revenue sparkline */}
              <div className="space-y-0.5">
                <div className="flex items-center justify-between">
                  <span className="text-xs text-[var(--muted-foreground)] flex items-center gap-0">
                    Revenue
                    <MetricTooltip text="Total top-line sales. Growing revenue over time supports EPS growth and indicates a business expanding its reach. Source: EDGAR annual income statements." />
                  </span>
                  {rule2.revenue_cagr != null && (
                    <span className={`text-xs font-mono font-medium ${rule2.revenue_cagr > 0 ? 'text-gain' : 'text-loss'}`}>
                      CAGR: {rule2.revenue_cagr >= 0 ? '+' : ''}{fmtPct(rule2.revenue_cagr)}
                      <MetricTooltip text={`Same CAGR formula applied to revenue: (Revenue_latest / Revenue_oldest)^(1 / ${rule2.years_of_data - 1} years) − 1. A company growing revenue at > 5–10% annually is expanding its economic footprint.`} />
                    </span>
                  )}
                </div>
                <Sparkline
                  data={rule2.revenue_history.map(e => ({ value: e.value / 1e9, name: yr(e.period) }))}
                  color={trendDir(rule2.revenue_history) === 'up' ? '#22c55e' : trendDir(rule2.revenue_history) === 'down' ? '#ef4444' : '#64748b'}
                  height={48}
                />
              </div>

              {/* AI Durability Analysis */}
              <div className="pt-1 border-t border-[var(--border)]">
                <div className="flex items-center justify-between mb-2">
                  <span className="text-xs font-medium text-[var(--muted-foreground)] flex items-center gap-1">
                    <Sparkles className="w-3 h-3 text-[var(--accent)]" />
                    AI Durability Analysis
                    <MetricTooltip text="On-demand AI analysis assessing: (1) Will this product/service exist in 30 years? (2) Is the business model understandable and predictable? (3) What are the key long-term durability risks? Uses a reasoning model with access to the company's sector, industry, and financial history. Not auto-triggered — click to run." />
                  </span>
                  {aiAnalysis.isStreaming ? (
                    <button
                      onClick={aiAnalysis.stop}
                      className="flex items-center gap-1 text-xs px-2.5 py-1 rounded bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
                    >
                      <Square className="w-3 h-3" /> Stop
                    </button>
                  ) : (
                    <button
                      onClick={aiAnalysis.trigger}
                      disabled={!ticker}
                      className="flex items-center gap-1 text-xs px-2.5 py-1 rounded bg-[var(--accent)]/10 text-[var(--accent)] hover:bg-[var(--accent)]/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <Sparkles className="w-3 h-3" />
                      {aiAnalysis.content ? 'Re-analyze' : 'Analyze'}
                    </button>
                  )}
                </div>

                {aiAnalysis.error && (
                  <p className="text-xs text-loss mt-1">{aiAnalysis.error}</p>
                )}

                {(aiAnalysis.content || aiAnalysis.isStreaming) && (
                  <div className="text-xs prose-sm">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        h1: ({ children }) => <h4 className="text-sm font-bold mt-3 mb-1 text-[var(--foreground)]">{children}</h4>,
                        h2: ({ children }) => <h5 className="text-xs font-semibold mt-2 mb-0.5 text-[var(--foreground)]">{children}</h5>,
                        h3: ({ children }) => <h5 className="text-xs font-semibold mt-2 mb-0.5 text-[var(--foreground)]">{children}</h5>,
                        p: ({ children }) => <p className="mb-1.5 text-[var(--foreground)] leading-relaxed">{children}</p>,
                        strong: ({ children }) => <strong className="font-semibold text-[var(--foreground)]">{children}</strong>,
                        ul: ({ children }) => <ul className="list-disc pl-4 mb-1.5 space-y-0.5 text-[var(--foreground)]">{children}</ul>,
                        li: ({ children }) => <li className="text-[var(--foreground)]">{children}</li>,
                      }}
                    >
                      {aiAnalysis.content}
                    </ReactMarkdown>
                    {aiAnalysis.isStreaming && (
                      <span className="inline-block w-1.5 h-3 bg-[var(--accent)] animate-pulse rounded-sm ml-0.5" />
                    )}
                  </div>
                )}
              </div>
            </div>

            {/* ── Rule 3: Stable & Understandable ──────────────────────── */}
            <div className="space-y-2">
              <RuleHeader
                number={3}
                title="Stable & Understandable"
                status={rule3.years_of_data < 3 ? 'na' : rule3Overall(rule3.bv_history, rule3.de_history, rule3.eps_history, rule3.roe_history)}
              />

              {rule3.years_of_data < 3 && (
                <p className="text-xs text-[var(--muted-foreground)]">
                  {rule3.years_of_data} year(s) of EDGAR data available — need 3+ for trend analysis.
                </p>
              )}

              {/* 2-column grid of sparklines */}
              <div className="grid grid-cols-2 gap-x-4 gap-y-3">

                {/* BV/Share */}
                <div className="space-y-0.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-[var(--muted-foreground)] flex items-center gap-0">
                      BV / Share
                      <MetricTooltip text="Book Value per Share = Shareholders' Equity ÷ Shares Outstanding. What each share would be worth if the company were liquidated today. Buffett's Rule 3 wants BV/share growing steadily each year — it's the foundation of the Rule 4 intrinsic value formula. Source: EDGAR annual balance sheets." />
                    </span>
                    <TrendCell series={rule3.bv_history} goodDir="up" formatVal={v => `$${v.toFixed(0)}`} />
                  </div>
                  <Sparkline
                    data={rule3.bv_history}
                    color={trendDir(rule3.bv_history) === 'up' ? '#22c55e' : '#64748b'}
                    height={40}
                  />
                </div>

                {/* D/E History */}
                <div className="space-y-0.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-[var(--muted-foreground)] flex items-center gap-0">
                      D/E Ratio
                      <MetricTooltip text="Debt-to-Equity computed for each year from EDGAR balance sheets: Long-Term Debt ÷ Shareholders' Equity (ratio form). A declining or stable trend signals improving financial health over time. Note: this is the raw ratio (e.g. 0.42x), not the yfinance % form." />
                    </span>
                    <TrendCell series={rule3.de_history} goodDir="down" formatVal={v => `${v.toFixed(2)}x`} />
                  </div>
                  <Sparkline
                    data={rule3.de_history}
                    color={trendDir(rule3.de_history) === 'down' || trendDir(rule3.de_history) === 'flat' ? '#22c55e' : '#ef4444'}
                    height={40}
                  />
                </div>

                {/* EPS History */}
                <div className="space-y-0.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-[var(--muted-foreground)] flex items-center gap-0">
                      EPS Trend
                      <MetricTooltip text="Earnings Per Share over time from EDGAR annual income statements. Consistently growing EPS indicates a business with durable earnings power. Erratic or declining EPS suggests unpredictability. Source: eps_diluted field from EDGAR." />
                    </span>
                    <TrendCell series={rule3.eps_history} goodDir="up" formatVal={v => `$${v.toFixed(2)}`} />
                  </div>
                  <Sparkline
                    data={rule3.eps_history}
                    color={trendDir(rule3.eps_history) === 'up' ? '#22c55e' : '#64748b'}
                    height={40}
                  />
                </div>

                {/* ROE History */}
                <div className="space-y-0.5">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] text-[var(--muted-foreground)] flex items-center gap-0">
                      ROE Trend
                      <MetricTooltip text="Return on Equity for each year: Net Income ÷ Shareholders' Equity (decimal). Consistent ROE above 15% year after year is a hallmark of a durable moat — the company repeatedly earns high returns on the equity entrusted to it. Source: EDGAR income + balance sheet statements." />
                    </span>
                    <TrendCell series={rule3.roe_history} goodDir="either" formatVal={v => `${(v * 100).toFixed(0)}%`} />
                  </div>
                  <Sparkline
                    data={rule3.roe_history}
                    color={trendDir(rule3.roe_history) !== 'down' ? '#22c55e' : '#64748b'}
                    height={40}
                  />
                </div>
              </div>
            </div>

            {/* ── Rule 4: Intrinsic Value ───────────────────────────────── */}
            <Rule4Section rule4={rule4} />

            {/* ── Option B: AI Valuation (only shown when Rule 4 is inapplicable) ── */}
            {rule4.inapplicable && (
              <div className="space-y-2 pt-1 border-t border-[var(--border)]">
                <div className="flex items-center justify-between">
                  <span className="text-xs font-medium text-[var(--muted-foreground)] flex items-center gap-1">
                    <Sparkles className="w-3 h-3 text-[var(--accent)]" />
                    AI Valuation Analysis
                    <MetricTooltip text="Because the Book Value DCF is inapplicable for this company, an AI reasoning model produces an alternative valuation. It classifies the company (mature/growth/pre-profitable), selects an appropriate methodology, injects analyst consensus, recent news, and SEC filing excerpts (10-K + 10-Q), and reasons through bear/base/bull scenarios or an investment thesis with capital runway analysis. SEC filings are indexed automatically on first run." />
                  </span>
                  {valuationAI.isStreaming ? (
                    <button
                      onClick={valuationAI.stop}
                      className="flex items-center gap-1 text-xs px-2.5 py-1 rounded bg-red-500/10 text-red-400 hover:bg-red-500/20 transition-colors"
                    >
                      <Square className="w-3 h-3" /> Stop
                    </button>
                  ) : (
                    <button
                      onClick={valuationAI.trigger}
                      disabled={!ticker}
                      className="flex items-center gap-1 text-xs px-2.5 py-1 rounded bg-[var(--accent)]/10 text-[var(--accent)] hover:bg-[var(--accent)]/20 transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                      <Sparkles className="w-3 h-3" />
                      {valuationAI.content ? 'Re-analyze' : 'Get AI Valuation'}
                    </button>
                  )}
                </div>

                {/* Status message — shown during indexing phase and data-gather phase */}
                {valuationAI.statusMessage && (
                  <div className="flex items-center gap-2 text-xs text-[var(--muted-foreground)] py-1 px-2 rounded bg-[var(--muted)]/40">
                    <Loader2 className="w-3 h-3 animate-spin shrink-0" />
                    <span>{valuationAI.statusMessage}</span>
                  </div>
                )}

                {valuationAI.error && (
                  <p className="text-xs text-loss">{valuationAI.error}</p>
                )}

                {(valuationAI.content || (valuationAI.isStreaming && !valuationAI.statusMessage)) && (
                  <div className="text-xs prose-sm">
                    <ReactMarkdown
                      remarkPlugins={[remarkGfm]}
                      components={{
                        h1: ({ children }) => <h4 className="text-sm font-bold mt-3 mb-1 text-[var(--foreground)]">{children}</h4>,
                        h2: ({ children }) => <h5 className="text-xs font-semibold mt-2 mb-0.5 text-[var(--foreground)]">{children}</h5>,
                        h3: ({ children }) => <h5 className="text-xs font-semibold mt-2 mb-0.5 text-[var(--foreground)]">{children}</h5>,
                        p: ({ children }) => <p className="mb-1.5 text-[var(--foreground)] leading-relaxed">{children}</p>,
                        strong: ({ children }) => <strong className="font-semibold text-[var(--foreground)]">{children}</strong>,
                        ul: ({ children }) => <ul className="list-disc pl-4 mb-1.5 space-y-0.5 text-[var(--foreground)]">{children}</ul>,
                        li: ({ children }) => <li className="text-[var(--foreground)]">{children}</li>,
                      }}
                    >
                      {valuationAI.content}
                    </ReactMarkdown>
                    {valuationAI.isStreaming && (
                      <span className="inline-block w-1.5 h-3 bg-[var(--accent)] animate-pulse rounded-sm ml-0.5" />
                    )}
                  </div>
                )}
              </div>
            )}

          </div>
        ) : null}
      </div>

      {/* Resize handle */}
      <div
        className="flex items-center justify-center h-4 -mx-4 -mb-4 mt-auto cursor-row-resize rounded-b-lg hover:bg-[var(--accent)]/10 transition-colors select-none shrink-0"
        onMouseDown={onResizeMouseDown ?? handleResizeMouseDown}
        title="Drag to resize"
      >
        <GripHorizontal className="w-5 h-5 text-[var(--border)]" />
      </div>
    </div>
  )
}