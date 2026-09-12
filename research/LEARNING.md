# Investron ML — Learning Log

A guided tour of the machine-learning concepts behind this project, tied to the exact
code that implements them. This is the companion to `README.md` (which is the *what/how-to-run*);
this file is the *why, and what you should understand*.

## How to use this

Each phase has three parts:

- **Lessons** — the concept you should be able to explain to someone else afterward.
- **In the code** — clickable links (with line numbers) to where the lesson lives.
- **Check yourself** — questions to test understanding. If you can't answer them, re-read the code.

It's a *living* doc: we fill in phases as we build them. Status legend: ✅ done · 🔨 building · ⬜ planned.

## Roadmap

| Phase | Theme | Status |
|------|-------|--------|
| 0 | Data foundation — capture labeled decisions | ✅ shipped (v0.1.64) |
| 1 | Build the historical training set | ✅ done |
| 2 | Train & evaluate a model | ✅ done (baseline established) |
| 1.5 | Enrich features (value/growth/quality/pre-profit/regime) | 🔨 next |
| 3 | Shadow-mode serving | ⬜ planned |
| 4 | Evaluate & (maybe) promote | ⬜ planned |

---

## Phase 0 — Data foundation ✅

*This shipped in the backend before the research work started. It's the plumbing that makes
everything else possible: capturing each decision with the data that drove it, so outcomes
can be attached later.*

### Lessons

1. **Supervised learning needs (features → label) pairs.** A trade decision is the feature
   vector; the eventual outcome is the label. No captured features = no training data.
2. **Point-in-time correctness.** You must record features *as they were at decision time*.
   The `screener_scores` table overwrites itself each scan, so without a snapshot the past is
   unrecoverable — hence a dedicated `trading_decisions` table + a dated history table.
3. **Look-ahead bias** (the cardinal sin, introduced here, enforced in Phase 1). Anything the
   model sees must have been knowable at time T.
4. **Selection bias — why skips matter.** If you only log *buys*, the model never learns what
   you correctly *avoided*. We log skips as richly as buys.
5. **Label maturation.** The label isn't knowable at decision time — it arrives weeks later.
   A background job computes forward return vs the market and writes the label back.

### In the code

- Decision + feature snapshot table → [schema.sql#L488](../backend/schema.sql#L488)
- Daily feature-store history table → [schema.sql#L523](../backend/schema.sql#L523)
- Log a decision (buy *and* skip) with its feature vector → [trading_db.py#L572](../backend/app/services/trading_db.py#L572)
- Snapshot the screener row at decision time → [trading_db.py#L562](../backend/app/services/trading_db.py#L562)
- Append the daily feature-store row during a scan → [scanner.py#L119](../backend/app/services/scanner.py#L119)
- Maturation job: find matured decisions & write the label back → [simple_stock_strategy.py#L572](../backend/app/services/simple_stock_strategy.py#L572), [trading_db.py#L626](../backend/app/services/trading_db.py#L626), [trading_db.py#L643](../backend/app/services/trading_db.py#L643)

### Check yourself

- Why can't we just read today's `screener_scores` to reconstruct why we bought a stock last month?
- If we only trained on stocks we bought, what would the model systematically fail to learn?
- What's the earliest moment a 3-month label for a decision made today becomes usable?

---

## Phase 1 — Build the historical training set ✅

*File: [build_dataset.py](build_dataset.py). Turns ~10 years of prices into 7k labeled examples.*

### Lessons

1. **Universe selection & survivorship bias.** Our universe is *today's* large-caps, so it
   silently excludes companies that failed — the world looks rosier than it was. A known,
   documented limitation of v1.
2. **Feature engineering, point-in-time.** Momentum (trailing returns), volatility, and
   trend-position features are computed from *backward-looking* rolling windows, then sampled
   at each month-end (`resample("ME").last()` = value as of the last trading day). Past-only
   by construction.
3. **The features-≤-T / labels->-T split** — the concrete mechanism that prevents look-ahead:
   features use `.rolling()` (looks back); labels use `.shift(-h)` (pulls a *future* price
   back to row T). That clean line is the whole game.
4. **Label design: relative vs absolute.** We label "beat SPY over 3 months," not "went up."
   That makes the classes ~50/50, so a do-nothing baseline scores ~50.7% — a hard, honest bar.
   An absolute-return label would look ~65% "accurate" for a useless model.
5. **Data hygiene.** Drop rows with insufficient history (no momentum lookback yet) and
   unmatured labels (recent months whose future isn't known). Verify zero nulls + even
   per-year coverage before trusting anything.
6. **Multi-factor philosophy (design decision).** Rather than hard-coding one investing school
   (classic Graham value), we'll feed value *and* growth *and* quality *and* momentum *and*
   pre-profit/dilution *and* regime-context features, and let the model learn the weighting —
   because markets in 2026 ≠ 1996, accounting understates intangibles, and pre-profit firms
   break P/E. v1 ships price/technical features only; fundamentals get layered in later,
   measured family-by-family against the baseline.

### In the code

- Universe + survivorship caveat → [build_dataset.py#L35](build_dataset.py#L35)
- Price download (split/dividend-adjusted) → [build_dataset.py#L55](build_dataset.py#L55)
- Feature engineering (point-in-time, backward-looking) → [build_dataset.py#L87](build_dataset.py#L87)
- The feature list → [build_dataset.py#L120](build_dataset.py#L120)
- Forward-return labels (`.shift(-h)`, strictly future) → [build_dataset.py#L134](build_dataset.py#L134)
- Cleanup: drop incomplete history / unmatured labels → [build_dataset.py#L171](build_dataset.py#L171)
- Diagnostics you should always eyeball → [build_dataset.py#L187](build_dataset.py#L187)

### Check yourself

- In `build_features`, why is sampling the *last* daily value in each month look-ahead safe,
  but sampling the *mean* of the month would not be for a decision made mid-month?
- Why does `.shift(-3)` on the month-end price series give a *label* and not a *feature*?
- If the "beat market" label were 85% one class instead of ~50%, why would a high accuracy
  score be almost meaningless?
- Which feature families would directly help evaluate a pre-profit company, and why can't
  P/E do that job?

---

## Phase 2 — Train & evaluate a model ✅

*File: [train.py](train.py). Loads `dataset_v1.parquet`, builds up from a dumb baseline to
LightGBM, evaluates honestly, and backtests. The headline finding: **price-only features
carry essentially no signal** for beating the market at 3 months — which is the realistic,
expected result and the whole reason Phase 1.5 (richer features) is next.*

### Lessons

1. **Train/test split by TIME, never random.** Shuffling a time series leaks the future into
   training — the most common way people fool themselves. Train on older years, test on newer.
2. **Baseline first, then complexity.** Fit a majority-class floor and a logistic regression
   before LightGBM so you *feel* the lift (or lack of it) that complexity buys.
3. **Regularization & early stopping earn their keep.** With only ~5k train rows, LightGBM's
   guardrails (shallow trees, subsampling, L2, early stopping) matter. Here early stopping
   halted at **1 tree** — the model *correctly* concluded there was nothing to learn.
4. **Overfitting tell:** strong train metric, weak walk-forward. Watch the gap.
5. **Walk-forward cross-validation** — the time-series-honest stability check.
6. **Metrics that matter here** — AUC (rank quality) and precision@top-decile (we only act on
   the top slice); plain accuracy is weak on a ~50/50 label.
7. **Calibration** — does a predicted "53%" actually happen 53% of the time?
8. **Feature importance** — reading *which* features the model leaned on.
9. **Backtest ≠ accuracy** — turning predictions into a simulated strategy vs SPY, ignoring
   costs (so it's an upper bound). The humbling truth-teller.
10. **Experiment tracking with MLflow** — every run's params/metrics/artifacts logged (optional
    dependency; the script degrades gracefully without it).
11. **Non-stationarity is real and visible** — train beat-rate was 52.7% but test (2023+) was
    46.3%. The world the model trained on differed from the world it was tested on.

### Results (v1 — price-only features, the baseline to beat)

| model | out-of-sample AUC | precision@10% | notes |
|------|------|------|------|
| majority-class | 0.500 | 0.401 | the floor |
| logistic | 0.505 | 0.450 | ~no linear signal |
| LightGBM | 0.467 | 0.392 | stopped at 1 tree = "nothing to learn" |

Walk-forward mean AUC **0.493 ± 0.031** (centered on coin-flip). Backtest (top-decile,
quarterly, out-of-sample 2023+): **strategy ×1.47 vs SPY ×1.84 — LAGGED.**

**The point:** the harness didn't lie to us. A random split would have inflated these numbers;
the time-honest pipeline correctly reported *no edge* from price/technical features alone. That
honest zero is the baseline every future feature family must beat.

### In the code

- Load + feature/label column split → [train.py#L50](train.py#L50)
- **Time-based split (never random)** → [train.py#L59](train.py#L59)
- Metrics: AUC + precision@top-decile → [train.py#L76](train.py#L76)
- Majority-class baseline (the floor) → [train.py#L101](train.py#L101)
- Logistic regression (scaler fit on train only) → [train.py#L112](train.py#L112)
- LightGBM with regularization + early stopping → [train.py#L126](train.py#L126)
- Feature importance → [train.py#L155](train.py#L155)
- Calibration table → [train.py#L166](train.py#L166)
- Walk-forward CV → [train.py#L184](train.py#L184)
- Backtest vs SPY (non-overlapping quarterly) → [train.py#L210](train.py#L210)
- Persist artifact + MLflow tracking → [train.py#L241](train.py#L241)

### Check yourself

- Why is out-of-sample AUC of 0.467 (below 0.5) not a bug, but a sign the price features
  don't generalize to the test years?
- LightGBM early-stopped at 1 tree. In plain terms, what did that tell us — and why is it a
  feature of the process working, not a failure?
- The backtest lagged SPY. Why is reporting that honestly more valuable than tuning params
  until it "wins"?
- Why would a *random* train/test split have made all these numbers look better — and why
  would that have been a lie?

---

## Phase 3 — Shadow-mode serving ⬜

### Lessons (planned)
- Serving a trained artifact from the backend; training/serving skew.
- Shadow evaluation: log predictions against live decisions *without* influencing trades.
- Feature/prediction drift monitoring.

---

## Phase 4 — Evaluate & (maybe) promote ⬜

### Lessons (planned)
- Offline vs online performance; why they diverge.
- Gating a model into the live buy/skip decision, reversibly.
- Retraining cadence and the non-stationarity problem (2026 ≠ 1996, and 2027 ≠ 2026).
