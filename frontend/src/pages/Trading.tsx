import { useState, useMemo } from 'react'
import { PageLayout } from '@/components/layout/PageLayout'
import { StrategyCard } from '@/components/trading/StrategyCard'
import { PortfolioSummary } from '@/components/trading/PortfolioSummary'
import { PositionsTable } from '@/components/trading/PositionsTable'
import { OrdersTable } from '@/components/trading/OrdersTable'
import { ActivityFeed } from '@/components/trading/ActivityFeed'
import { StrategyFilterPills } from '@/components/trading/StrategyFilterPills'
import { useStrategies, usePortfolio, usePositions, useOrders, useActivityLog } from '@/hooks/useTrading'

type Tab = 'overview' | 'positions' | 'orders' | 'activity'

const TABS: { key: Tab; label: string }[] = [
  { key: 'overview', label: 'Overview' },
  { key: 'positions', label: 'Positions' },
  { key: 'orders', label: 'Order History' },
  { key: 'activity', label: 'Activity Log' },
]

export function Trading() {
  const [activeTab, setActiveTab] = useState<Tab>('overview')
  const [strategyFilter, setStrategyFilter] = useState<string | null>(null)

  const { data: strategiesData, isLoading: strategiesLoading } = useStrategies()
  const { data: portfolio, isLoading: portfolioLoading } = usePortfolio()
  const { data: positionsData } = usePositions()
  const { data: ordersData } = useOrders()
  // Fetch a small batch of recent events for the Overview tab's "Recent Activity"
  // section. The full Activity tab manages its own data fetching internally.
  const { data: activityData } = useActivityLog({ limit: 5 })

  // Fixed display order — lookup by ID so position never changes with status
  const strategiesMap = new Map((strategiesData?.strategies || []).map(s => [s.id, s]))
  const strategies = ['simple_stock', 'wheel']
    .map(id => strategiesMap.get(id))
    .filter((s): s is NonNullable<typeof s> => s != null)
  const allPositions = positionsData?.positions || []
  const allOrders = ordersData?.orders || []
  const recentEvents = activityData?.events || []
  const recentEventsCount = activityData?.total_count || 0

  // Client-side strategy filtering for Positions and Orders tabs
  const positions = useMemo(
    () => strategyFilter ? allPositions.filter(p => p.strategy_id === strategyFilter) : allPositions,
    [allPositions, strategyFilter]
  )
  const orders = useMemo(
    () => strategyFilter ? allOrders.filter(o => o.strategy_id === strategyFilter) : allOrders,
    [allOrders, strategyFilter]
  )

  return (
    <PageLayout>
      <div className="space-y-4">
        {/* Page header */}
        <div>
          <h1 className="text-2xl font-bold">Paper Trading</h1>
          <p className="text-sm text-[var(--muted-foreground)] mt-1">
            Automated strategies using Alpaca paper trading
          </p>
        </div>

        {/* Tab navigation */}
        <div className="flex gap-1 border-b border-[var(--border)]">
          {TABS.map(({ key, label }) => (
            <button
              key={key}
              onClick={() => setActiveTab(key)}
              className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === key
                  ? 'border-[var(--accent)] text-[var(--accent)]'
                  : 'border-transparent text-[var(--muted-foreground)] hover:text-[var(--foreground)]'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div>
          {activeTab === 'overview' && (
            <div className="space-y-4">
              {/* Portfolio summary */}
              {portfolioLoading ? (
                <div className="card h-24 animate-pulse bg-[var(--muted)]" />
              ) : portfolio ? (
                <PortfolioSummary portfolio={portfolio} />
              ) : null}

              {/* Strategy cards */}
              {strategiesLoading ? (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  <div className="card h-48 animate-pulse bg-[var(--muted)]" />
                  <div className="card h-48 animate-pulse bg-[var(--muted)]" />
                </div>
              ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                  {strategies.map((strategy) => (
                    <StrategyCard key={strategy.id} strategy={strategy} />
                  ))}
                </div>
              )}

              {/* Quick view: recent activity (compact mode — no filters/expand) */}
              {recentEvents.length > 0 && (
                <div>
                  <h3 className="text-sm font-medium text-[var(--muted-foreground)] mb-2">Recent Activity</h3>
                  <ActivityFeed compact events={recentEvents} totalCount={recentEventsCount} />
                </div>
              )}
            </div>
          )}

          {activeTab === 'positions' && (
            <div className="space-y-3">
              <StrategyFilterPills
                strategies={strategies}
                selected={strategyFilter}
                onChange={setStrategyFilter}
              />
              <PositionsTable positions={positions} totalCount={positions.length} />
            </div>
          )}

          {activeTab === 'orders' && (
            <div className="space-y-3">
              <StrategyFilterPills
                strategies={strategies}
                selected={strategyFilter}
                onChange={setStrategyFilter}
              />
              <OrdersTable orders={orders} totalCount={orders.length} />
            </div>
          )}

          {activeTab === 'activity' && (
            <ActivityFeed />
          )}
        </div>
      </div>
    </PageLayout>
  )
}
