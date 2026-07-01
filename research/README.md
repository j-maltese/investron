# Investron Research (ML)

Offline machine-learning workbench for the Investron trading system. **Nothing here is
deployed** — it runs on your machine to build datasets, train models, and evaluate them.
The trained model artifact is later copied into the backend for shadow-mode serving (Phase 3).

This is a *learn-by-building* project: the code is heavily commented to explain the ML
*why*, not just the *what*. Read the comments.

📚 **Learning?** See [`LEARNING.md`](LEARNING.md) — the concepts to master in each phase,
tied to the exact code that implements them, with "check yourself" questions.

## Why this exists

Investron makes buy/skip decisions whose outcomes become known later — labeled data. But
our own trades are too few to train on, so the training corpus is **market history**: every
stock on every past month is an example (`features as-of T → did it beat the market over the
next 3 months?`). See the full roadmap in `~/.claude/plans/smooth-chasing-cosmos.md`.

## Setup

```bash
cd research
python -m venv .venv
source .venv/Scripts/activate      # Git Bash on Windows;  .venv\Scripts\activate for cmd/PS
pip install -r requirements.txt
```

## Pipeline (phases)

| Phase | File | What it does | Status |
|------|------|--------------|--------|
| 1 | `build_dataset.py` | Download prices → build point-in-time features + forward-return labels → `data/dataset_v1.parquet` | **now** |
| 2 | `train.py` *(next)* | Time-based split, logistic baseline → LightGBM, MLflow tracking, backtest vs SPY | planned |
| 3 | (backend) | Serve the model in shadow mode — log predictions, don't change trades | planned |

Run Phase 1:
```bash
python build_dataset.py           # or step through the "# %%" cells in VS Code
```

## Core concepts this codebase drills into you

- **Point-in-time correctness** — a feature dated T uses only data available at T.
- **Look-ahead bias** — the cardinal sin; features use data ≤ T, labels use data > T.
- **Survivorship bias** — our universe is *today's* large-caps, so it omits companies that
  failed. Noted honestly; a known limitation of v1.
- **Time-ordered splitting** (Phase 2) — never random-shuffle a time series; train on the
  past, test on the future, or the future leaks into training.

## Layout

```
research/
  build_dataset.py     # Phase 1 — dataset builder (cell-script)
  requirements.txt
  data/                # generated Parquet datasets (gitignored)
  mlruns/              # MLflow tracking store (gitignored, Phase 2)
```
