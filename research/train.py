# %% [markdown]
# # Phase 2 — Train & evaluate a model
#
# We have a leak-free dataset (`dataset_v1.parquet`): one row per (ticker, month-end),
# 10 point-in-time features, and a binary label `beat_market` (did it beat SPY over the
# next 3 months?). Now we ask the only question that matters: **is there any signal?**
#
# The honest bar to clear is the label balance — ~50.7%. A model that can't beat "always
# guess the majority class" has learned nothing. We'll build up in order of complexity so
# you feel what each step buys:
#   1. Majority-class baseline   (the floor)
#   2. Logistic regression       (linear signal)
#   3. LightGBM                  (nonlinear + interactions)
# ...then evaluate honestly (AUC, precision@top-decile, calibration), stress-test with
# walk-forward CV, and finally run a backtest — because good classification metrics do
# NOT automatically mean a profitable strategy.
#
# Run: python train.py   (or step through the "# %%" cells in VS Code)
#
# MLflow and matplotlib are OPTIONAL — the script runs without them and just skips
# tracking/plots. Install the full venv (requirements.txt) to get both.

# %%
from pathlib import Path

import numpy as np
import pandas as pd

from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import roc_auc_score, accuracy_score

import lightgbm as lgb

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "dataset_v2.parquet"
MODELS = HERE / "models"

TARGET = "beat_market"
# Columns that are NOT features: identifiers and anything derived from the future (labels).
NON_FEATURES = {"date", "ticker", "beat_market", "fwd_ret_3m", "spy_fwd_ret", "excess_ret"}

# The train/test boundary is a DATE, not a random fraction. See the split lesson below.
SPLIT_DATE = pd.Timestamp("2023-01-01")
TOP_DECILE = 0.10          # we only "act" on the highest-conviction names
BACKTEST_HOLD_M = 3        # holding period = label horizon (non-overlapping rebalances)

# %% [markdown]
# ## 1. Load
# %%
df = pd.read_parquet(DATA).sort_values(["date", "ticker"]).reset_index(drop=True)
FEATURES = [c for c in df.columns if c not in NON_FEATURES]
print(f"{len(df)} rows | {df['ticker'].nunique()} tickers | "
      f"{df['date'].min().date()} -> {df['date'].max().date()}")
print(f"features ({len(FEATURES)}): {FEATURES}")

# %% [markdown]
# ## 2. Split by TIME — never randomly
# The cardinal rule of time-series ML. If you random-shuffle, a June 2020 row lands in
# training while May 2020 sits in test — the model effectively "sees the future" and every
# metric is inflated fantasy. We train only on the PAST and test only on the FUTURE:
# train = everything before 2023, test = 2023 onward. That mimics reality: you can only
# ever learn from what already happened.

# %%
train = df[df["date"] < SPLIT_DATE].copy()
test = df[df["date"] >= SPLIT_DATE].copy()
X_train, y_train = train[FEATURES], train[TARGET]
X_test, y_test = test[FEATURES], test[TARGET]
print(f"train: {len(train)} rows (->{ (SPLIT_DATE - pd.Timedelta(days=1)).date()})   "
      f"test: {len(test)} rows ({SPLIT_DATE.date()}->)")
print(f"train beat-rate {y_train.mean():.1%} | test beat-rate {y_test.mean():.1%}")

# %% [markdown]
# ## 3. Metrics helper
# - **Accuracy** alone is weak (a 51%-majority dataset makes 51% look "okay").
# - **AUC** (area under ROC): probability the model ranks a random winner above a random
#   loser. 0.5 = coin flip, 1.0 = perfect. This is the honest headline number.
# - **Precision@top-decile**: of the names the model is MOST confident about, what fraction
#   actually beat the market? This matches how we'd use it — act on the top slice, ignore
#   the rest. It's the metric closest to money.

# %%
def precision_at_top(y_true: pd.Series, prob: np.ndarray, frac: float) -> float:
    n = max(1, int(len(prob) * frac))
    top_idx = np.argsort(prob)[::-1][:n]          # indices of highest-probability picks
    return float(np.asarray(y_true)[top_idx].mean())

def evaluate(name: str, y_true: pd.Series, prob: np.ndarray) -> dict:
    auc = roc_auc_score(y_true, prob)
    acc = accuracy_score(y_true, (prob >= 0.5).astype(int))
    p_top = precision_at_top(y_true, prob, TOP_DECILE)
    base = float(y_true.mean())
    print(f"  {name:<20} AUC={auc:.3f}  acc={acc:.3f}  "
          f"precision@{int(TOP_DECILE*100)}%={p_top:.3f}  (base rate {base:.3f})")
    return {"model": name, "auc": auc, "accuracy": acc,
            "precision_top_decile": p_top, "base_rate": base}

# %% [markdown]
# ## 4. Model 1 — majority-class baseline (the floor)
# The dumbest possible model: always predict the majority class from the TRAIN set.
# Any real model must beat this, or it's worthless. Its "AUC" is 0.5 by construction.

# %%
print("\n=== models (out-of-sample, test = 2023+) ===")
majority = int(round(y_train.mean()))
base_prob = np.full(len(y_test), y_train.mean())   # constant probability
results = [evaluate(f"majority(={majority})", y_test, base_prob)]

# %% [markdown]
# ## 5. Model 2 — logistic regression (linear signal)
# Scale features first (fit the scaler on TRAIN ONLY — fitting on all data would leak test
# statistics into training). Logistic regression finds the best *linear* combination of
# features. If it beats the baseline, there's linear signal; if LightGBM later beats IT,
# the extra signal is nonlinear / interaction-based.

# %%
logit = make_pipeline(StandardScaler(),
                      LogisticRegression(max_iter=1000, C=1.0))
logit.fit(X_train, y_train)
logit_prob = logit.predict_proba(X_test)[:, 1]
results.append(evaluate("logistic", y_test, logit_prob))

# %% [markdown]
# ## 6. Model 3 — LightGBM (nonlinear + interactions)
# Gradient-boosted trees: the right tool for small/medium tabular data. Params are
# deliberately *regularized* (shallow trees, few leaves, subsampling, L2) because 7k rows
# overfit easily — an unregularized model would memorize the train years and fall apart
# out-of-sample. We carve the last training year off as a validation set for **early
# stopping**: keep adding trees only while validation AUC improves, then stop.

# %%
val_cut = SPLIT_DATE - pd.DateOffset(years=1)      # last train year = validation
fit_mask = train["date"] < val_cut
val_mask = ~fit_mask
gbm = lgb.LGBMClassifier(
    n_estimators=600, learning_rate=0.02,
    num_leaves=15, max_depth=4,                    # shallow = less overfit
    subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
    reg_lambda=1.0, min_child_samples=30,
    random_state=42, n_jobs=-1, verbose=-1,
)
gbm.fit(
    X_train[fit_mask], y_train[fit_mask],
    eval_set=[(X_train[val_mask], y_train[val_mask])],
    eval_metric="auc",
    callbacks=[lgb.early_stopping(50, verbose=False)],
)
gbm_prob = gbm.predict_proba(X_test)[:, 1]
results.append(evaluate("lightgbm", y_test, gbm_prob))
print(f"  (lightgbm stopped at {gbm.best_iteration_} trees)")

# %% [markdown]
# ## 7. Feature importance
# Which features did LightGBM actually lean on? This is how you *read* the model — and
# later, how you'll watch factor weights shift across regimes as we add fundamentals.

# %%
imp = (pd.Series(gbm.feature_importances_, index=FEATURES)
       .sort_values(ascending=False))
print("\nfeature importance (LightGBM split gain):")
print(imp.to_string())

# %% [markdown]
# ## 8. Calibration — are the probabilities honest?
# A model can rank well (good AUC) yet output miscalibrated probabilities. If we bucket
# predictions into deciles, the average predicted probability in each bucket should match
# the actual beat-rate in that bucket. Big gaps = the "70%" doesn't mean 70%. This matters
# a lot before a probability is allowed to size a position.

# %%
def calibration_table(y_true: pd.Series, prob: np.ndarray, bins: int = 10) -> pd.DataFrame:
    d = pd.DataFrame({"y": np.asarray(y_true), "p": prob})
    d["bucket"] = pd.qcut(d["p"], q=bins, duplicates="drop")
    tbl = d.groupby("bucket", observed=True).agg(
        n=("y", "size"), predicted=("p", "mean"), actual=("y", "mean"))
    return tbl

print("\ncalibration (LightGBM, test set):")
print(calibration_table(y_test, gbm_prob).round(3).to_string())

# %% [markdown]
# ## 9. Walk-forward cross-validation
# A single train/test split can be lucky. Walk-forward is the time-series-honest way to
# estimate stability: expand the training window one year at a time and test on the next
# year. Consistent AUC across folds = trustworthy; wild swings = fragile.

# %%
print("\nwalk-forward CV (train on all prior years, test on each year):")
years = sorted(df["date"].dt.year.unique())
wf_aucs = []
for ty in years:
    tr = df[df["date"].dt.year < ty]
    te = df[df["date"].dt.year == ty]
    if len(tr) < 500 or te[TARGET].nunique() < 2:   # need history + both classes
        continue
    m = lgb.LGBMClassifier(
        n_estimators=300, learning_rate=0.02, num_leaves=15, max_depth=4,
        subsample=0.8, subsample_freq=1, colsample_bytree=0.8,
        reg_lambda=1.0, min_child_samples=30, random_state=42, n_jobs=-1, verbose=-1)
    m.fit(tr[FEATURES], tr[TARGET])
    a = roc_auc_score(te[TARGET], m.predict_proba(te[FEATURES])[:, 1])
    wf_aucs.append(a)
    print(f"  test {ty}: AUC={a:.3f}  (n={len(te)})")
if wf_aucs:
    print(f"  mean AUC {np.mean(wf_aucs):.3f} +/- {np.std(wf_aucs):.3f}")

# %% [markdown]
# ## 10. Backtest — does the signal make money?
# The reality check. Good AUC ≠ profit. We rebalance every 3 months (non-overlapping, so
# returns compound cleanly), each time buying the top-decile names by predicted probability,
# equal-weighted, and holding for the 3-month horizon. We compare the compounded equity
# curve to simply holding SPY over the same dates.
#
# Honest caveats baked in: out-of-sample only (test period), and we IGNORE transaction
# costs/slippage — so treat the number as an upper bound, not a promise.

# %%
bt = test[["date", "ticker", "fwd_ret_3m", "spy_fwd_ret"]].copy()
bt["prob"] = gbm_prob
rebal_dates = sorted(bt["date"].unique())[::BACKTEST_HOLD_M]   # every 3rd month-end
strat_eq, mkt_eq = 1.0, 1.0
print("\nbacktest (top-decile, quarterly rebalance, out-of-sample):")
for d in rebal_dates:
    day = bt[bt["date"] == d]
    if len(day) < 10:
        continue
    n = max(1, int(len(day) * TOP_DECILE))
    picks = day.nlargest(n, "prob")
    strat_ret = picks["fwd_ret_3m"].mean()
    mkt_ret = day["spy_fwd_ret"].iloc[0]
    strat_eq *= (1 + strat_ret)
    mkt_eq *= (1 + mkt_ret)
    print(f"  {pd.Timestamp(d).date()}  picks={n:2d}  "
          f"strat={strat_ret:+.2%}  spy={mkt_ret:+.2%}")
print(f"\n  cumulative  strategy x{strat_eq:.2f}   |   SPY x{mkt_eq:.2f}")
print(f"  strategy {'BEAT' if strat_eq > mkt_eq else 'LAGGED'} the market over the test window")

# %% [markdown]
# ## 11. Persist the model + track the run
# Save the trained LightGBM artifact for Phase 3 (shadow serving). Log the run to MLflow if
# it's installed — params, metrics, and the model — so experiments are comparable over time.
# (`mlflow ui` from research/ opens the dashboard.) Missing MLflow just skips this gracefully.

# %%
MODELS.mkdir(parents=True, exist_ok=True)
import joblib
artifact = MODELS / "lgbm_v2.pkl"
joblib.dump({"model": gbm, "features": FEATURES, "split_date": str(SPLIT_DATE)}, artifact)
print(f"\nsaved model -> {artifact}")

try:
    import mlflow
    mlflow.set_tracking_uri(f"file:{(HERE / 'mlruns').as_posix()}")
    mlflow.set_experiment("simple_stock_beat_market")
    with mlflow.start_run(run_name="lgbm_v2"):
        mlflow.log_params({
            "features": len(FEATURES), "split_date": str(SPLIT_DATE.date()),
            "n_estimators": gbm.best_iteration_, "learning_rate": 0.02,
            "num_leaves": 15, "max_depth": 4})
        gbm_row = next(r for r in results if r["model"] == "lightgbm")
        mlflow.log_metrics({
            "auc": gbm_row["auc"], "precision_top_decile": gbm_row["precision_top_decile"],
            "wf_auc_mean": float(np.mean(wf_aucs)) if wf_aucs else 0.0,
            "backtest_strategy_mult": strat_eq, "backtest_spy_mult": mkt_eq})
        mlflow.log_artifact(str(artifact))
    print("logged run to MLflow (run `mlflow ui` in research/ to view)")
except ImportError:
    print("mlflow not installed - skipped tracking (install requirements.txt to enable)")

# %% [markdown]
# ## What to take away
# - AUC just above 0.5 is NORMAL and even useful in finance — markets are near-efficient, so
#   a small, *consistent* edge (especially in the top decile) is the realistic prize. Don't
#   expect 0.9.
# - Watch for the tell-tale overfit gap: strong train metrics, weak walk-forward.
# - The backtest is the humbling truth-teller. If the strategy lags SPY, the honest move is
#   to say so — and that's exactly why the next step is richer features (Phase 1.5: value +
#   growth + quality + pre-profit + regime context), measured against THIS baseline.
