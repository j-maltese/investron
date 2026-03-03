import type { TradingPortfolio } from '@/lib/types'

function formatMoney(value: number): string {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value)
}

function formatPct(value: number): string {
  const sign = value >= 0 ? '+' : ''
  return `${sign}${value.toFixed(2)}%`
}

interface PortfolioSummaryProps {
  portfolio: TradingPortfolio
}

export function PortfolioSummary({ portfolio }: PortfolioSummaryProps) {
  const pnlPositive = portfolio.total_pnl >= 0

  return (
    <div className="card">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-semibold text-lg">Paper Trading Portfolio</h2>
        <span className="text-xs text-[var(--muted-foreground)] bg-amber-500/15 text-amber-400 px-2 py-0.5 rounded-full">
          Paper
        </span>
      </div>

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-4">
        <div>
          <div className="text-xs text-[var(--muted-foreground)]">Total Value</div>
          <div className="text-xl font-mono font-bold">{formatMoney(portfolio.total_value)}</div>
        </div>
        <div>
          <div className="text-xs text-[var(--muted-foreground)]">Cash</div>
          <div className="font-mono">{formatMoney(portfolio.total_cash)}</div>
        </div>
        <div>
          <div className="text-xs text-[var(--muted-foreground)]">Invested</div>
          <div className="font-mono">{formatMoney(portfolio.total_portfolio_value)}</div>
        </div>
        <div>
          <div className="text-xs text-[var(--muted-foreground)]">P&L</div>
          <div className={`font-mono font-semibold ${pnlPositive ? 'text-gain' : 'text-loss'}`}>
            {formatMoney(portfolio.total_pnl)}
          </div>
        </div>
        <div>
          <div className="text-xs text-[var(--muted-foreground)]">Return</div>
          <div className={`font-mono font-semibold ${pnlPositive ? 'text-gain' : 'text-loss'}`}>
            {formatPct(portfolio.total_pnl_pct)}
          </div>
        </div>
      </div>
    </div>
  )
}
