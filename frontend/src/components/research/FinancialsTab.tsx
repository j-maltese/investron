import { useState } from 'react'
import { useStatements } from '@/hooks/useCompany'
import { LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer } from 'recharts'
import type { FinancialStatement } from '@/lib/types'

interface FinancialsTabProps {
  ticker: string
}

type StatementType = 'income_statement' | 'balance_sheet' | 'cash_flow'
type PeriodType = 'annual' | 'quarterly'

const STATEMENT_LABELS: Record<StatementType, string> = {
  income_statement: 'Income Statement',
  balance_sheet: 'Balance Sheet',
  cash_flow: 'Cash Flow',
}

// Display names for raw field keys
const FIELD_LABELS: Record<string, string> = {
  revenue: 'Revenue',
  cost_of_revenue: 'Cost of Revenue',
  gross_profit: 'Gross Profit',
  rd_expense: 'R&D Expense',
  sga_expense: 'SG&A Expense',
  operating_income: 'Operating Income',
  operating_expenses: 'Operating Expenses',
  interest_expense: 'Interest Expense',
  income_tax: 'Income Tax',
  net_income: 'Net Income',
  eps_basic: 'EPS (Basic)',
  eps_diluted: 'EPS (Diluted)',
  shares_outstanding: 'Shares Outstanding',
  shares_diluted: 'Diluted Shares',
  cash_and_equivalents: 'Cash & Equivalents',
  short_term_investments: 'Short-term Investments',
  accounts_receivable: 'Accounts Receivable',
  inventory: 'Inventory',
  current_assets: 'Current Assets',
  ppe_net: 'PP&E (Net)',
  goodwill: 'Goodwill',
  total_assets: 'Total Assets',
  accounts_payable: 'Accounts Payable',
  long_term_debt: 'Long-term Debt',
  current_liabilities: 'Current Liabilities',
  total_liabilities: 'Total Liabilities',
  stockholders_equity: "Stockholders' Equity",
  retained_earnings: 'Retained Earnings',
  total_liabilities_and_equity: 'Total Liabilities & Equity',
  operating_cash_flow: 'Operating Cash Flow',
  investing_cash_flow: 'Investing Cash Flow',
  financing_cash_flow: 'Financing Cash Flow',
  capex: 'Capital Expenditures',
  depreciation_amortization: 'Depreciation & Amortization',
  dividends_paid: 'Dividends Paid',
  share_repurchases: 'Share Repurchases',
}

function formatValue(val: unknown): string {
  if (val == null) return '-'
  const num = Number(val)
  if (isNaN(num)) return String(val)
  if (Math.abs(num) >= 1e9) return `${(num / 1e9).toFixed(2)}B`
  if (Math.abs(num) >= 1e6) return `${(num / 1e6).toFixed(1)}M`
  if (Math.abs(num) >= 1e3) return `${(num / 1e3).toFixed(1)}K`
  return num.toFixed(2)
}

export function FinancialsTab({ ticker }: FinancialsTabProps) {
  const [statementType, setStatementType] = useState<StatementType>('income_statement')
  const [periodType, setPeriodType] = useState<PeriodType>('annual')
  const { data, isLoading } = useStatements(ticker, statementType, periodType)

  if (isLoading) {
    return <div className="text-[var(--muted-foreground)] py-8 text-center">Loading financial data...</div>
  }

  const statements = data?.statements || []

  // Get all fields (excluding 'period')
  const allFields = new Set<string>()
  statements.forEach((s: FinancialStatement) => {
    Object.keys(s).forEach((k) => { if (k !== 'period') allFields.add(k) })
  })
  const fields = Array.from(allFields)

  // Prepare chart data for key metrics
  const chartField = statementType === 'income_statement' ? 'revenue'
    : statementType === 'balance_sheet' ? 'total_assets'
    : 'operating_cash_flow'
  const chartField2 = statementType === 'income_statement' ? 'net_income'
    : statementType === 'balance_sheet' ? 'stockholders_equity'
    : 'capex'

  const chartData = statements.map((s: FinancialStatement) => ({
    period: String(s.period).slice(0, 4),
    [chartField]: Number(s[chartField]) / 1e9 || 0,
    [chartField2]: Number(s[chartField2]) / 1e9 || 0,
  }))

  return (
    <div className="space-y-4">
      {/* Controls */}
      <div className="flex gap-2 flex-wrap">
        {(Object.keys(STATEMENT_LABELS) as StatementType[]).map((type) => (
          <button
            key={type}
            onClick={() => setStatementType(type)}
            className={statementType === type ? 'btn-primary text-sm' : 'btn-secondary text-sm'}
          >
            {STATEMENT_LABELS[type]}
          </button>
        ))}
        <div className="w-px bg-[var(--border)] mx-1" />
        <button
          onClick={() => setPeriodType('annual')}
          className={periodType === 'annual' ? 'btn-primary text-sm' : 'btn-secondary text-sm'}
        >
          Annual
        </button>
        <button
          onClick={() => setPeriodType('quarterly')}
          className={periodType === 'quarterly' ? 'btn-primary text-sm' : 'btn-secondary text-sm'}
        >
          Quarterly
        </button>
      </div>

      {/* Trend Chart */}
      {chartData.length > 1 && (
        <div className="card">
          <h4 className="text-sm font-medium mb-2">
            {FIELD_LABELS[chartField] || chartField} vs {FIELD_LABELS[chartField2] || chartField2} ($B)
          </h4>
          <div className="h-52">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData}>
                <XAxis dataKey="period" tick={{ fontSize: 12 }} />
                <YAxis tick={{ fontSize: 12 }} />
                <Tooltip formatter={(v: number | undefined) => v != null ? `$${v.toFixed(2)}B` : '-'} />
                <Line type="monotone" dataKey={chartField} stroke="#3b82f6" strokeWidth={2} dot={{ r: 3 }} />
                <Line type="monotone" dataKey={chartField2} stroke="#22c55e" strokeWidth={2} dot={{ r: 3 }} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>
      )}

      {/* Data Table */}
      {statements.length === 0 ? (
        <div className="text-[var(--muted-foreground)] py-8 text-center">No data available</div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-[var(--border)]">
                <th className="text-left py-2 px-2 font-medium text-[var(--muted-foreground)] sticky left-0 bg-[var(--card)]">
                  Item
                </th>
                {statements.map((s: FinancialStatement) => (
                  <th key={String(s.period)} className="text-right py-2 px-3 font-medium text-[var(--muted-foreground)] whitespace-nowrap">
                    {String(s.period).slice(0, 10)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {fields.map((field) => (
                <tr key={field} className="border-b border-[var(--border)] last:border-0 hover:bg-[var(--muted)] transition-colors">
                  <td className="py-1.5 px-2 font-medium sticky left-0 bg-[var(--card)]">
                    {FIELD_LABELS[field] || field}
                  </td>
                  {statements.map((s: FinancialStatement) => (
                    <td key={String(s.period)} className="py-1.5 px-3 text-right font-mono whitespace-nowrap">
                      {formatValue(s[field])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
