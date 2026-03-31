# Buffett Scorecard

The **Buffett Scorecard** is a dashboard card that evaluates any publicly traded stock against Warren Buffett's four investing rules, as documented and taught at [BuffettsBooks.com](https://www.buffettsbooks.com). It is not a buy/sell signal generator — it is a structured framework for fundamental due diligence that surfaces the quantitative data behind each rule so you can make an informed judgment.

---

## How to Use It

1. Click the ticker selector in the top-right of the card and type a ticker symbol or company name.
2. The card loads data for all four rules automatically (cached for 15 minutes).
3. Use the hamburger menu on the Dashboard to show or hide the card.
4. Drag the grip handle at the bottom to resize the card.
5. The last selected ticker is saved in your browser so it persists across page reloads.

---

## Rule 1 — Vigilant Leadership

> *"Invest in companies with vigilant leaders who use company profits wisely."*

Rule 1 evaluates current financial health and management discipline via three quantitative metrics and one contextual indicator.

### Metrics

#### Debt-to-Equity Ratio (D/E)

| Field | Details |
|-------|---------|
| **Source** | `yfinance` → `debtToEquity` field |
| **Units** | yfinance returns this as a percentage (e.g., `42.3` = a ratio of 0.423). The card divides by 100 to display as a ratio (e.g., `0.42x`). |
| **Formula** | `Total Long-Term Debt ÷ Shareholders' Equity` |
| **Buffett Threshold** | < 0.50x (pass), 0.50x–1.00x (borderline), ≥ 1.00x (fail) |
| **Why it matters** | Companies with low debt survive economic recessions and don't divert profits to interest payments. |

**Note on negative equity:** If D/E is negative (e.g., McDonald's, Starbucks — companies that have repurchased more stock than their book equity), the card flags `negative_equity = true`. Rule 4 is automatically marked inapplicable in this case since the BV DCF formula requires positive book value.

**Note on financial sector:** Banks, insurance companies, and other financial sector firms operate with structurally high leverage by design (deposits are liabilities; loans are assets). A warning banner is shown for these companies and D/E thresholds should not be applied.

---

#### Current Ratio

| Field | Details |
|-------|---------|
| **Source** | `yfinance` → `currentRatio` field |
| **Units** | Ratio (e.g., `1.80x`) |
| **Formula** | `Current Assets ÷ Current Liabilities` |
| **Buffett Threshold** | > 1.50x (pass), 1.00x–1.50x (borderline), < 1.00x (fail) |
| **Why it matters** | A ratio above 1.0 means the company can cover all short-term obligations without taking on new debt. Buffett wants management that keeps the balance sheet clean. |

---

#### Return on Equity (ROE)

| Field | Details |
|-------|---------|
| **Source** | `yfinance` → `returnOnEquity` field |
| **Units** | Decimal (e.g., `0.184` = 18.4%). Displayed as a percentage. |
| **Formula** | `Net Income ÷ Shareholders' Equity` |
| **Buffett Threshold** | > 15% (pass), 10%–15% (borderline), < 10% (fail) |
| **Why it matters** | ROE measures how efficiently management converts shareholder equity into profit. A consistently high ROE (above 15%) is a hallmark of durable competitive advantage — the company isn't just lucky, it repeatedly earns high returns. |

---

#### Price-to-Book Ratio (P/B)

| Field | Details |
|-------|---------|
| **Source** | `yfinance` → `priceToBook` field |
| **Units** | Ratio (e.g., `2.1x`) |
| **Formula** | `Market Price per Share ÷ Book Value per Share` |
| **Threshold** | Context only — no pass/fail |
| **Why it matters** | Shows the premium the market is paying over the company's net asset value. A high P/B may mean the market has already priced in future growth, leaving less margin of safety. A P/B near 1.0 means you're paying close to liquidation value. |

### Rule 1 Overall Score
- **PASS** — all three threshold metrics pass (or are N/A)
- **MIXED** — at least one borderline, none hard-failed
- **FAIL** — any metric is a hard fail (negative equity counts as fail)

---

## Rule 2 — Long-Term Prospects

> *"Invest in companies with long-term prospects — ones whose products will still be needed in 20–30 years."*

Rule 2 is informational rather than pass/fail. It shows the historical trajectory of earnings and revenue, and provides an on-demand AI durability analysis.

### Metrics

#### EPS (Diluted) History

| Field | Details |
|-------|---------|
| **Source** | EDGAR annual income statements via the platform's `get_financial_statements` endpoint |
| **Field used** | `eps_diluted` (falls back to `eps_basic` if diluted is unavailable) |
| **Units** | Dollars per share |
| **Chart** | Sparkline showing each fiscal year. X-axis shows the first and last year of available data. Hover to see the exact value for each year. |

**Consecutive Positive EPS Years** — the number of consecutive fiscal years at the end of the series where EPS was positive. A long streak (7–10+ years) is a strong signal of consistent profitability.

**EPS CAGR (Compound Annual Growth Rate)**

```
EPS CAGR = (EPS_latest / EPS_oldest) ^ (1 / (years - 1)) − 1
```

Where `years` is the number of data points in the history. A positive CAGR shows earnings are growing over time; negative shows decline.

---

#### Revenue History

| Field | Details |
|-------|---------|
| **Source** | EDGAR annual income statements |
| **Field used** | `revenue` (total net revenue / net sales) |
| **Units** | Billions of dollars (raw value ÷ 1,000,000,000) |
| **Chart** | Sparkline per fiscal year. Hover value shows `$XB`. |

**Revenue CAGR**

```
Revenue CAGR = (Revenue_latest / Revenue_oldest) ^ (1 / (years - 1)) − 1
```

---

#### AI Durability Analysis (On-Demand)

Click **Analyze** to trigger a streaming AI analysis using a reasoning model. The analysis assesses:

1. Will this product or service still exist and be in demand in 20–30 years?
2. Is the business model understandable and predictable?
3. What are the key long-term durability risks (competitive, regulatory, technological disruption)?

The AI is provided the company's sector, industry, financial history, and has access to a search of recent news headlines. This call is expensive and is never triggered automatically.

---

## Rule 3 — Stable & Understandable

> *"Invest in companies that are stable and understandable — whose financials are consistent and predictable over time."*

Rule 3 evaluates multi-year trends using historical data from EDGAR filings. All four charts are annual, one data point per fiscal year.

### Metrics

All four metrics are sourced from **EDGAR annual balance sheet and income statement filings** via the platform's `get_financial_statements` endpoint. The number of available years varies by company and EDGAR coverage (typically 5–10 years).

#### Book Value per Share (BV/Share)

| Field | Details |
|-------|---------|
| **Source** | EDGAR annual balance sheet |
| **Formula** | `Stockholders' Equity ÷ Shares Outstanding` |
| **Units** | Dollars per share |
| **Good direction** | Increasing year-over-year |
| **Why it matters** | BV/share represents what each share would be worth if the company were liquidated today. Steadily growing BV means the company is retaining and compounding value over time. This is also the foundation of the Rule 4 intrinsic value formula. |

---

#### D/E Ratio History

| Field | Details |
|-------|---------|
| **Source** | EDGAR annual balance sheet |
| **Formula** | `Long-Term Debt ÷ Stockholders' Equity` (ratio form, not %) |
| **Units** | Ratio (e.g., `0.42x`) |
| **Good direction** | Declining or stable |
| **Note** | This uses the raw ratio, unlike the Rule 1 D/E which comes from yfinance in percentage form. The values should be consistent but may differ slightly due to rounding and EDGAR vs. yfinance field definitions. |

---

#### EPS Trend

| Field | Details |
|-------|---------|
| **Source** | EDGAR annual income statements |
| **Field used** | `eps_diluted` (same as Rule 2) |
| **Units** | Dollars per share |
| **Good direction** | Increasing year-over-year |

---

#### ROE Trend

| Field | Details |
|-------|---------|
| **Source** | EDGAR annual income statements + balance sheet (joined by fiscal year) |
| **Formula** | `Net Income ÷ Stockholders' Equity` (decimal form) |
| **Units** | Percentage (e.g., `18%`) |
| **Good direction** | Stable or increasing; consistently above 15% is ideal |
| **Why it matters** | Consistent ROE over many years is a hallmark of durable moat. A company earning 20%+ ROE year after year is not getting lucky — it has a structural advantage. |

### Rule 3 Overall Score
Each metric's trend is classified as `up`, `flat`, or `down` based on first vs. last value (>5% change = directional):

| Metric | Good outcome |
|--------|-------------|
| BV/Share | up |
| D/E | flat or down |
| EPS | up |
| ROE | flat or up |

- **PASS** — all four trends in the good direction
- **MIXED** — 2–3 of 4 trending well
- **FAIL** — fewer than 2 trending well
- **N/A** — fewer than 3 years of EDGAR data available

---

## Rule 4 — Intrinsic Value

> *"Invest only when the stock is trading below its intrinsic value."*

Rule 4 computes an intrinsic value (IV) using the BuffettsBooks.com Book Value DCF methodology and compares it to the current market price. The formula has two components: the present value of future book value and the present value of dividend income over 10 years.

### When Rule 4 Is Inapplicable

Rule 4 cannot be computed when:
- **Negative equity** — BV growth formula requires positive book value (BV cannot be negative or zero)
- **Insufficient history** — fewer than 3 years of EDGAR balance sheet data (can't compute a reliable BV growth rate)

In these cases, an **AI Valuation Analysis** is offered as an alternative (see below).

### Inputs

#### Current Book Value per Share (BV)

| Field | Details |
|-------|---------|
| **Source** | `yfinance` → `bookValue` field |
| **Units** | Dollars per share |

---

#### Oldest Book Value per Share

| Field | Details |
|-------|---------|
| **Source** | Earliest data point in the EDGAR balance sheet history (same calculation as Rule 3 BV/Share) |
| **Formula** | `Stockholders' Equity ÷ Shares Outstanding` at the oldest available fiscal year |
| **Units** | Dollars per share |

---

#### BV Growth Rate (annualized)

```
BV Growth Rate = (Current BV / Oldest BV) ^ (1 / Years Between) − 1
```

Where `Years Between` is the number of years between the oldest and most recent BV data points. This is the single most important input to the formula — it determines how fast book value is expected to grow for the next 10 years.

**High growth warning:** If the BV growth rate exceeds 20%/year, the card shows a warning. The stability assumption behind the DCF (that past growth rate continues for 10 years) is less reliable for high-growth companies.

---

#### Annual Dividend per Share

| Field | Details |
|-------|---------|
| **Primary source** | `yfinance` → `dividendRate` — the annualized cash dividend in dollars per share |
| **Fallback** | `Current Price × dividendYield` if `dividendRate` is unavailable |
| **No dividend** | If neither is available, `annual_dividend = 0`. Rule 4 is still valid — the PV of dividends term is simply $0.00. |
| **Units** | Dollars per share per year |

The **Dividend Yield** is also displayed for context: `dividendYield` from yfinance, shown as a percentage.

---

#### 10-Year Treasury Rate

| Field | Details |
|-------|---------|
| **Source** | `yfinance` → `^TNX` ticker → `regularMarketPrice / 100` |
| **Cache** | 24 hours (treasury rate changes slowly) |
| **Units** | Decimal (e.g., `0.0434` = 4.34%) |
| **Floor** | Clamped to a minimum of 0.001 (0.1%) to prevent division by zero |

The treasury rate represents the **risk-free rate** — what your money could earn in a safe U.S. government bond. Buffett uses this as the discount rate because any investment should beat the risk-free alternative.

**You can override the rate** using the input field in the card. The intrinsic value recalculates instantly in your browser without a server call. This lets you model what happens to IV under different rate environments.

---

### Intrinsic Value Formula

**Step 1 — Project book value 10 years forward:**
```
BV_future = Current BV × (1 + BV Growth Rate) ^ 10
```

**Step 2 — Discount projected BV back to present value:**
```
PV_of_BV = BV_future / (1 + Treasury Rate) ^ 10
```

**Step 3 — Present value of dividend annuity over 10 years:**
```
PV_of_divs = Annual Dividend × [1 − (1 + Treasury Rate) ^ −10] / Treasury Rate
```

**Step 4 — Intrinsic Value:**
```
IV = PV_of_BV + PV_of_divs
```

---

### Margin of Safety

```
Margin of Safety = (IV − Current Price) / Current Price × 100
```

| Outcome | Badge |
|---------|-------|
| ≥ 15% | UNDERVALUED (green) |
| 0% to 15% | NEAR IV (amber) |
| < 0% | OVERVALUED (red) |

Buffett typically requires at least 15–25% margin of safety to account for estimation error in the growth rate. A positive margin of safety does not guarantee a good investment — it means the stock *may* be trading below estimated intrinsic value under the assumptions of this model.

**Rule 4 Overall Score:** PASS if IV > Current Price, FAIL if IV < Current Price, N/A if inapplicable.

---

## Option B — AI Valuation Analysis

When Rule 4 is inapplicable (negative equity, insufficient EDGAR history), the card offers an AI-powered alternative valuation. This uses a reasoning model (o4-mini) with access to:

- All four rules' computed data (sector, industry, metrics)
- Analyst consensus (mean price target, buy/hold/sell rating, number of analysts)
- Recent news headlines from a live search
- Excerpts from the most recent 10-K and 10-Q filings via semantic search (RAG)

### Filing Indexing

SEC filings must be indexed (embedded into a vector database) before the AI can search them. The card handles this automatically:

1. **Check** — if the ticker is already indexed, proceed directly to streaming
2. **Index** — if not indexed, trigger indexing automatically and show an animated progress indicator
3. **Stream** — once indexed, stream the AI response token-by-token

Indexing typically takes 30–90 seconds for a new ticker. The status message in the card shows what's happening at each phase.

### What the AI Produces

The AI classifies the company into one of three categories and tailors the analysis accordingly:

| Category | Description | Methodology used |
|----------|-------------|-----------------|
| **A — Mature** | Positive consistent EPS, stable revenue | DCF on earnings, comparable multiples, dividend yield |
| **B — Growth** | Growing revenue, EPS not yet stable | Revenue multiple, growth-adjusted P/E, path to profitability |
| **C — Pre-Profitable** | Negative or erratic EPS | Capital runway, burn rate analysis, milestone-based framework |

For Category C companies, the AI explicitly addresses:
- Cash on hand vs. quarterly burn rate
- How many quarters of runway remain at the current burn rate
- What milestones need to be achieved to reach profitability
- Key risks that could cause the company to fail

The output includes bear/base/bull scenario analysis (or equivalent framework for the company type) with specific price targets and the reasoning behind each scenario.

---

## Data Sources Summary

| Data Point | Source | Refresh / Cache |
|-----------|--------|----------------|
| D/E Ratio | yfinance `debtToEquity` | Per page load |
| Current Ratio | yfinance `currentRatio` | Per page load |
| ROE (current) | yfinance `returnOnEquity` | Per page load |
| P/B Ratio | yfinance `priceToBook` | Per page load |
| Book Value/Share (current) | yfinance `bookValue` | Per page load |
| Annual Dividend | yfinance `dividendRate` | Per page load |
| Dividend Yield | yfinance `dividendYield` | Per page load |
| Sector / Industry | yfinance `sector`, `industry` | Per page load |
| Current Price | yfinance `regularMarketPrice` | Per page load |
| 10Y Treasury Rate | yfinance `^TNX` | 24 hours |
| EPS history | EDGAR annual income statements | 15 minutes |
| Revenue history | EDGAR annual income statements | 15 minutes |
| BV/Share history | EDGAR annual balance sheets | 15 minutes |
| D/E history | EDGAR annual balance sheets | 15 minutes |
| ROE history | EDGAR income + balance sheets | 15 minutes |
| Analyst consensus | yfinance `targetMeanPrice`, `recommendationKey`, etc. | Per page load |
| News headlines | Serper API (Google search) | Live (per AI request) |
| Filing excerpts (RAG) | EDGAR via pgvector semantic search | Indexed on demand |

---

## Known Limitations

- **Negative equity companies** (MCD, SBUX, etc.): These companies have repurchased so much stock that book equity is negative. Rule 4's BV DCF is mathematically inapplicable. Use the AI Valuation (Option B) instead.
- **Financial sector companies** (banks, insurers): Their balance sheets are structured differently. D/E thresholds don't apply. Rule 3 and Rule 4 may still be computed but should be interpreted with caution.
- **Stock splits**: A historical BV/share series may show a discontinuity around a split date. The growth rate calculation may be distorted if the oldest data point predates a major split.
- **< 3 years of EDGAR data**: New public companies or those with limited EDGAR history will show N/A for Rule 3 and Rule 4.
- **BV growth > 20%/yr**: The DCF assumes a stable, predictable growth rate extending 10 years. A 20%+ rate typically belongs to high-growth companies where this assumption breaks down. The card flags this with a warning.
- **Model risk**: Rule 4's intrinsic value is a model output based on historical BV growth and a single discount rate. It is not a prediction — actual returns depend on future performance, which the model cannot know.

---

## Methodology Reference

The Rule 4 intrinsic value formula follows the methodology documented at [BuffettsBooks.com](https://www.buffettsbooks.com/how-to-invest-in-stocks/part-3/lesson-20/) — specifically the Book Value and Dividend DCF approach used in their Rule 4 calculator.