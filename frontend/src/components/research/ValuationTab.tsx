import { useState } from 'react'
import { api } from '@/lib/api'
import { ScenarioModeler } from './ScenarioModeler'
import type { DCFResult } from '@/lib/types'

interface ValuationTabProps {
  ticker: string
}

export function ValuationTab({ ticker }: ValuationTabProps) {
  const [growthRate, setGrowthRate] = useState('10')
  const [discountRate, setDiscountRate] = useState('10')
  const [terminalGrowth, setTerminalGrowth] = useState('3')
  const [years, setYears] = useState('10')
  const [dcfResult, setDcfResult] = useState<DCFResult | null>(null)
  const [loading, setLoading] = useState(false)

  const handleRunDCF = async () => {
    setLoading(true)
    try {
      const result = await api.runDCF(ticker, {
        growth_rate: parseFloat(growthRate) / 100,
        discount_rate: parseFloat(discountRate) / 100,
        terminal_growth_rate: parseFloat(terminalGrowth) / 100,
        projection_years: parseInt(years),
      })
      setDcfResult(result)
    } catch (err) {
      console.error('DCF calculation failed:', err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="space-y-6">
      {/* DCF Calculator */}
      <div className="card space-y-4">
        <h3 className="font-semibold text-lg">DCF Valuation</h3>

        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          <div>
            <label className="text-xs text-[var(--muted-foreground)] block mb-1">Growth Rate (%)</label>
            <input type="number" value={growthRate} onChange={(e) => setGrowthRate(e.target.value)} className="input w-full text-sm" />
          </div>
          <div>
            <label className="text-xs text-[var(--muted-foreground)] block mb-1">Discount Rate (%)</label>
            <input type="number" value={discountRate} onChange={(e) => setDiscountRate(e.target.value)} className="input w-full text-sm" />
          </div>
          <div>
            <label className="text-xs text-[var(--muted-foreground)] block mb-1">Terminal Growth (%)</label>
            <input type="number" value={terminalGrowth} onChange={(e) => setTerminalGrowth(e.target.value)} className="input w-full text-sm" />
          </div>
          <div>
            <label className="text-xs text-[var(--muted-foreground)] block mb-1">Projection Years</label>
            <input type="number" value={years} onChange={(e) => setYears(e.target.value)} className="input w-full text-sm" />
          </div>
        </div>

        <button onClick={handleRunDCF} className="btn-primary text-sm" disabled={loading}>
          {loading ? 'Calculating...' : 'Calculate DCF'}
        </button>

        {dcfResult && (
          <div className="mt-4 space-y-3">
            <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
              <div className="p-3 rounded-lg bg-[var(--muted)]">
                <div className="text-xs text-[var(--muted-foreground)]">Intrinsic Value / Share</div>
                <div className="text-xl font-bold font-mono text-[var(--accent)]">
                  ${dcfResult.intrinsic_value_per_share.toFixed(2)}
                </div>
              </div>
              {dcfResult.current_price && (
                <div className="p-3 rounded-lg bg-[var(--muted)]">
                  <div className="text-xs text-[var(--muted-foreground)]">Current Price</div>
                  <div className="text-xl font-bold font-mono">
                    ${dcfResult.current_price.toFixed(2)}
                  </div>
                </div>
              )}
              {dcfResult.margin_of_safety != null && (
                <div className="p-3 rounded-lg bg-[var(--muted)]">
                  <div className="text-xs text-[var(--muted-foreground)]">Margin of Safety</div>
                  <div className={`text-xl font-bold font-mono ${dcfResult.margin_of_safety > 0 ? 'text-gain' : 'text-loss'}`}>
                    {dcfResult.margin_of_safety > 0 ? '+' : ''}{dcfResult.margin_of_safety.toFixed(1)}%
                  </div>
                </div>
              )}
            </div>

            {/* FCF projections table */}
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-[var(--border)]">
                    <th className="text-left py-2 px-2 font-medium text-[var(--muted-foreground)]">Year</th>
                    <th className="text-right py-2 px-2 font-medium text-[var(--muted-foreground)]">Projected FCF</th>
                    <th className="text-right py-2 px-2 font-medium text-[var(--muted-foreground)]">Present Value</th>
                  </tr>
                </thead>
                <tbody>
                  {dcfResult.projected_fcf.map((row: { year: number; fcf: number; present_value: number }) => (
                    <tr key={row.year} className="border-b border-[var(--border)] last:border-0">
                      <td className="py-1.5 px-2">Year {row.year}</td>
                      <td className="py-1.5 px-2 text-right font-mono">${(row.fcf / 1e9).toFixed(2)}B</td>
                      <td className="py-1.5 px-2 text-right font-mono">${(row.present_value / 1e9).toFixed(2)}B</td>
                    </tr>
                  ))}
                  <tr className="font-semibold">
                    <td className="py-1.5 px-2">Terminal Value</td>
                    <td className="py-1.5 px-2 text-right font-mono" colSpan={2}>
                      ${(dcfResult.terminal_value / 1e9).toFixed(2)}B
                    </td>
                  </tr>
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>

      {/* Scenario Modeler */}
      <ScenarioModeler ticker={ticker} />
    </div>
  )
}
