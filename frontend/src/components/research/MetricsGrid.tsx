interface MetricCardProps {
  label: string
  value: string
  status?: 'positive' | 'negative' | 'neutral'
  sublabel?: string
}

function MetricCard({ label, value, status = 'neutral', sublabel }: MetricCardProps) {
  const colorClass = status === 'positive' ? 'metric-positive'
    : status === 'negative' ? 'metric-negative'
    : 'metric-neutral'

  return (
    <div className="p-3 rounded-lg bg-[var(--muted)]">
      <div className="text-xs text-[var(--muted-foreground)] mb-1">{label}</div>
      <div className={`text-lg font-semibold font-mono ${colorClass}`}>{value}</div>
      {sublabel && <div className="text-xs text-[var(--muted-foreground)] mt-0.5">{sublabel}</div>}
    </div>
  )
}

interface MetricsGridProps {
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  metrics: Record<string, any>
}

function fmt(val: unknown, suffix = ''): string {
  if (val == null) return 'N/A'
  if (typeof val === 'number') {
    if (Math.abs(val) >= 1e12) return `$${(val / 1e12).toFixed(2)}T`
    if (Math.abs(val) >= 1e9) return `$${(val / 1e9).toFixed(2)}B`
    if (Math.abs(val) >= 1e6) return `$${(val / 1e6).toFixed(1)}M`
    return `${val.toFixed(2)}${suffix}`
  }
  return String(val)
}

function pct(val: unknown): string {
  if (val == null) return 'N/A'
  if (typeof val === 'number') return `${(val * 100).toFixed(1)}%`
  return String(val)
}

export function MetricsGrid({ metrics }: MetricsGridProps) {
  const m = metrics as Record<string, number | null | undefined>

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-3">
      <MetricCard label="P/E Ratio" value={fmt(m.pe_ratio)} status={m.pe_ratio != null && m.pe_ratio > 0 && m.pe_ratio <= 15 ? 'positive' : m.pe_ratio != null && m.pe_ratio > 25 ? 'negative' : 'neutral'} />
      <MetricCard label="Forward P/E" value={fmt(m.forward_pe)} />
      <MetricCard label="P/B Ratio" value={fmt(m.pb_ratio)} status={m.pb_ratio != null && m.pb_ratio <= 1.5 ? 'positive' : m.pb_ratio != null && m.pb_ratio > 5 ? 'negative' : 'neutral'} />
      <MetricCard label="P/S Ratio" value={fmt(m.ps_ratio)} />
      <MetricCard label="EPS" value={fmt(m.eps, '')} status={m.eps != null && m.eps > 0 ? 'positive' : m.eps != null && m.eps < 0 ? 'negative' : 'neutral'} />
      <MetricCard label="Debt/Equity" value={fmt(m.debt_to_equity != null ? m.debt_to_equity / 100 : null)} status={m.debt_to_equity != null && m.debt_to_equity < 50 ? 'positive' : m.debt_to_equity != null && m.debt_to_equity > 200 ? 'negative' : 'neutral'} />
      <MetricCard label="Current Ratio" value={fmt(m.current_ratio)} status={m.current_ratio != null && m.current_ratio >= 2 ? 'positive' : m.current_ratio != null && m.current_ratio < 1 ? 'negative' : 'neutral'} />
      <MetricCard label="ROE" value={pct(m.roe)} status={m.roe != null && m.roe > 0.15 ? 'positive' : m.roe != null && m.roe < 0 ? 'negative' : 'neutral'} />
      <MetricCard label="Net Margin" value={pct(m.net_margin)} status={m.net_margin != null && m.net_margin > 0.1 ? 'positive' : m.net_margin != null && m.net_margin < 0 ? 'negative' : 'neutral'} />
      <MetricCard label="Revenue Growth" value={pct(m.revenue_growth)} status={m.revenue_growth != null && m.revenue_growth > 0 ? 'positive' : 'negative'} />
      <MetricCard label="Free Cash Flow" value={fmt(m.free_cash_flow)} status={m.free_cash_flow != null && m.free_cash_flow > 0 ? 'positive' : 'negative'} />
      <MetricCard label="Dividend Yield" value={pct(m.dividend_yield)} />
      <MetricCard label="Beta" value={fmt(m.beta)} />
      <MetricCard label="52W High" value={fmt(m.fifty_two_week_high, '')} sublabel={m.price != null && m.fifty_two_week_high != null ? `${((1 - m.price / m.fifty_two_week_high) * 100).toFixed(1)}% below` : undefined} />
      <MetricCard label="52W Low" value={fmt(m.fifty_two_week_low, '')} sublabel={m.price != null && m.fifty_two_week_low != null ? `${((m.price / m.fifty_two_week_low - 1) * 100).toFixed(1)}% above` : undefined} />
    </div>
  )
}
