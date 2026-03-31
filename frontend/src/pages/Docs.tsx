import { useState } from 'react'
import { ChevronDown, ChevronRight, Tag, Wrench, Bug } from 'lucide-react'
import { PageLayout } from '@/components/layout/PageLayout'
import { useReleaseNotes } from '@/hooks/useReleaseNotes'
import type { ReleaseNote, ReleaseNoteSection } from '@/lib/types'

type Tab = 'user' | 'buffett' | 'wheel' | 'developer' | 'releases'

const TABS: { key: Tab; label: string }[] = [
  { key: 'user', label: 'User Guide' },
  { key: 'buffett', label: 'Buffett Scorecard Guide' },
  { key: 'wheel', label: 'Wheel Strategy Guide' },
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
          {activeTab === 'buffett' && <BuffettGuide />}
          {activeTab === 'wheel' && <WheelGuide />}
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
            <li><strong>Trading</strong> — Automated paper trading strategies (see section 10)</li>
            <li><strong>Search bar</strong> — Type any ticker (e.g., AAPL, NVDA) to jump to its Research page</li>
            <li><strong>Docs</strong> — This documentation page</li>
            <li><strong>Theme toggle</strong> — Switch between dark and light modes (moon/sun icon)</li>
            <li><strong>Sign out</strong> — Log out of your account (door icon)</li>
          </ul>
        </SubSection>
      </Section>

      <Section title="2. Dashboard & Watchlist">
        <p>
          The Dashboard shows your personal watchlist — a table of stocks you're tracking — and the
          Value Screener, which automatically ranks S&P 500 stocks by value (see section 3).
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

      <Section title="3. Value Screener">
        <p>
          Below the Watchlist, the <strong>Value Screener</strong> panel ranks all S&P 500 companies (~500 stocks)
          by a composite value score inspired by Benjamin Graham and Warren Buffett. A background engine
          re-scores every stock once daily at market close — no action needed from you.
        </p>
        <SubSection title="How the composite score works">
          <p>
            Each stock receives a score from 0 to 100 based on a weighted blend of value metrics. Higher scores
            indicate stronger value characteristics. The weights are:
          </p>
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Margin of Safety (25%)</strong> — How far the stock price is below the Graham Number (intrinsic value). Larger discounts score higher.</li>
            <li><strong>P/E Ratio (15%)</strong> — Price-to-Earnings. Lower is better — Graham preferred P/E under 15.</li>
            <li><strong>FCF Yield (15%)</strong> — Free Cash Flow relative to market cap. Higher yield = more cash generated per dollar invested.</li>
            <li><strong>Earnings Yield (10%)</strong> — Inverse of P/E (1/PE). Higher means you're paying less for each dollar of earnings.</li>
            <li><strong>P/B Ratio (10%)</strong> — Price-to-Book. Lower means you pay less per dollar of net assets. Graham preferred under 1.5.</li>
            <li><strong>ROE (10%)</strong> — Return on Equity. Measures how efficiently the company turns equity into profit.</li>
            <li><strong>Debt/Equity (10%)</strong> — Lower debt relative to equity scores higher. Conservative balance sheets are preferred.</li>
            <li><strong>Dividend Yield (5%)</strong> — Annual income returned to shareholders. A small bonus for dividend payers.</li>
          </ul>
        </SubSection>
        <SubSection title="Column descriptions">
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>#</strong> — Rank by composite score (1 = best value).</li>
            <li><strong>Score</strong> — The composite value score (0-100). Green = strong (&ge;55), amber = moderate (&ge;35), red = weak.</li>
            <li><strong>Price</strong> — Current market share price (not intrinsic value).</li>
            <li><strong>MoS %</strong> — Margin of Safety. Positive (green) = stock trades below the Graham Number. Negative (red) = trades above.</li>
            <li><strong>P/E</strong> — Price-to-Earnings ratio. Click to sort (lowest first).</li>
            <li><strong>P/B</strong> — Price-to-Book ratio. Click to sort (lowest first).</li>
            <li><strong>ROE</strong> — Return on Equity percentage.</li>
            <li><strong>Div %</strong> — Dividend yield percentage. A dash means no dividend.</li>
            <li><strong>Flags</strong> — Warning dots (hover to see details). Red = high severity (e.g., negative earnings), amber = medium (e.g., declining revenue), blue = low (e.g., very high P/E).</li>
          </ul>
        </SubSection>
        <SubSection title="Features">
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Sortable columns</strong> — Click any column header with arrows to sort. P/E and P/B default to ascending (lower is better); all others default to descending.</li>
            <li><strong>Sector filter</strong> — Use the dropdown to filter by GICS sector (e.g., Technology, Healthcare).</li>
            <li><strong>Add to Watchlist</strong> — Click the + icon on any row to add it to your personal Watchlist above.</li>
            <li><strong>Research link</strong> — Click the arrow icon or the ticker name to open the full Research page for that stock.</li>
            <li><strong>Auto-refresh</strong> — The background scanner re-scores all stocks once daily at market close (~5 PM ET). The "Updated" timestamp shows when the last scan completed.</li>
          </ul>
        </SubSection>
        <SubSection title="Important notes">
          <ul className="list-disc pl-5 space-y-1">
            <li>Scores are based on publicly available market data from Yahoo Finance — not EDGAR filings.</li>
            <li>High scores do not mean "buy." The screener surfaces candidates for further research, not investment recommendations.</li>
            <li>Warning flags are informational — distressed or risky stocks are never filtered out, only flagged.</li>
            <li>Some tickers may show incomplete data if yfinance doesn't have full coverage.</li>
          </ul>
        </SubSection>
      </Section>

      <Section title="4. Company Research">
        <p>
          Search for any publicly traded US company using the search bar in the header. Type a ticker
          symbol (e.g., GOOGL) and select from the results. This opens the <strong>Research</strong> page,
          which has five tabs:
        </p>
        <SubSection title="Research page header">
          <p>
            At the top you'll see the ticker, company name, sector, industry, exchange, current stock price,
            and market capitalization.
          </p>
        </SubSection>
      </Section>

      <Section title="5. Overview Tab">
        <p>
          The Overview tab provides a snapshot of the company:
        </p>
        <ul className="list-disc pl-5 space-y-1">
          <li><strong>Key Metrics</strong> — A grid of important financial ratios and figures:
            P/E ratio, P/B ratio, market cap, dividend yield, 52-week high/low, profit margins, ROE, debt-to-equity, and more.
          </li>
          <li><strong>Graham Score</strong> — Benjamin Graham's evaluation (see section 11 below for details).</li>
          <li><strong>Growth Lens</strong> — Metrics designed for pre-profit or high-growth companies (see section 12).</li>
          <li><strong>Price chart</strong> — Historical stock price visualization.</li>
        </ul>
      </Section>

      <Section title="6. Financial Statements">
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

      <Section title="7. SEC Filings">
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

      <Section title="8. Valuation Tools">
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

      <Section title="9. AI Analysis">
        <p>
          The <strong>AI Analysis</strong> tab on the Research page provides a conversational AI research assistant
          powered by GPT-4o. It has access to all of the company's structured data — key metrics, Graham Score,
          growth metrics, financial statements, and screener scores — so it can reason with real numbers rather
          than general knowledge.
        </p>
        <SubSection title="How to use it">
          <p>
            Type a question in the chat input or click one of the suggestion chips to get started.
            The assistant streams its response in real time. You can ask follow-up questions — the conversation
            context is preserved within the session.
          </p>
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Suggestion chips</strong> — Pre-built prompts for common analyses (valuation frameworks, scenario analysis, risk/catalyst review, DCF walkthrough).</li>
            <li><strong>Shift+Enter</strong> — Insert a new line without sending.</li>
            <li><strong>Stop button</strong> — Cancel a response mid-stream.</li>
            <li><strong>Clear chat</strong> — Start a fresh conversation (trash icon in the header).</li>
          </ul>
        </SubSection>
        <SubSection title="Filing Deep Search">
          <p>
            By default, the AI reasons from structured data only (ratios, scores, financial tables). To give it access
            to the <strong>narrative content</strong> inside SEC filings — risk factors, management discussion, business
            strategy, acquisition disclosures, earnings guidance — you can index a company's filings.
          </p>
          <p className="font-medium">How to enable:</p>
          <ol className="list-decimal pl-5 space-y-1">
            <li>Open the AI Analysis tab for a company.</li>
            <li>Click the blue <strong>Index Filings</strong> button in the banner.</li>
            <li>Wait for indexing to complete (typically 2-5 minutes). Progress updates show in real time.</li>
            <li>Once the banner turns green ("Filing search active"), the AI can now search filing text.</li>
          </ol>
          <p className="font-medium">What gets indexed:</p>
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>10-K</strong> — Up to 3 most recent annual reports (comprehensive business and financial overview).</li>
            <li><strong>10-Q</strong> — Up to 5 most recent quarterly reports (interim updates).</li>
            <li><strong>8-K</strong> — Up to 10 most recent current reports (material events: earnings, acquisitions, leadership changes).</li>
          </ul>
          <p>
            Filings are broken into searchable chunks organized by section (e.g., Risk Factors, MD&A, Financial Statements).
            When you ask a question, the AI automatically decides whether to search the filing text and retrieves the
            most relevant passages. Responses cite the specific filing type and date so you can verify against the source.
          </p>
          <p className="font-medium">Suggested questions when filings are indexed:</p>
          <ul className="list-disc pl-5 space-y-1">
            <li>"What risk factors does the 10-K mention?"</li>
            <li>"Summarize the MD&A section"</li>
            <li>"Any recent acquisitions or material events?"</li>
            <li>"What does management say about competitive landscape?"</li>
          </ul>
        </SubSection>
        <SubSection title="Managing the index">
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Re-index</strong> — Click the refresh icon on the green banner to re-run indexing (e.g., after new filings are published).</li>
            <li><strong>Remove index</strong> — Click the trash icon on the green banner to delete all indexed data for that company.</li>
            <li>Indexing is per-company and on-demand — only companies you choose to index are processed.</li>
          </ul>
        </SubSection>
        <SubSection title="Important notes">
          <ul className="list-disc pl-5 space-y-1">
            <li>The AI uses GPT-4o for analysis and may occasionally produce inaccurate conclusions. Always verify against the source filings.</li>
            <li>Filing indexing requires the SEC EDGAR full-text filings to be available (most US public companies).</li>
            <li>Conversations are stored in your browser session only — they are not saved across page reloads.</li>
            <li>The assistant is for research purposes only and does not provide investment advice.</li>
          </ul>
        </SubSection>
      </Section>

      <Section title="10. Paper Trading">
        <p>
          The <strong>Trading</strong> page lets Investron automatically trade on your behalf using
          Alpaca Markets' paper trading API. This is <strong>simulated trading with fake money</strong> —
          no real funds are at risk. Two independent strategies are available:
        </p>
        <SubSection title="Strategies">
          <ul className="list-disc pl-5 space-y-1.5">
            <li><strong>Simple Stock Trading ($500)</strong> — AI-powered buying and selling of common stock.
              Uses the screener's composite scores as a free first filter, then sends top candidates to GPT-4o
              for a buy/hold/sell signal with confidence rating. The AI receives full financial statements and,
              when available, relevant excerpts from SEC filings (risk factors, MD&A, guidance) for deeper analysis.
              Only high-conviction signals are executed.</li>
            <li><strong>The Wheel Strategy ($30,000)</strong> — A mechanical options income strategy: sell cash-secured puts
              on screener-selected stocks, get assigned if the put expires in-the-money, then sell covered calls until the
              stock is called away. Candidates are dynamically chosen from the screener by composite score, price, market cap,
              and sector diversification. Includes defensive features like hard stops,
              rolling puts, and adjusted cost basis tracking. See the <strong>Wheel Strategy Guide</strong> tab for
              a detailed explanation.</li>
          </ul>
        </SubSection>
        <SubSection title="Page tabs">
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Overview</strong> — Portfolio summary (total value, P&L) and strategy cards showing status, capital, and controls.</li>
            <li><strong>Positions</strong> — All open and closed positions with entry price, current value, and P&L.</li>
            <li><strong>Order History</strong> — Every order submitted to Alpaca, including the AI reasoning that triggered each trade.</li>
            <li><strong>Activity Log</strong> — Event stream with filter pills (Decisions, Executions, Blocked, Errors),
              date range picker, and expandable detail rows. Click any event to see structured details including
              decision reasoning, fill amounts, and filter breakdowns.</li>
          </ul>
        </SubSection>
        <SubSection title="Starting a strategy">
          <ol className="list-decimal pl-5 space-y-1">
            <li>Ensure Alpaca API keys are configured and <code className="text-xs bg-[var(--muted)] px-1 py-0.5 rounded">TRADING_ENABLED=true</code> is set in the backend environment.</li>
            <li>Navigate to the Trading page.</li>
            <li>Click the <strong>Start</strong> button on a strategy card.</li>
            <li>The trading engine will begin running cycles during US market hours (Mon-Fri, 9 AM - 4 PM ET).</li>
          </ol>
          <p>
            You can <strong>Pause</strong> (monitor positions but open no new trades), <strong>Stop</strong> (cease all activity),
            or <strong>Reset</strong> (return to initial capital) at any time using the buttons on each strategy card.
          </p>
        </SubSection>
        <SubSection title="How Simple Stock Trading works">
          <p>Each cycle (approximately every 30 minutes during market hours):</p>
          <ol className="list-decimal pl-5 space-y-1">
            <li><strong>Sync orders</strong> — Checks Alpaca for fills on pending orders and updates local records.</li>
            <li><strong>Check sells</strong> — For each open position: triggers stop-loss if price dropped &gt;10% from entry
              (with 3-layer confirmation and stop-limit order), take-profit if price rose &gt;20% (with limit order),
              or asks GPT-4o whether to sell. All sell triggers pass execution safety checks before executing.</li>
            <li><strong>Find buys</strong> — Pulls the top 20 stocks from the screener by composite score.
              Filters by minimum score (60+), then asks GPT-4o for a buy signal (max 5 AI calls per cycle to control costs).
              High-conviction buys are executed as limit orders, sized at up to 25% of strategy capital per position.</li>
          </ol>
        </SubSection>
        <SubSection title="Automatic filing research">
          <p>
            Once per day, the trading engine automatically indexes SEC filings (10-K, 10-Q, 8-K) for the top 10
            screener candidates. This uses the same indexing pipeline as the AI Analysis tab's "Filing Deep Search."
            When the AI evaluates a trade signal, it searches these indexed filings for relevant excerpts —
            risk factors, management commentary, and forward guidance — and factors them into its decision.
            Tickers that haven't been indexed yet still receive signals based on financial metrics alone.
          </p>
        </SubSection>
        <SubSection title="Safety features">
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Circuit breaker</strong> — Automatically pauses the strategy if total drawdown exceeds 20% of initial capital.</li>
            <li><strong>Position limits</strong> — No single position can exceed 25% of capital.</li>
            <li><strong>Stop-loss / take-profit</strong> — Automatic sell triggers at -10% and +20%, with multi-layer confirmation before executing.</li>
            <li><strong>Independent price confirmation</strong> — Stop-loss and take-profit triggers cross-check Alpaca prices against yfinance. If the two sources disagree by more than 5%, the trade is blocked (prevents false triggers from bad data).</li>
            <li><strong>Spread &amp; staleness checks</strong> — Blocks all trades when bid/ask spread exceeds 2% (illiquid) or the last trade price is more than 5 minutes old during market hours (stale data).</li>
            <li><strong>Limit orders only</strong> — No market orders. Buys use limit orders with a small buffer, sells use limit or stop-limit orders for controlled execution.</li>
            <li><strong>Market hours only</strong> — The engine only runs during US market hours to avoid stale quotes.</li>
            <li><strong>AI cost cap</strong> — Max 5 GPT-4o calls per cycle keeps API costs predictable (~$0.40-1.20/day).</li>
            <li><strong>Master kill switch</strong> — <code className="text-xs bg-[var(--muted)] px-1 py-0.5 rounded">TRADING_ENABLED=false</code> prevents the engine from starting entirely.</li>
          </ul>
        </SubSection>
        <SubSection title="Important notes">
          <ul className="list-disc pl-5 space-y-1">
            <li>This is <strong>paper trading only</strong> — no real money is involved. All trades execute against Alpaca's simulated market.</li>
            <li>The two strategies share one Alpaca paper account but track capital independently in the database ($500 vs $30,000).</li>
            <li>AI trade signals are logged on every order for full audit trail — see the Order History tab for the reasoning behind each trade.</li>
            <li>The AI is for experimentation, not financial advice. Past simulated performance does not predict future results.</li>
          </ul>
        </SubSection>
      </Section>

      <Section title="11. Graham Score">
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

      <Section title="12. Growth Lens">
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

      <Section title="13. Data Sources & Freshness">
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

/* ─── Buffett Scorecard Guide ─── */

function BuffettGuide() {
  return (
    <div className="space-y-8">

      <Section title="Overview">
        <p>
          The <strong>Buffett Scorecard</strong> evaluates any publicly traded stock against Warren Buffett's four
          investing rules, as documented at <em>BuffettsBooks.com</em>. It is not a buy/sell signal — it is a structured
          framework for fundamental due diligence that surfaces the quantitative data behind each rule so you can make an
          informed judgment.
        </p>
        <p>
          Select a ticker using the search box in the top-right of the card. The card loads all four rules automatically
          (data is cached for 15 minutes). Your last selected ticker is saved in the browser and restored on reload.
        </p>
      </Section>

      <Section title="Rule 1 — Vigilant Leadership">
        <p>Evaluates current financial health and management discipline via three quantitative metrics and one contextual indicator.</p>

        <SubSection title="Debt-to-Equity Ratio (D/E)">
          <p><strong>Source:</strong> yfinance <code>debtToEquity</code> — returned as a percentage (e.g. 42.3 = a ratio of 0.423x). The card divides by 100 for display.</p>
          <p><strong>Formula:</strong> Total Long-Term Debt ÷ Shareholders' Equity</p>
          <p><strong>Thresholds:</strong> &lt; 0.50x = Pass, 0.50–1.00x = Borderline, ≥ 1.00x = Fail</p>
          <p>Companies with low debt survive recessions and don't divert profits to interest payments. If D/E is negative (e.g. McDonald's, Starbucks — companies that have bought back more stock than their book equity), the card flags negative equity and marks Rule 4 inapplicable. For financial sector companies (banks, insurers), a warning is shown since high leverage is structural, not a risk signal.</p>
        </SubSection>

        <SubSection title="Current Ratio">
          <p><strong>Source:</strong> yfinance <code>currentRatio</code></p>
          <p><strong>Formula:</strong> Current Assets ÷ Current Liabilities</p>
          <p><strong>Thresholds:</strong> &gt; 1.50x = Pass, 1.00–1.50x = Borderline, &lt; 1.00x = Fail</p>
          <p>A ratio above 1.0 means the company can cover all short-term obligations without new borrowing. Buffett wants management that keeps the balance sheet clean.</p>
        </SubSection>

        <SubSection title="Return on Equity (ROE)">
          <p><strong>Source:</strong> yfinance <code>returnOnEquity</code> (decimal, e.g. 0.184 = 18.4%)</p>
          <p><strong>Formula:</strong> Net Income ÷ Shareholders' Equity</p>
          <p><strong>Thresholds:</strong> &gt; 15% = Pass, 10–15% = Borderline, &lt; 10% = Fail</p>
          <p>Consistently high ROE signals a durable competitive advantage — the company isn't just lucky, it repeatedly earns high returns on the equity entrusted to it.</p>
        </SubSection>

        <SubSection title="Price-to-Book Ratio (P/B) — context only">
          <p><strong>Source:</strong> yfinance <code>priceToBook</code></p>
          <p><strong>Formula:</strong> Market Price per Share ÷ Book Value per Share</p>
          <p>No pass/fail threshold. A high P/B means the market is already pricing in future growth, leaving less margin of safety. A P/B near 1.0 means you are paying close to liquidation value.</p>
        </SubSection>
      </Section>

      <Section title="Rule 2 — Long-Term Prospects">
        <p>Rule 2 is informational rather than scored. It shows the historical trajectory of earnings and revenue, and provides an on-demand AI durability analysis.</p>

        <SubSection title="EPS (Diluted) History">
          <p><strong>Source:</strong> EDGAR annual income statements — <code>eps_diluted</code> field (falls back to <code>eps_basic</code>)</p>
          <p><strong>Chart:</strong> Sparkline with one point per fiscal year. X-axis shows the first and last year. Hover for the exact dollar value.</p>
          <p><strong>Consecutive Positive EPS Years:</strong> Number of consecutive fiscal years at the end of the series where EPS was positive. A long streak (7–10+ years) signals consistent profitability.</p>
          <p><strong>EPS CAGR:</strong> (EPS_latest / EPS_oldest) ^ (1 / (years − 1)) − 1. Smooths year-to-year noise to show the true growth trajectory.</p>
        </SubSection>

        <SubSection title="Revenue History">
          <p><strong>Source:</strong> EDGAR annual income statements — <code>revenue</code> field. Displayed in billions (÷ 1,000,000,000).</p>
          <p><strong>Revenue CAGR:</strong> Same formula as EPS CAGR applied to revenue. A company growing revenue at &gt;5–10%/yr is expanding its economic footprint.</p>
        </SubSection>

        <SubSection title="AI Durability Analysis (on-demand)">
          <p>Click <strong>Analyze</strong> to trigger a streaming AI analysis using a reasoning model. It assesses: (1) Will this product or service exist in 20–30 years? (2) Is the business model understandable and predictable? (3) What are the key long-term durability risks? The AI is provided sector, industry, financial history, and recent news headlines. Not auto-triggered — each run costs an API call.</p>
        </SubSection>
      </Section>

      <Section title="Rule 3 — Stable & Understandable">
        <p>Rule 3 evaluates multi-year trends using historical EDGAR filings. All four charts are annual, one data point per fiscal year (typically 5–10 years of history).</p>

        <SubSection title="Book Value per Share (BV/Share)">
          <p><strong>Source:</strong> EDGAR annual balance sheets</p>
          <p><strong>Formula:</strong> Stockholders' Equity ÷ Shares Outstanding</p>
          <p><strong>Good direction:</strong> Increasing. Steady BV growth means the company is retaining and compounding value. This is also the foundation of the Rule 4 intrinsic value formula.</p>
        </SubSection>

        <SubSection title="D/E Ratio History">
          <p><strong>Source:</strong> EDGAR annual balance sheets</p>
          <p><strong>Formula:</strong> Long-Term Debt ÷ Stockholders' Equity (raw ratio, not the yfinance % form used in Rule 1)</p>
          <p><strong>Good direction:</strong> Declining or stable. Improving leverage over time signals strengthening financial health.</p>
        </SubSection>

        <SubSection title="EPS Trend">
          <p><strong>Source:</strong> EDGAR annual income statements — <code>eps_diluted</code></p>
          <p><strong>Good direction:</strong> Increasing. Consistently growing EPS indicates durable earnings power.</p>
        </SubSection>

        <SubSection title="ROE Trend">
          <p><strong>Source:</strong> EDGAR income statements + balance sheets, joined by fiscal year</p>
          <p><strong>Formula:</strong> Net Income ÷ Stockholders' Equity (decimal)</p>
          <p><strong>Good direction:</strong> Stable or increasing. Consistently above 15% year after year is a hallmark of a durable moat.</p>
        </SubSection>

        <SubSection title="Scoring">
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>PASS</strong> — all four trends moving in the good direction</li>
            <li><strong>MIXED</strong> — 2–3 of 4 trending well</li>
            <li><strong>FAIL</strong> — fewer than 2 trending well</li>
            <li><strong>N/A</strong> — fewer than 3 years of EDGAR data</li>
          </ul>
        </SubSection>
      </Section>

      <Section title="Rule 4 — Intrinsic Value">
        <p>
          Rule 4 computes an intrinsic value (IV) using the <strong>BuffettsBooks.com Book Value DCF methodology</strong> and
          compares it to the current market price. Rule 4 is inapplicable when:
        </p>
        <ul className="list-disc pl-5 space-y-1 mt-1">
          <li><strong>Negative equity</strong> — the BV DCF formula requires positive book value (common in heavy buyback programs like MCD, SBUX)</li>
          <li><strong>Near-zero equity</strong> — when P/B &gt; 50×, book value is less than 2% of the market price and the DCF produces an economically meaningless result (e.g. HALO: BV = $0.41/share, price = $63 → IV ≈ $0.94). The company's real value comes from future earnings, not assets.</li>
          <li><strong>Insufficient history</strong> — fewer than 3 years of EDGAR balance sheet data</li>
        </ul>
        <p className="mt-1">
          When Rule 4 is inapplicable, the card automatically shows an <strong>Earnings Power Analysis</strong> instead (see below).
          An <strong>AI Valuation</strong> is also available on demand.
        </p>

        <SubSection title="Inputs">
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Current BV/Share:</strong> yfinance <code>bookValue</code> (dollars per share)</li>
            <li><strong>Oldest BV/Share:</strong> Earliest EDGAR balance sheet — Stockholders' Equity ÷ Shares Outstanding</li>
            <li><strong>Annual Dividend:</strong> yfinance <code>dividendRate</code> (annualized dollars per share). Fallback: Current Price × <code>dividendYield</code>. Zero if no dividend — Rule 4 is still valid.</li>
            <li><strong>10Y Treasury Rate:</strong> yfinance <code>^TNX</code> → regularMarketPrice ÷ 100 (cached 24h). Clamped to a minimum of 0.001 to avoid division by zero. Override-able in the card UI.</li>
          </ul>
        </SubSection>

        <SubSection title="BV Growth Rate">
          <p className="font-mono text-xs bg-[var(--muted)] px-3 py-2 rounded">
            BV Growth Rate = (Current BV / Oldest BV) ^ (1 / Years Between) − 1
          </p>
          <p className="mt-1">This is the single most important input — it determines how fast book value is projected to grow for the next 10 years. If the rate exceeds 20%/yr, a warning is shown because the stability assumption is less reliable for high-growth companies.</p>
        </SubSection>

        <SubSection title="Intrinsic Value Formula">
          <div className="space-y-2">
            <p><strong>Step 1 — Project BV forward 10 years:</strong></p>
            <p className="font-mono text-xs bg-[var(--muted)] px-3 py-2 rounded">BV_future = Current BV × (1 + BV Growth Rate) ^ 10</p>
            <p><strong>Step 2 — Discount BV back to present value:</strong></p>
            <p className="font-mono text-xs bg-[var(--muted)] px-3 py-2 rounded">PV_of_BV = BV_future / (1 + Treasury Rate) ^ 10</p>
            <p><strong>Step 3 — Present value of dividend annuity over 10 years:</strong></p>
            <p className="font-mono text-xs bg-[var(--muted)] px-3 py-2 rounded">PV_of_divs = Annual Dividend × [1 − (1 + Treasury Rate) ^ −10] / Treasury Rate</p>
            <p><strong>Step 4 — Intrinsic Value:</strong></p>
            <p className="font-mono text-xs bg-[var(--muted)] px-3 py-2 rounded">IV = PV_of_BV + PV_of_divs</p>
          </div>
        </SubSection>

        <SubSection title="Margin of Safety">
          <p className="font-mono text-xs bg-[var(--muted)] px-3 py-2 rounded">
            Margin of Safety = (IV − Current Price) / Current Price × 100
          </p>
          <ul className="list-disc pl-5 space-y-1 mt-2">
            <li><strong>≥ 15%</strong> — UNDERVALUED: stock may be trading below estimated IV</li>
            <li><strong>0–15%</strong> — NEAR IV: modest buffer</li>
            <li><strong>&lt; 0%</strong> — OVERVALUED: stock is above estimated IV under this model</li>
          </ul>
          <p className="mt-1">Buffett typically requires 15–25% margin of safety to account for estimation error in the growth rate. A positive margin does not guarantee a good investment.</p>
        </SubSection>
      </Section>

      <Section title="Earnings Power Analysis (Rule 4 Alternative)">
        <p>
          When Rule 4's BV-DCF is inapplicable, the right panel automatically switches to an <strong>Earnings Power Analysis</strong>.
          The question shifts from "what are the assets worth?" to "does the stock earn more per dollar than a risk-free Treasury bond,
          and can the company support its debt?"
        </p>

        <SubSection title="Earnings Yield vs Treasury">
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Earnings Yield</strong> — EPS ÷ Price × 100. Buffett's core bond-vs-stock comparison: if earnings yield &gt; Treasury rate, the stock earns more per dollar than a risk-free bond. PASS if ≥ 1.5× Treasury; BORDERLINE if ≥ Treasury; FAIL if below.</li>
            <li><strong>FCF Yield</strong> — Free Cash Flow ÷ Market Cap × 100. Cash flow is harder to manipulate than earnings — a more honest picture of what the business actually generates. Same pass/fail thresholds as Earnings Yield.</li>
            <li>Both metrics use the same live 10Y Treasury rate as Rule 4's discount rate.</li>
          </ul>
        </SubSection>

        <SubSection title="Valuation & Growth">
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>P/E (trailing / forward)</strong> — context only, no pass/fail. Forward P/E below trailing suggests analysts expect earnings growth.</li>
            <li><strong>EPS CAGR</strong> — for companies where BV is not a reliable anchor, consistent earnings growth is the next best signal of durable value. PASS if &gt;10%/yr. Consecutive positive EPS years also displayed.</li>
          </ul>
        </SubSection>

        <SubSection title="Debt Health">
          <p>When D/E is broken by near-zero or negative equity, these metrics replace it:</p>
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Net Debt / EBITDA</strong> — (Total Debt − Cash) ÷ EBITDA. How many years of operating earnings to retire net debt. PASS if &lt;3× (or net cash); BORDERLINE 3–5×; FAIL &gt;5×. A net cash position (more cash than debt) always passes.</li>
            <li><strong>Interest Coverage</strong> — Operating Income ÷ Interest Expense (most recent EDGAR annual). Can the company comfortably service its debt? PASS if ≥5×; BORDERLINE 2–5×; FAIL &lt;2×. Source: EDGAR annual income statements.</li>
          </ul>
        </SubSection>
      </Section>

      <Section title="AI Valuation Analysis (Option B)">
        <p>
          When Rule 4 is inapplicable, the card also offers an AI-powered alternative valuation using a reasoning model (o4-mini).
          The AI receives analyst consensus, recent news headlines, and excerpts from the most recent 10-K and 10-Q filings
          via semantic search.
        </p>

        <SubSection title="Filing Indexing">
          <p>SEC filings must be indexed into the vector database before the AI can search them. The card handles this automatically:</p>
          <ul className="list-disc pl-5 space-y-1">
            <li>If the ticker is already indexed — proceed directly to streaming</li>
            <li>If not — trigger indexing automatically and show an animated progress indicator (typically 30–90 seconds)</li>
            <li>Once indexed — stream the AI response token-by-token</li>
          </ul>
        </SubSection>

        <SubSection title="Company Classification">
          <p>The AI classifies the company and tailors its analysis accordingly:</p>
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Category A — Mature:</strong> Positive consistent EPS, stable revenue → DCF on earnings, comparable multiples, dividend yield</li>
            <li><strong>Category B — Growth:</strong> Growing revenue, EPS not yet stable → Revenue multiple, growth-adjusted P/E, path to profitability</li>
            <li><strong>Category C — Pre-Profitable:</strong> Negative or erratic EPS → Capital runway analysis, burn rate, milestone-based framework</li>
          </ul>
          <p className="mt-1">For Category C companies, the AI explicitly addresses how many quarters of runway remain at the current burn rate and what must happen for the company to reach profitability. The output includes bear/base/bull scenario analysis with specific price targets.</p>
        </SubSection>
      </Section>

      <Section title="Known Limitations">
        <ul className="list-disc pl-5 space-y-1">
          <li><strong>Negative equity</strong> (MCD, SBUX, etc.) — share buybacks can make book equity negative. Rule 4 is inapplicable; the Earnings Power panel is shown automatically.</li>
          <li><strong>Near-zero equity</strong> (e.g. HALO) — P/B &gt; 50× means book value is less than 2% of market price; the BV-DCF result is meaningless. The Earnings Power panel is shown automatically.</li>
          <li><strong>Financial sector</strong> (banks, insurers) — D/E thresholds don't apply. Rules 3 and 4 may be computed but should be interpreted with caution.</li>
          <li><strong>Stock splits</strong> — BV/share history may show a discontinuity around a split date, distorting the growth rate calculation.</li>
          <li><strong>High BV growth (&gt;20%/yr)</strong> — the stability assumption behind the 10-year DCF projection is less reliable. The card flags this.</li>
          <li><strong>Model risk</strong> — Rule 4's IV is based on historical BV growth and a single discount rate. It is not a prediction of future returns.</li>
          <li><strong>Data coverage</strong> — EDGAR history typically covers 5–10 years. Newer public companies may show N/A for Rules 3 and 4.</li>
        </ul>
      </Section>

    </div>
  )
}

/* ─── Wheel Strategy Guide ─── */

function WheelGuide() {
  return (
    <div className="space-y-8">
      <Section title="1. What Is the Wheel?">
        <p>
          The Wheel is a <strong>mechanical options income strategy</strong> that generates returns through
          options premiums rather than stock price appreciation. It cycles through three phases:
        </p>
        <ol className="list-decimal pl-5 space-y-2">
          <li>
            <strong>Sell a cash-secured put</strong> — You sell someone the right to sell you 100 shares
            of a stock at a specific price (the <em>strike price</em>) by a specific date (the <em>expiration</em>).
            In exchange, you receive a <em>premium</em> (cash payment) upfront. You must keep enough cash on
            hand to buy the shares if required — this is the "cash-secured" part.
          </li>
          <li>
            <strong>Get assigned (if the put expires in-the-money)</strong> — If the stock price is below
            the strike at expiration, you're <em>assigned</em>: you must buy 100 shares at the strike price.
            This is expected and part of the plan — you're buying a stock you wanted to own anyway, at a price
            you chose, and you already collected a premium that reduces your effective cost.
          </li>
          <li>
            <strong>Sell covered calls</strong> — Now that you own 100 shares, you sell someone the right to
            buy them from you at a higher price. You collect another premium. If the stock rises above the strike,
            your shares get "called away" (sold), and the cycle completes. If not, the call expires worthless,
            you keep the premium, and sell another call.
          </li>
        </ol>
        <p>
          The cycle then repeats: sell another put, potentially get assigned again, sell calls. Each time
          you collect premium — this is the income. The strategy works best on <strong>stocks you'd be willing
          to own</strong> at prices you're comfortable paying.
        </p>
      </Section>

      <Section title="2. Key Options Concepts">
        <SubSection title="What is a put?">
          <p>
            A <strong>put option</strong> gives the buyer the right (not obligation) to sell 100 shares of a stock
            at a specific price (strike) by a specific date (expiration). When you <em>sell</em> a put, you're
            taking on the <em>obligation</em> to buy those shares if the buyer exercises their right. In exchange,
            you receive a premium.
          </p>
        </SubSection>
        <SubSection title="What is a call?">
          <p>
            A <strong>call option</strong> gives the buyer the right to buy 100 shares at the strike price. When you
            <em> sell</em> a covered call (you already own the shares), you're agreeing to sell them at the strike
            if exercised. You collect a premium for this.
          </p>
        </SubSection>
        <SubSection title="Premium">
          <p>
            The <strong>premium</strong> is the cash you receive when you sell an option. It's yours to keep regardless
            of what happens. Premiums are quoted per share, but each contract covers 100 shares. So a $0.85 premium =
            $85 per contract.
          </p>
        </SubSection>
        <SubSection title="Strike price">
          <p>
            The <strong>strike</strong> is the agreed-upon price for the transaction. For puts, it's the price you'd
            buy the stock at if assigned. For calls, it's the price you'd sell at if called away. Lower put strikes =
            lower assignment probability but less premium. Higher call strikes = less likely to be called away.
          </p>
        </SubSection>
        <SubSection title="Delta">
          <p>
            <strong>Delta</strong> measures how much an option's price changes when the stock moves $1. For our
            purposes, delta roughly approximates the <em>probability of assignment</em>. A put with delta 0.20
            has roughly a 20% chance of being assigned. Investron targets delta 0.15-0.30 — a sweet spot between
            reasonable premium and manageable assignment risk.
          </p>
        </SubSection>
        <SubSection title="DTE (Days to Expiration)">
          <p>
            <strong>DTE</strong> is how many days until the option expires. Investron targets 7-45 days. Shorter
            expirations have faster time decay (premiums shrink faster as expiration approaches), which benefits
            option sellers. Longer expirations offer more premium but tie up capital longer.
          </p>
        </SubSection>
      </Section>

      <Section title="3. How Investron Runs the Wheel">
        <p>
          Every ~60 seconds during market hours, the trading engine runs a cycle for each candidate symbol.
          By default, candidates are pulled dynamically from the screener — filtered by composite score, max price,
          min market cap, and sector diversification limits. Tickers with open positions are always included even if
          they fall off the screener. Here's what happens at each phase:
        </p>
        <SubSection title="Phase 1: Selling puts (IDLE → SELLING_PUTS)">
          <p>For each symbol with no open position:</p>
          <ol className="list-decimal pl-5 space-y-1">
            <li>Check affordability: can we cover 100 shares at the strike price with available cash?</li>
            <li>Fetch the option chain from Alpaca with the configured DTE window (7-45 days)</li>
            <li>Filter contracts by delta (0.15-0.30), yield (4%+), open interest (100+), and bid &gt; 0</li>
            <li>Score remaining candidates: 40% yield + 30% delta proximity + 30% DTE proximity</li>
            <li>Submit a limit sell order for the highest-scoring put</li>
            <li>Reserve cash for potential assignment</li>
          </ol>
        </SubSection>
        <SubSection title="Phase 2: Monitoring puts (SELLING_PUTS)">
          <p>While the put is open, each cycle monitors the position:</p>
          <ul className="list-disc pl-5 space-y-1">
            <li>If the put expires <strong>out-of-the-money</strong> (stock price above strike): the option expires worthless, we keep the premium, and return to idle. This is the ideal outcome — pure income.</li>
            <li>If the put is deep <strong>in-the-money</strong> near expiration (stock dropped significantly): the strategy considers <em>rolling</em> the put (see "Rolling Puts" below).</li>
            <li>If assigned: we now own 100 shares and transition to phase 3.</li>
          </ul>
        </SubSection>
        <SubSection title="Phase 3: Assigned stock (ASSIGNED → SELLING_CALLS)">
          <p>Before selling a call, the strategy runs defensive checks (in order):</p>
          <ol className="list-decimal pl-5 space-y-1">
            <li><strong>Hard stop check</strong> — If the stock has dropped more than 25% from entry, sell immediately (see "Hard Stops" below).</li>
            <li><strong>Capital efficiency check</strong> — If the stock has been held more than 60 days with no recovery, consider exiting (see "Capital Efficiency" below).</li>
            <li><strong>Sell a covered call</strong> — Same option selection logic as puts, but for calls. The minimum strike is based on the <em>adjusted cost basis</em> (see below), not the raw entry price.</li>
          </ol>
        </SubSection>
        <SubSection title="Phase 4: Monitoring calls (SELLING_CALLS)">
          <ul className="list-disc pl-5 space-y-1">
            <li>If the call expires <strong>out-of-the-money</strong>: keep the premium, still hold the stock, sell another call. This generates income while waiting for the stock to recover.</li>
            <li>If the call is exercised (<strong>called away</strong>): shares are sold at the strike price. Cash is credited, the cycle completes, and we return to idle to sell another put.</li>
          </ul>
        </SubSection>
      </Section>

      <Section title="4. Risk Management">
        <p>
          The Wheel's biggest risk is a stock dropping significantly after you're assigned. Professional options
          traders use several techniques to manage this — Investron implements them all automatically.
        </p>
        <SubSection title="Hard stops">
          <p>
            If an assigned stock drops more than <strong>25%</strong> from entry (configurable via{' '}
            <code className="text-xs bg-[var(--muted)] px-1 py-0.5 rounded">max_stock_loss_pct</code>), the strategy
            sells the stock immediately via market order. This prevents the "bagholder" trap — holding a
            deteriorating position hoping it recovers, while capital is stuck and can't be redeployed.
          </p>
          <p>
            The hard stop logs the full breakdown: entry price, exit price, loss percentage, total premiums
            collected on that symbol, and net loss after premiums.
          </p>
        </SubSection>
        <SubSection title="Rolling puts">
          <p>
            When a sold put is deep in-the-money (stock is more than 10% below the strike) with 3 or fewer
            days to expiration, the strategy attempts to <strong>roll</strong> the put:
          </p>
          <ol className="list-decimal pl-5 space-y-1">
            <li>Buy back the current put (buy-to-close)</li>
            <li>Sell a new put at a lower strike and/or later expiration (sell-to-open)</li>
            <li>Only execute if the roll produces a <strong>net credit</strong> of at least $0.10/share</li>
          </ol>
          <p>
            Rolling delays assignment and collects additional premium, improving your position before potentially
            taking the shares. If no profitable roll exists, the strategy lets assignment happen — that's the
            Wheel's natural flow.
          </p>
        </SubSection>
        <SubSection title="Adjusted cost basis">
          <p>
            Your <strong>true break-even</strong> on an assigned stock isn't just the entry (strike) price — it's
            the entry price minus all premiums collected on that symbol. For example:
          </p>
          <div className="card font-mono text-xs whitespace-pre leading-5 bg-[var(--muted)]">
{`Assigned at strike: $22.00 per share ($2,200 for 100 shares)
Put premium collected: $0.85 ($85 total)
First call premium:   $0.60 ($60 total)
Second call premium:  $0.45 ($45 total)
────────────────────────────────
Total premiums:       $1.90 ($190 total)
Adjusted cost basis:  $22.00 - $1.90 = $20.10

Break-even is $20.10, not $22.00`}
          </div>
          <p>
            The strategy uses this adjusted cost basis when setting the minimum call strike — it can sell calls
            slightly below the raw entry price because premiums already offset some of the cost. This is configurable
            via <code className="text-xs bg-[var(--muted)] px-1 py-0.5 rounded">call_min_strike_pct</code> (default: allows strikes up to 5% below adjusted basis).
          </p>
        </SubSection>
        <SubSection title="Capital efficiency exits">
          <p>
            If assigned stock has been held for more than <strong>60 days</strong> (configurable) with no price
            recovery, the position is tying up capital unproductively. The strategy takes action:
          </p>
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>Down more than 15%:</strong> Sell the stock and free the capital for redeployment</li>
            <li><strong>Down 5-15%:</strong> Sell a more aggressive call (closer to at-the-money) to accelerate exit</li>
            <li><strong>Down less than 5%:</strong> Normal call selling continues</li>
          </ul>
          <p>
            The philosophy: don't tie up money in broken positions. Free capital and redeploy it where the
            Wheel can generate income again. Discipline over hope.
          </p>
        </SubSection>
        <SubSection title="PDT (Pattern Day Trader) protection">
          <p>
            Accounts under $25,000 are limited to 3 day trades per rolling 5 business days. A day trade is
            opening and closing the same position on the same calendar day — rolling a put (buy-to-close +
            sell-to-open) counts. The strategy tracks recent round-trip trades and blocks actions that would
            exceed the limit, logging a <code className="text-xs bg-[var(--muted)] px-1 py-0.5 rounded">blocked_pdt_limit</code> event.
          </p>
        </SubSection>
      </Section>

      <Section title="5. Reading the Activity Feed">
        <p>
          The Activity Log tab on the Trading page shows every decision, execution, and restriction.
          Use the <strong>filter pills</strong> at the top to focus on what you care about:
        </p>
        <SubSection title="Decisions (why something was done)">
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>option_selected</strong> — The best option was chosen from the chain. Details include delta, yield, score, and how many candidates were evaluated.</li>
            <li><strong>put_sold / call_sold</strong> — An option sell order was submitted. Details include strike, premium, cash committed, and the reasoning.</li>
            <li><strong>roll_executed</strong> — A put was rolled to a new strike/date. Shows old and new symbols, net credit.</li>
            <li><strong>hard_stop</strong> — Stock was sold due to exceeding the loss threshold. Full P&L breakdown including premiums collected.</li>
            <li><strong>capital_efficiency_exit</strong> — Stock was sold or call strategy adjusted after extended hold with no recovery.</li>
          </ul>
        </SubSection>
        <SubSection title="Executions (what happened)">
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>order_placed / order_filled</strong> — Orders submitted to and filled by Alpaca.</li>
            <li><strong>assignment</strong> — Put was exercised, now holding stock.</li>
            <li><strong>called_away</strong> — Call was exercised, shares sold, wheel cycle complete.</li>
            <li><strong>option_expired</strong> — Option expired worthless (you kept the premium).</li>
            <li><strong>phase_transition</strong> — Symbol moved to a new wheel phase.</li>
          </ul>
        </SubSection>
        <SubSection title="Blocked (what the program wanted to do but couldn't)">
          <p>These are particularly important for understanding system constraints:</p>
          <p className="mt-2 mb-1 font-medium text-sm">Simple Stock:</p>
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>blocked_stop_loss</strong> / <strong>blocked_stop_loss_price_mismatch</strong> — Stop-loss not confirmed on re-fetch, or Alpaca vs yfinance price divergence exceeded 5%.</li>
            <li><strong>blocked_take_profit_price_mismatch</strong> — Take-profit blocked due to price source disagreement.</li>
            <li><strong>blocked_stale_price</strong> — Last trade was too old during market hours (stale data).</li>
            <li><strong>blocked_wide_spread</strong> — Bid/ask spread exceeded 2%, indicating illiquidity or bad data.</li>
          </ul>
          <p className="mt-2 mb-1 font-medium text-sm">Wheel:</p>
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>blocked_insufficient_cash</strong> — Wanted to sell a put but can't afford assignment. Shows how much was needed vs. available.</li>
            <li><strong>blocked_too_expensive</strong> — Ticker's 100 shares exceed total strategy capital.</li>
            <li><strong>blocked_no_options</strong> — No option contracts passed filters. Shows filter breakdown (how many failed each criterion).</li>
            <li><strong>blocked_position_exists</strong> — Already have an open position on this symbol.</li>
            <li><strong>blocked_roll_no_credit</strong> — Wanted to roll a put but couldn't get a net credit.</li>
            <li><strong>blocked_pdt_limit</strong> — Would exceed the 3-per-5-day day trade limit.</li>
          </ul>
        </SubSection>
        <SubSection title="Using date range and detail expansion">
          <ul className="list-disc pl-5 space-y-1">
            <li>Use the <strong>date range picker</strong> to narrow to a specific time period (Today, This Week, This Month, or custom dates).</li>
            <li><strong>Click any event row</strong> to expand it and see the full structured details — reasoning text, numerical breakdowns, filter results.</li>
            <li>The <strong>"reason"</strong> field (shown in italics at the top of expanded details) explains the decision logic in plain English.</li>
            <li>Click <strong>"Load more"</strong> at the bottom to fetch older events from the database.</li>
          </ul>
        </SubSection>
      </Section>

      <Section title="6. Configuration">
        <p>
          The Wheel's behavior is controlled by its JSONB config, which can be edited from the strategy card
          on the Trading page (gear icon → edit config). All values are tunable without code changes.
        </p>
        <SubSection title="Candidate selection">
          <p>
            By default, the Wheel dynamically selects candidates from the screener each cycle. Stocks are filtered
            by minimum composite score (<code className="text-xs bg-[var(--muted)] px-1 py-0.5 rounded">screener_min_score</code>, default 40),
            max price (<code className="text-xs bg-[var(--muted)] px-1 py-0.5 rounded">screener_max_price</code>, default $200),
            min market cap (<code className="text-xs bg-[var(--muted)] px-1 py-0.5 rounded">screener_min_market_cap</code>, default $1B),
            and sector diversification (<code className="text-xs bg-[var(--muted)] px-1 py-0.5 rounded">max_per_sector</code>, default 2).
            Tickers are sorted by price ascending — cheaper stocks get capital first since assignment costs less.
            You can also set <code className="text-xs bg-[var(--muted)] px-1 py-0.5 rounded">screener_enabled: false</code> and
            provide a fixed <code className="text-xs bg-[var(--muted)] px-1 py-0.5 rounded">symbol_list</code> instead.
          </p>
        </SubSection>
        <SubSection title="Option selection parameters">
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>delta_min / delta_max</strong> (0.15-0.30) — Target delta range. Lower delta = less premium but lower assignment probability.</li>
            <li><strong>yield_min / yield_max</strong> (4%-100%) — Annualized premium yield range. Filters out options with too little or suspiciously high yield.</li>
            <li><strong>expiration_min_days / expiration_max_days</strong> (7-45) — DTE window. Shorter = faster time decay (good for sellers), longer = more premium.</li>
            <li><strong>open_interest_min</strong> (100) — Minimum open interest. Ensures enough liquidity for reasonable fills.</li>
          </ul>
        </SubSection>
        <SubSection title="Defensive parameters">
          <ul className="list-disc pl-5 space-y-1">
            <li><strong>max_stock_loss_pct</strong> (25%) — Hard stop threshold. Increase to tolerate more pain; decrease for tighter risk management.</li>
            <li><strong>roll_threshold_pct</strong> (10%) — How deep ITM a put must be before the strategy attempts to roll. Lower = more aggressive rolling.</li>
            <li><strong>roll_min_net_credit</strong> ($0.10) — Minimum net credit required to execute a roll. Prevents rolling at a loss.</li>
            <li><strong>call_min_strike_pct</strong> (-5%) — How far below adjusted cost basis a call strike can be. More negative = more aggressive (risk selling at a loss, but frees capital faster).</li>
            <li><strong>capital_efficiency_days</strong> (60) — How long to hold an underwater stock before escalating exit strategy.</li>
            <li><strong>pdt_protection</strong> (true) — Track day trades to avoid PDT violations. Disable only if your account has &gt; $25,000.</li>
          </ul>
        </SubSection>
      </Section>

      <Section title="7. Frequently Asked Questions">
        <SubSection title="What if a stock crashes after I'm assigned?">
          <p>
            The hard stop at 25% protects against catastrophic loss. Before that threshold, the strategy
            sells covered calls to collect premium, which reduces your effective cost basis. If the stock is
            down but recovering, the Wheel naturally works through it. If it keeps dropping, the hard stop fires
            and the strategy moves on.
          </p>
        </SubSection>
        <SubSection title="How does the Wheel choose which stocks to trade?">
          <p>
            By default, the Wheel pulls candidates dynamically from the screener each cycle — filtered by composite
            score (40+), max price ($200), min market cap ($1B), and sector diversification (max 2 per sector).
            This means the Wheel automatically adapts as stock prices and fundamentals change. You can also disable
            the screener and provide a fixed <code className="text-xs bg-[var(--muted)] px-1 py-0.5 rounded">symbol_list</code> in
            the strategy config if you prefer manual control. Tickers with open positions are always monitored even
            if they fall off the screener.
          </p>
        </SubSection>
        <SubSection title="What if a ticker is too expensive?">
          <p>
            The strategy automatically skips tickers it can't afford to be assigned on (logged as{' '}
            <code className="text-xs bg-[var(--muted)] px-1 py-0.5 rounded">blocked_too_expensive</code> or{' '}
            <code className="text-xs bg-[var(--muted)] px-1 py-0.5 rounded">blocked_insufficient_cash</code>).
            If capital grows large enough or prices drop, they become eligible automatically. No manual intervention needed.
          </p>
        </SubSection>
        <SubSection title="What does 'rolling' actually do?">
          <p>
            Rolling means closing the current option position and opening a new one in a single logical action.
            For a put that's deep in-the-money near expiration: buy back the current put (costs money), then
            sell a new put at a lower strike or later date (receives money). If the new premium exceeds the
            buyback cost, you've collected a net credit and delayed or avoided assignment at a worse price.
          </p>
        </SubSection>
        <SubSection title="How much does the Wheel cost to run?">
          <p>
            The Wheel uses no AI — all decisions are mechanical based on the configured parameters. The only costs
            are Alpaca API calls ($0) and option market data ($0, included with Alpaca). Unlike the Simple Stock
            strategy, the Wheel generates zero GPT-4o costs.
          </p>
        </SubSection>
        <SubSection title="What happens outside market hours?">
          <p>
            The trading engine sleeps during off-hours (nights, weekends, holidays). No orders are placed, no
            monitoring occurs. The engine resumes automatically when the market opens (Mon-Fri, 9 AM - 4 PM ET).
          </p>
        </SubSection>
        <SubSection title="How do I know if the strategy is working?">
          <p>
            Check the <strong>Activity Log</strong> — a healthy Wheel produces a steady stream of events:
            puts sold, premiums collected, occasional assignments and call sales. If you see mostly
            "blocked" events, the capital may be too small for the configured tickers, or the option filters
            may be too tight. If you see "error" events, check the backend logs for details.
          </p>
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
