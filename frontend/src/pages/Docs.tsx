import { useState } from 'react'
import { ChevronDown, ChevronRight, Tag, Wrench, Bug } from 'lucide-react'
import { PageLayout } from '@/components/layout/PageLayout'
import { useReleaseNotes } from '@/hooks/useReleaseNotes'
import type { ReleaseNote, ReleaseNoteSection } from '@/lib/types'

type Tab = 'user' | 'developer' | 'releases'

const TABS: { key: Tab; label: string }[] = [
  { key: 'user', label: 'User Guide' },
  { key: 'developer', label: 'Developer Guide' },
  { key: 'releases', label: 'Release Notes' },
]

export function Docs() {
  const [activeTab, setActiveTab] = useState<Tab>('user')

  return (
    <PageLayout>
      <div className="space-y-4">
        <h1 className="text-2xl font-bold">Documentation</h1>

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
        <div className="max-w-4xl">
          {activeTab === 'user' && <UserGuide />}
          {activeTab === 'developer' && <DeveloperGuide />}
          {activeTab === 'releases' && <ReleaseNotesTab />}
        </div>
      </div>
    </PageLayout>
  )
}

/* ─── Section helper ─── */

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="space-y-3">
      <h2 className="text-xl font-semibold border-b border-[var(--border)] pb-2">{title}</h2>
      <div className="space-y-2 text-sm leading-relaxed text-[var(--foreground)]">{children}</div>
    </section>
  )
}

function SubSection({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <h3 className="text-base font-semibold">{title}</h3>
      <div className="space-y-1.5">{children}</div>
    </div>
  )
}

/* ─── User Guide ─── */

function UserGuide() {
  return (
    <div className="space-y-8">
      <Section title="1. Getting Started">
        <p>
          Investron is a research platform for fundamental value investors. After signing in with your Google account,
          you'll land on the <strong>Dashboard</strong> — your home base for tracking stocks you're interested in.
        </p>
        <SubSection title="Navigation">
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Dashboard</strong> — Your watchlist and price alerts</li>
            <li><strong>Search bar</strong> — Type any ticker (e.g., AAPL, NVDA) to jump to its Research page</li>
            <li><strong>Docs</strong> — This documentation page</li>
            <li><strong>Theme toggle</strong> — Switch between dark and light modes (moon/sun icon)</li>
            <li><strong>Sign out</strong> — Log out of your account (door icon)</li>
          </ul>
        </SubSection>
      </Section>

      <Section title="2. Dashboard & Watchlist">
        <p>
          The Dashboard shows your personal watchlist — a table of stocks you're tracking.
        </p>
        <SubSection title="Adding stocks">
          <p>
            Type a ticker symbol (e.g., NVDA) into the "Add ticker" field and optionally set a target price.
            Press <strong>Enter</strong> or click <strong>Add</strong>. The stock will appear in your watchlist
            with its current price fetched in real time.
          </p>
        </SubSection>
        <SubSection title="Watchlist columns">
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Ticker</strong> — The stock symbol (clickable — opens the Research page)</li>
            <li><strong>Company</strong> — Full company name</li>
            <li><strong>Price</strong> — Current market price (refreshed on page load)</li>
            <li><strong>Target</strong> — Your target price, if set</li>
            <li><strong>Notes</strong> — Personal notes for your reference</li>
            <li><strong>Actions</strong> — Research link and delete button</li>
          </ul>
        </SubSection>
        <SubSection title="Price alerts">
          <p>
            If a stock's current price comes within <strong>10%</strong> of your target price (above or below),
            an alert banner will appear at the top of the Dashboard. Alerts tell you the ticker, how far it is
            from your target, and in which direction.
          </p>
        </SubSection>
      </Section>

      <Section title="3. Company Research">
        <p>
          Search for any publicly traded US company using the search bar in the header. Type a ticker
          symbol (e.g., GOOGL) and select from the results. This opens the <strong>Research</strong> page,
          which has four tabs:
        </p>
        <SubSection title="Research page header">
          <p>
            At the top you'll see the ticker, company name, sector, industry, exchange, current stock price,
            and market capitalization.
          </p>
        </SubSection>
      </Section>

      <Section title="4. Overview Tab">
        <p>
          The Overview tab provides a snapshot of the company:
        </p>
        <ul className="list-disc pl-5 space-y-1">
          <li><strong>Key Metrics</strong> — A grid of important financial ratios and figures:
            P/E ratio, P/B ratio, market cap, dividend yield, 52-week high/low, profit margins, ROE, debt-to-equity, and more.
          </li>
          <li><strong>Graham Score</strong> — Benjamin Graham's evaluation (see section 8 below for details).</li>
          <li><strong>Growth Lens</strong> — Metrics designed for pre-profit or high-growth companies (see section 9).</li>
          <li><strong>Price chart</strong> — Historical stock price visualization.</li>
        </ul>
      </Section>

      <Section title="5. Financial Statements">
        <p>
          The <strong>Financials</strong> tab shows structured financial data sourced from SEC EDGAR's XBRL database.
        </p>
        <SubSection title="Statement types">
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Income Statement</strong> — Revenue, cost of revenue, gross profit, operating income, net income, EPS</li>
            <li><strong>Balance Sheet</strong> — Assets, liabilities, equity, cash, debt, retained earnings</li>
            <li><strong>Cash Flow</strong> — Operating, investing, and financing cash flows, CapEx, dividends</li>
          </ul>
        </SubSection>
        <SubSection title="Period toggle">
          <p>
            Switch between <strong>Annual</strong> (10-K filings) and <strong>Quarterly</strong> (10-Q filings) data.
            Annual data is best for long-term trend analysis. Quarterly data helps track recent momentum.
          </p>
        </SubSection>
        <SubSection title="Reading the data">
          <p>
            Data is presented as a time series — each column represents a fiscal period. Look for trends:
            growing revenue, expanding margins, and consistent profitability are positive signals for value investors.
          </p>
        </SubSection>
      </Section>

      <Section title="6. SEC Filings">
        <p>
          The <strong>Filings</strong> tab lists all SEC filings for the company. You can filter by type:
        </p>
        <ul className="list-disc pl-5 space-y-1">
          <li><strong>10-K</strong> — Annual report (comprehensive financial and business overview)</li>
          <li><strong>10-Q</strong> — Quarterly report (interim financial data)</li>
          <li><strong>8-K</strong> — Current report (material events: earnings, acquisitions, leadership changes)</li>
        </ul>
        <p>
          Each filing shows its type, date, and description. Click the <strong>link icon</strong> to open
          the filing directly on the SEC EDGAR website, where you can read the full document.
        </p>
      </Section>

      <Section title="7. Valuation Tools">
        <p>
          The <strong>Valuation</strong> tab provides two analytical models for estimating a stock's intrinsic value.
        </p>
        <SubSection title="DCF Calculator (Discounted Cash Flow)">
          <p>
            The DCF model estimates what a company is worth based on its future cash flows, discounted back to present value.
          </p>
          <p className="font-medium">Inputs:</p>
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Growth Rate (%)</strong> — How fast you expect free cash flow to grow annually. Conservative: 5-10%. Aggressive: 15-25%.</li>
            <li><strong>Discount Rate (%)</strong> — Your required rate of return. Typical range: 8-15%. Higher = more conservative valuation.</li>
            <li><strong>Terminal Growth (%)</strong> — Long-run growth rate after the projection period. Usually 2-3% (roughly GDP growth).</li>
            <li><strong>Projection Years</strong> — How many years to project forward. Default: 10.</li>
          </ul>
          <p className="font-medium">Results:</p>
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Intrinsic Value / Share</strong> — The model's estimate of what the stock is worth.</li>
            <li><strong>Current Price</strong> — Today's market price for comparison.</li>
            <li><strong>Margin of Safety</strong> — How much cheaper (positive %) or more expensive (negative %) the stock is relative to intrinsic value. Graham recommends buying with at least a 25-30% margin of safety.</li>
            <li><strong>FCF Projections</strong> — Year-by-year table of projected free cash flows and their present values.</li>
          </ul>
        </SubSection>
        <SubSection title="Scenario Modeler (Bull / Base / Bear)">
          <p>
            The Scenario Modeler lets you define multiple future scenarios and assign probabilities to each.
            This is especially useful for growth companies where the range of outcomes is wide.
          </p>
          <p className="font-medium">Inputs for each scenario:</p>
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Revenue Growth %</strong> — Annual revenue growth rate over the next 5 years.</li>
            <li><strong>Terminal Margin %</strong> — Expected profit margin at maturity. Early-stage companies may have 0% margins today but could reach 10-20% at scale.</li>
            <li><strong>Discount Rate %</strong> — Higher for riskier scenarios (bear case might use 20%, bull case 12%).</li>
            <li><strong>Dilution/yr %</strong> — Annual share dilution from stock-based compensation. Pre-profit companies often dilute 5-10% annually.</li>
            <li><strong>Probability %</strong> — Your confidence that this scenario will play out. All scenarios should sum to 100%.</li>
          </ul>
          <p className="font-medium">Results:</p>
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Implied values</strong> — Each scenario's estimated per-share value.</li>
            <li><strong>Weighted Value</strong> — Probability-weighted average across all scenarios. This is your blended estimate of intrinsic value.</li>
            <li><strong>Upside/Downside %</strong> — How far the weighted value is from the current stock price.</li>
          </ul>
          <p>
            <strong>Tip:</strong> The default scenarios (Bull 25%, Base 50%, Bear 25%) are a reasonable starting point.
            Adjust the assumptions based on your research. For pre-profit companies, the bear case should consider
            the possibility that the company never reaches profitability.
          </p>
        </SubSection>
      </Section>

      <Section title="8. Graham Score">
        <p>
          The Graham Score evaluates a stock against Benjamin Graham's 7 criteria for defensive investors,
          as described in <em>The Intelligent Investor</em>. Each criterion is shown with a green checkmark
          (passed) or red X (failed), along with the actual value and threshold.
        </p>
        <SubSection title="The 7 criteria">
          <ol className="list-decimal pl-5 space-y-1.5">
            <li><strong>Adequate Size</strong> — Annual revenue exceeds $2 billion. This filters out smaller, more volatile companies.</li>
            <li><strong>Strong Financial Condition</strong> — Current ratio (current assets / current liabilities) is at least 2.0, indicating the company can cover short-term obligations.</li>
            <li><strong>Earnings Stability</strong> — Positive net income in each of the past 5+ years. No losses allowed.</li>
            <li><strong>Dividend Record</strong> — The company currently pays a dividend. (Graham originally required 20 years of uninterrupted dividends; this is relaxed for modern markets.)</li>
            <li><strong>Earnings Growth</strong> — At least 33% cumulative growth in earnings per share over available history.</li>
            <li><strong>Moderate P/E Ratio</strong> — Price-to-earnings ratio of 15 or below.</li>
            <li><strong>Moderate Price-to-Assets</strong> — Price-to-book ratio of 1.5 or below, OR the product of P/E and P/B is 22.5 or below.</li>
          </ol>
        </SubSection>
        <SubSection title="Graham Number & Margin of Safety">
          <p>
            The <strong>Graham Number</strong> is calculated as: sqrt(22.5 x EPS x Book Value per Share).
            It represents the maximum price a defensive investor should pay.
          </p>
          <p>
            The <strong>Margin of Safety</strong> shows how the Graham Number compares to the current stock price.
            A positive percentage means the stock trades below the Graham Number (potentially undervalued).
            A negative percentage means it trades above (potentially overvalued by Graham's standards).
          </p>
        </SubSection>
        <SubSection title="Interpreting the score">
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>5-7/7</strong> — Strong Graham candidate. The stock meets most defensive criteria.</li>
            <li><strong>3-4/7</strong> — Mixed. Some value characteristics but with caveats.</li>
            <li><strong>0-2/7</strong> — Does not meet Graham's defensive standards. This doesn't mean it's a bad investment — many excellent growth companies score low here.</li>
          </ul>
        </SubSection>
      </Section>

      <Section title="9. Growth Lens">
        <p>
          The Growth Lens appears on the Overview tab and provides metrics specifically designed for
          <strong> pre-profit and high-growth companies</strong> (like JOBY or early-stage tech companies)
          where traditional value metrics like P/E don't apply.
        </p>
        <SubSection title="Metrics explained">
          <ul className="list-disc pl-5 space-y-1.5">
            <li><strong>Revenue Growth Rates</strong> — Year-over-year revenue growth for each fiscal year. Look for acceleration (growth rate increasing) or deceleration.</li>
            <li><strong>Cash on Hand</strong> — Total cash and equivalents from the most recent quarter.</li>
            <li><strong>Burn Rate</strong> — How much cash the company consumed in the most recent quarter. Positive number = burning cash. Negative = generating cash.</li>
            <li><strong>Cash Runway (Quarters)</strong> — How many quarters the company can operate at the current burn rate before running out of cash. Less than 4 quarters is a warning sign.</li>
            <li><strong>Share Dilution Rate</strong> — Annual rate of new share issuance. High dilution (5%+ per year) erodes existing shareholders' value over time.</li>
            <li><strong>R&D Expense</strong> — Total research and development spending.</li>
            <li><strong>R&D as % of Revenue</strong> — How much of revenue is reinvested in R&D. Very high percentages (50%+) are common in early-stage tech/biotech.</li>
            <li><strong>Insider Activity</strong> — Count of insider buy and sell transactions in recent months. More buys than sells can signal management confidence.</li>
          </ul>
        </SubSection>
      </Section>

      <Section title="10. Data Sources & Freshness">
        <p>
          Investron uses two primary data sources, both free and publicly available:
        </p>
        <SubSection title="SEC EDGAR">
          <p>
            The Securities and Exchange Commission's EDGAR database is the authoritative source for all US public company filings.
            Investron uses EDGAR for:
          </p>
          <ul className="list-disc pl-5 space-y-1">
            <li>Structured financial data (XBRL format) — income statements, balance sheets, cash flow statements</li>
            <li>Filing history — 10-K, 10-Q, 8-K, and other SEC filings</li>
            <li>Company information — CIK numbers, exchanges, fiscal year end</li>
          </ul>
          <p>
            EDGAR data is typically available within 24 hours of a company filing with the SEC.
          </p>
        </SubSection>
        <SubSection title="yfinance">
          <p>
            yfinance provides real-time market data sourced from Yahoo Finance:
          </p>
          <ul className="list-disc pl-5 space-y-1">
            <li>Current stock prices and market capitalization</li>
            <li>Financial ratios (P/E, P/B, ROE, debt-to-equity)</li>
            <li>Dividend information</li>
            <li>Insider trading activity</li>
          </ul>
        </SubSection>
        <SubSection title="Data caching">
          <p>
            To keep the app fast and respect API rate limits, data is cached in the database with the following refresh intervals:
          </p>
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Financial statements</strong> — Refreshed every 24 hours</li>
            <li><strong>SEC filings list</strong> — Refreshed every 24 hours</li>
            <li><strong>Stock prices & metrics</strong> — Refreshed every 15 minutes</li>
            <li><strong>Company info</strong> — Refreshed every 7 days</li>
          </ul>
          <p>
            This means the first lookup for a new ticker may take a few seconds while data is fetched from external APIs.
            Subsequent visits will load almost instantly from the cache.
          </p>
        </SubSection>
        <SubSection title="Limitations">
          <ul className="list-disc pl-5 space-y-1">
            <li>Only US-listed companies with SEC filings are supported</li>
            <li>XBRL data coverage varies — some smaller companies may have incomplete financial data</li>
            <li>Prices are delayed (not real-time streaming); typically 15-minute delay</li>
            <li>Insider transaction data may not be complete for all companies</li>
          </ul>
        </SubSection>
      </Section>
    </div>
  )
}

/* ─── Developer Guide ─── */

function DeveloperGuide() {
  return (
    <div className="space-y-8">
      <Section title="Tech Stack">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div className="card space-y-2">
            <h3 className="font-semibold">Frontend</h3>
            <ul className="list-disc pl-5 space-y-1">
              <li>React 19 + TypeScript</li>
              <li>Vite 5 (dev server & bundler)</li>
              <li>React Router v6</li>
              <li>TanStack Query v5 (data fetching)</li>
              <li>Tailwind CSS v3</li>
              <li>Recharts (charts)</li>
              <li>Supabase JS (auth)</li>
              <li>Lucide React (icons)</li>
            </ul>
          </div>
          <div className="card space-y-2">
            <h3 className="font-semibold">Backend</h3>
            <ul className="list-disc pl-5 space-y-1">
              <li>FastAPI (Python async)</li>
              <li>SQLAlchemy 2.0 (async ORM)</li>
              <li>asyncpg (PostgreSQL driver)</li>
              <li>httpx (async HTTP client)</li>
              <li>yfinance (market data)</li>
              <li>Pydantic (validation)</li>
              <li>PostgreSQL via Supabase</li>
            </ul>
          </div>
        </div>
      </Section>

      <Section title="Architecture">
        <p>
          The frontend is a single-page React app that communicates with the FastAPI backend via REST API.
          The backend acts as a caching proxy between the user and two external data sources:
        </p>
        <div className="card font-mono text-xs whitespace-pre leading-5">
{`Browser (React)
  │
  ├── Supabase Auth (Google OAuth)
  │
  └── HTTP ──► FastAPI Backend (:8000)
                 │
                 ├──► PostgreSQL (Supabase)
                 │       ├── companies table
                 │       ├── filings_cache
                 │       ├── financial_data_cache (JSONB + TTL)
                 │       └── watchlist_items
                 │
                 ├──► SEC EDGAR API
                 │       ├── company_tickers.json (ticker → CIK mapping)
                 │       ├── submissions/CIK{cik}.json (filings)
                 │       └── api/xbrl/companyfacts/CIK{cik}.json (financials)
                 │
                 └──► yfinance
                         ├── Stock info (price, P/E, margins, etc.)
                         ├── Price history
                         └── Insider transactions`}
        </div>
      </Section>

      <Section title="Project Structure">
        <div className="card font-mono text-xs whitespace-pre leading-5">
{`investron/
├── backend/
│   ├── app/
│   │   ├── api/           # Route handlers (companies, financials, filings, valuation, watchlist)
│   │   ├── auth/          # Supabase JWT verification middleware
│   │   ├── models/        # database.py (SQLAlchemy async setup) + schemas.py (Pydantic)
│   │   ├── services/      # Business logic: edgar.py, yfinance_svc.py, valuation.py, etc.
│   │   ├── utils/         # cache.py (DB caching), rate_limiter.py (token bucket)
│   │   ├── config.py      # Pydantic Settings (env vars, TTLs)
│   │   └── main.py        # FastAPI app init, CORS, router registration
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── components/    # UI: layout/, research/, search/, charts/, dashboard/
│   │   ├── pages/         # Dashboard, Research, Docs, Login
│   │   ├── hooks/         # useAuth, useCompany, useWatchlist, useTheme
│   │   ├── lib/           # api.ts (HTTP client), supabase.ts, types.ts
│   │   └── styles/        # CSS variables + Tailwind base styles
│   └── package.json
└── .env.example`}
        </div>
      </Section>

      <Section title="Key Patterns">
        <SubSection title="Data fetching">
          <p>
            Frontend uses TanStack Query hooks that call the typed API client in <code className="text-xs bg-[var(--muted)] px-1 py-0.5 rounded">lib/api.ts</code>.
            The backend service layer checks the DB cache first, and only calls external APIs on cache miss.
            Cached data is stored as JSONB with expiration timestamps.
          </p>
        </SubSection>
        <SubSection title="Auth flow">
          <p>
            Google OAuth is handled entirely by Supabase. The frontend uses <code className="text-xs bg-[var(--muted)] px-1 py-0.5 rounded">supabase.auth.signInWithOAuth()</code>.
            The <code className="text-xs bg-[var(--muted)] px-1 py-0.5 rounded">useAuth</code> hook listens for session changes
            and gates access to the app routes.
          </p>
        </SubSection>
        <SubSection title="Caching strategy">
          <p>
            All external data flows through the DB cache with TTLs: financial data (24h), prices (15min), company info (7 days).
            Cache entries use <code className="text-xs bg-[var(--muted)] px-1 py-0.5 rounded">expires_at</code> timestamps — expired rows are re-fetched transparently.
          </p>
        </SubSection>
        <SubSection title="Rate limiting">
          <p>
            SEC EDGAR (10 req/s) and yfinance (5 req/s) have token bucket rate limiters to stay within API fair use policies.
          </p>
        </SubSection>
      </Section>

      <Section title="More Details">
        <p>
          For deeper technical documentation, see the README files on GitHub:
        </p>
        <ul className="list-disc pl-5 space-y-1">
          <li><strong>Frontend README</strong> — Component architecture, hooks reference, styling conventions</li>
          <li><strong>Backend README</strong> — Full API route table, database schema, service layer details, EDGAR integration</li>
        </ul>
      </Section>
    </div>
  )
}

/* ─── Release Notes ─── */

function ReleaseNotesTab() {
  const { data, isLoading, error } = useReleaseNotes()

  if (isLoading) {
    return <p className="text-sm text-[var(--muted-foreground)]">Loading release notes...</p>
  }

  if (error) {
    return <p className="text-sm text-red-500">Failed to load release notes.</p>
  }

  const releases = data?.releases ?? []

  if (releases.length === 0) {
    return <p className="text-sm text-[var(--muted-foreground)]">No release notes available.</p>
  }

  return (
    <div className="space-y-6">
      {releases.map((release) => (
        <ReleaseCard key={release.version} release={release} />
      ))}
    </div>
  )
}

function ReleaseCard({ release }: { release: ReleaseNote }) {
  return (
    <div className="card space-y-3">
      <div className="flex items-center justify-between">
        <h2 className="text-lg font-semibold">v{release.version} — {release.title}</h2>
        <span className="text-sm text-[var(--muted-foreground)]">{release.date}</span>
      </div>
      <p className="text-sm text-[var(--muted-foreground)]">{release.summary}</p>
      <div className="space-y-2">
        {release.sections.map((section) => (
          <CollapsibleSection key={section.type} section={section} />
        ))}
      </div>
    </div>
  )
}

const SECTION_ICONS: Record<string, React.ReactNode> = {
  new_feature: <Tag className="w-4 h-4 text-green-500" />,
  enhancement: <Wrench className="w-4 h-4 text-blue-500" />,
  bug_fix: <Bug className="w-4 h-4 text-orange-500" />,
}

function CollapsibleSection({ section }: { section: ReleaseNoteSection }) {
  const [isOpen, setIsOpen] = useState(true)

  return (
    <div className="border border-[var(--border)] rounded-md">
      <button
        onClick={() => setIsOpen(!isOpen)}
        className="w-full flex items-center gap-2 px-3 py-2 text-sm font-medium hover:bg-[var(--muted)] transition-colors rounded-md"
      >
        {isOpen ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
        {SECTION_ICONS[section.type]}
        {section.label}
        <span className="text-[var(--muted-foreground)] ml-auto">{section.items.length}</span>
      </button>
      {isOpen && (
        <ul className="px-3 pb-3 space-y-1">
          {section.items.map((item, i) => (
            <li key={i} className="text-sm text-[var(--foreground)] pl-8 list-disc">
              {item}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}
