import { useState } from 'react'
import { api } from '@/lib/api'

interface ScenarioModelerProps {
  ticker: string
}

interface ScenarioForm {
  name: string
  revenue_growth_rate: string
  terminal_margin: string
  discount_rate: string
  annual_dilution: string
  probability: string
}

const DEFAULT_SCENARIOS: ScenarioForm[] = [
  { name: 'Bull', revenue_growth_rate: '30', terminal_margin: '20', discount_rate: '12', annual_dilution: '3', probability: '25' },
  { name: 'Base', revenue_growth_rate: '15', terminal_margin: '12', discount_rate: '15', annual_dilution: '5', probability: '50' },
  { name: 'Bear', revenue_growth_rate: '5', terminal_margin: '5', discount_rate: '20', annual_dilution: '10', probability: '25' },
]

export function ScenarioModeler({ ticker }: ScenarioModelerProps) {
  const [scenarios, setScenarios] = useState<ScenarioForm[]>(DEFAULT_SCENARIOS)
  const [result, setResult] = useState<ScenarioResult | null>(null)
  const [loading, setLoading] = useState(false)

  const updateScenario = (index: number, field: keyof ScenarioForm, value: string) => {
    const updated = [...scenarios]
    updated[index] = { ...updated[index], [field]: value }
    setScenarios(updated)
  }

  const handleRun = async () => {
    setLoading(true)
    try {
      const data = await api.runScenario(ticker, {
        scenarios: scenarios.map((s) => ({
          name: s.name,
          revenue_growth_rate: parseFloat(s.revenue_growth_rate) / 100,
          terminal_margin: parseFloat(s.terminal_margin) / 100,
          discount_rate: parseFloat(s.discount_rate) / 100,
          annual_dilution: parseFloat(s.annual_dilution) / 100,
          probability: parseFloat(s.probability) / 100,
        })),
      })
      setResult(data)
    } catch (err) {
      console.error('Scenario analysis failed:', err)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="card space-y-4">
      <h3 className="font-semibold text-lg">Scenario Modeler</h3>

      {/* Scenario inputs */}
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-[var(--border)]">
              <th className="text-left py-2 px-2 font-medium text-[var(--muted-foreground)]">Scenario</th>
              <th className="text-right py-2 px-2 font-medium text-[var(--muted-foreground)]">Rev Growth %</th>
              <th className="text-right py-2 px-2 font-medium text-[var(--muted-foreground)]">Terminal Margin %</th>
              <th className="text-right py-2 px-2 font-medium text-[var(--muted-foreground)]">Discount Rate %</th>
              <th className="text-right py-2 px-2 font-medium text-[var(--muted-foreground)]">Dilution/yr %</th>
              <th className="text-right py-2 px-2 font-medium text-[var(--muted-foreground)]">Probability %</th>
            </tr>
          </thead>
          <tbody>
            {scenarios.map((s, i) => (
              <tr key={i} className="border-b border-[var(--border)] last:border-0">
                <td className="py-1.5 px-2 font-medium">{s.name}</td>
                <td className="py-1.5 px-2"><input type="number" value={s.revenue_growth_rate} onChange={(e) => updateScenario(i, 'revenue_growth_rate', e.target.value)} className="input w-20 text-right text-sm py-1" /></td>
                <td className="py-1.5 px-2"><input type="number" value={s.terminal_margin} onChange={(e) => updateScenario(i, 'terminal_margin', e.target.value)} className="input w-20 text-right text-sm py-1" /></td>
                <td className="py-1.5 px-2"><input type="number" value={s.discount_rate} onChange={(e) => updateScenario(i, 'discount_rate', e.target.value)} className="input w-20 text-right text-sm py-1" /></td>
                <td className="py-1.5 px-2"><input type="number" value={s.annual_dilution} onChange={(e) => updateScenario(i, 'annual_dilution', e.target.value)} className="input w-20 text-right text-sm py-1" /></td>
                <td className="py-1.5 px-2"><input type="number" value={s.probability} onChange={(e) => updateScenario(i, 'probability', e.target.value)} className="input w-20 text-right text-sm py-1" /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <button onClick={handleRun} className="btn-primary text-sm" disabled={loading}>
        {loading ? 'Running...' : 'Run Analysis'}
      </button>

      {/* Results */}
      {result && (
        <div className="mt-4 space-y-3">
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {result.scenarios.map((s) => (
              <div key={s.name} className="p-3 rounded-lg bg-[var(--muted)]">
                <div className="text-xs text-[var(--muted-foreground)]">{s.name} Case</div>
                <div className="text-lg font-semibold font-mono">${s.implied_value.toFixed(2)}</div>
                <div className="text-xs text-[var(--muted-foreground)]">{(s.probability * 100).toFixed(0)}% probability</div>
              </div>
            ))}
            <div className="p-3 rounded-lg bg-[var(--accent)]/10 border border-[var(--accent)]/30">
              <div className="text-xs text-[var(--muted-foreground)]">Weighted Value</div>
              <div className="text-lg font-bold font-mono text-[var(--accent)]">${result.probability_weighted_value.toFixed(2)}</div>
              {result.upside_downside != null && (
                <div className={`text-xs font-semibold ${result.upside_downside > 0 ? 'text-gain' : 'text-loss'}`}>
                  {result.upside_downside > 0 ? '+' : ''}{result.upside_downside.toFixed(1)}% vs current
                </div>
              )}
            </div>
          </div>
          {result.current_price && (
            <div className="text-sm text-[var(--muted-foreground)]">
              Current price: ${result.current_price.toFixed(2)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
