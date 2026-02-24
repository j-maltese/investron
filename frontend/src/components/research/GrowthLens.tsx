import { useGrowthMetrics } from '@/hooks/useCompany'
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from 'recharts'

interface GrowthLensProps {
  ticker: string
}

function formatLarge(val: number | null | undefined): string {
  if (val == null) return 'N/A'
  if (Math.abs(val) >= 1e9) return `$${(val / 1e9).toFixed(2)}B`
  if (Math.abs(val) >= 1e6) return `$${(val / 1e6).toFixed(1)}M`
  return `$${val.toLocaleString()}`
}

export function GrowthLens({ ticker }: GrowthLensProps) {
  const { data, isLoading } = useGrowthMetrics(ticker)

  if (isLoading) return <div className="text-[var(--muted-foreground)]">Loading growth metrics...</div>
  if (!data) return null

  const revenueGrowthData = data.revenue_growth_rates.map((r: { period: string; growth_rate: number }) => ({
    period: r.period.slice(0, 4), // Just the year
    growth: +(r.growth_rate * 100).toFixed(1),
  }))

  return (
    <div className="card space-y-6">
      <h3 className="font-semibold text-lg">Growth / Emerging Lens</h3>

      {/* Key growth metrics */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="p-3 rounded-lg bg-[var(--muted)]">
          <div className="text-xs text-[var(--muted-foreground)]">Cash on Hand</div>
          <div className="text-lg font-semibold font-mono">{formatLarge(data.cash_on_hand)}</div>
        </div>
        <div className="p-3 rounded-lg bg-[var(--muted)]">
          <div className="text-xs text-[var(--muted-foreground)]">Burn Rate (Quarterly)</div>
          <div className={`text-lg font-semibold font-mono ${data.burn_rate != null && data.burn_rate > 0 ? 'text-loss' : 'text-gain'}`}>
            {data.burn_rate != null ? formatLarge(Math.abs(data.burn_rate)) : 'N/A'}
          </div>
        </div>
        <div className="p-3 rounded-lg bg-[var(--muted)]">
          <div className="text-xs text-[var(--muted-foreground)]">Cash Runway</div>
          <div className={`text-lg font-semibold font-mono ${data.cash_runway_quarters != null && data.cash_runway_quarters < 4 ? 'text-loss' : data.cash_runway_quarters != null && data.cash_runway_quarters > 8 ? 'text-gain' : ''}`}>
            {data.cash_runway_quarters != null ? `${data.cash_runway_quarters} Q` : 'N/A'}
          </div>
        </div>
        <div className="p-3 rounded-lg bg-[var(--muted)]">
          <div className="text-xs text-[var(--muted-foreground)]">Annual Dilution</div>
          <div className={`text-lg font-semibold font-mono ${data.dilution_rate != null && data.dilution_rate > 0.05 ? 'text-loss' : ''}`}>
            {data.dilution_rate != null ? `${(data.dilution_rate * 100).toFixed(1)}%` : 'N/A'}
          </div>
        </div>
      </div>

      {/* R&D and Insiders */}
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <div className="p-3 rounded-lg bg-[var(--muted)]">
          <div className="text-xs text-[var(--muted-foreground)]">R&D Expense</div>
          <div className="text-lg font-semibold font-mono">{formatLarge(data.rd_expense)}</div>
          {data.rd_as_pct_revenue != null && (
            <div className="text-xs text-[var(--muted-foreground)]">{(data.rd_as_pct_revenue * 100).toFixed(1)}% of revenue</div>
          )}
        </div>
        <div className="p-3 rounded-lg bg-[var(--muted)]">
          <div className="text-xs text-[var(--muted-foreground)]">Insider Buys (6mo)</div>
          <div className={`text-lg font-semibold ${data.insider_buys_6m != null && data.insider_buys_6m > 0 ? 'text-gain' : ''}`}>
            {data.insider_buys_6m ?? 'N/A'}
          </div>
        </div>
        <div className="p-3 rounded-lg bg-[var(--muted)]">
          <div className="text-xs text-[var(--muted-foreground)]">Insider Sells (6mo)</div>
          <div className={`text-lg font-semibold ${data.insider_sells_6m != null && data.insider_sells_6m > 3 ? 'text-loss' : ''}`}>
            {data.insider_sells_6m ?? 'N/A'}
          </div>
        </div>
      </div>

      {/* Revenue Growth Chart */}
      {revenueGrowthData.length > 0 && (
        <div>
          <h4 className="text-sm font-medium mb-2">Revenue Growth Rate (Year over Year)</h4>
          <div className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={revenueGrowthData}>
                <XAxis dataKey="period" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} tickFormatter={(v) => `${v}%`} />
                <Tooltip formatter={(value: number | undefined) => value != null ? [`${value}%`, 'Growth'] : ['-', 'Growth']} />
                <Bar dataKey="growth" radius={[4, 4, 0, 0]}>
                  {revenueGrowthData.map((entry: { period: string; growth: number }, index: number) => (
                    <Cell key={index} fill={entry.growth >= 0 ? '#22c55e' : '#ef4444'} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}
    </div>
  )
}
