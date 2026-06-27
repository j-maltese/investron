"""Tests for the ML feedback loop (Phase 0).

Covers the two pieces with real logic:

  * ``_mature_decision_labels`` (simple_stock_strategy) — converts a pending
    decision into a labeled example: forward return vs SPY over the same window,
    excess return, and the beat_market classification target. Edge cases: no
    pending work, missing anchor price (→ 'skipped'), transient price gap
    (→ left 'pending'), and a missing benchmark (→ raw return only, label null).
  * ``log_decision`` (trading_db) — derives decision_price and screener_score
    from the feature vector so the maturation job has a consistent anchor.

DB and yfinance access are mocked — no Postgres or network needed.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import simple_stock_strategy, trading_db


# ---------------------------------------------------------------------------
# _mature_decision_labels
# ---------------------------------------------------------------------------

CONFIG = {"ml_label_horizon_days": 30}


def _prices(mapping):
    """Build an AsyncMock for get_quick_price backed by a ticker→price dict."""
    return AsyncMock(side_effect=lambda ticker: mapping.get(ticker))


async def test_no_pending_is_noop():
    with patch.object(simple_stock_strategy, "trading_db") as td, \
         patch.object(simple_stock_strategy, "get_quick_price", new=AsyncMock()) as gp:
        td.get_pending_matured_decisions = AsyncMock(return_value=[])
        td.update_decision_label = AsyncMock()

        await simple_stock_strategy._mature_decision_labels(MagicMock(), CONFIG)

        td.update_decision_label.assert_not_awaited()
        gp.assert_not_awaited()  # returns before fetching the benchmark


async def test_missing_anchor_price_is_skipped():
    pending = [{"id": 7, "ticker": "AAA", "decision_price": None, "benchmark_price": 400.0}]
    with patch.object(simple_stock_strategy, "trading_db") as td, \
         patch.object(simple_stock_strategy, "get_quick_price", new=_prices({"SPY": 420.0})):
        td.get_pending_matured_decisions = AsyncMock(return_value=pending)
        td.update_decision_label = AsyncMock()

        await simple_stock_strategy._mature_decision_labels(MagicMock(), CONFIG)

        td.update_decision_label.assert_awaited_once()
        _, kwargs = td.update_decision_label.await_args
        assert kwargs["label_status"] == "skipped"


async def test_transient_forward_price_gap_left_pending():
    # Forward price unavailable for the ticker → leave the row pending (no update).
    pending = [{"id": 1, "ticker": "AAA", "decision_price": 100.0, "benchmark_price": 400.0}]
    with patch.object(simple_stock_strategy, "trading_db") as td, \
         patch.object(simple_stock_strategy, "get_quick_price", new=_prices({"SPY": 420.0})):
        td.get_pending_matured_decisions = AsyncMock(return_value=pending)
        td.update_decision_label = AsyncMock()

        await simple_stock_strategy._mature_decision_labels(MagicMock(), CONFIG)

        td.update_decision_label.assert_not_awaited()


async def test_beats_market_label_true():
    # Stock +10% (100→110), SPY +5% (400→420) → excess +5% → beat_market True.
    pending = [{"id": 1, "ticker": "AAA", "decision_price": 100.0, "benchmark_price": 400.0}]
    with patch.object(simple_stock_strategy, "trading_db") as td, \
         patch.object(simple_stock_strategy, "get_quick_price",
                      new=_prices({"SPY": 420.0, "AAA": 110.0})):
        td.get_pending_matured_decisions = AsyncMock(return_value=pending)
        td.update_decision_label = AsyncMock()

        await simple_stock_strategy._mature_decision_labels(MagicMock(), CONFIG)

        _, kwargs = td.update_decision_label.await_args
        assert kwargs["forward_return_pct"] == pytest.approx(10.0, abs=1e-6)
        assert kwargs["benchmark_return_pct"] == pytest.approx(5.0, abs=1e-6)
        assert kwargs["excess_return_pct"] == pytest.approx(5.0, abs=1e-6)
        assert kwargs["beat_market"] is True


async def test_beats_market_label_false_when_underperforms():
    # Stock +2% (100→102), SPY +5% (400→420) → excess -3% → beat_market False.
    pending = [{"id": 2, "ticker": "BBB", "decision_price": 100.0, "benchmark_price": 400.0}]
    with patch.object(simple_stock_strategy, "trading_db") as td, \
         patch.object(simple_stock_strategy, "get_quick_price",
                      new=_prices({"SPY": 420.0, "BBB": 102.0})):
        td.get_pending_matured_decisions = AsyncMock(return_value=pending)
        td.update_decision_label = AsyncMock()

        await simple_stock_strategy._mature_decision_labels(MagicMock(), CONFIG)

        _, kwargs = td.update_decision_label.await_args
        assert kwargs["excess_return_pct"] == pytest.approx(-3.0, abs=1e-6)
        assert kwargs["beat_market"] is False


async def test_missing_benchmark_still_matures_with_null_label():
    # No benchmark anchor → forward return is recorded, but the relative label is null.
    pending = [{"id": 3, "ticker": "CCC", "decision_price": 50.0, "benchmark_price": None}]
    with patch.object(simple_stock_strategy, "trading_db") as td, \
         patch.object(simple_stock_strategy, "get_quick_price",
                      new=_prices({"SPY": 420.0, "CCC": 55.0})):
        td.get_pending_matured_decisions = AsyncMock(return_value=pending)
        td.update_decision_label = AsyncMock()

        await simple_stock_strategy._mature_decision_labels(MagicMock(), CONFIG)

        _, kwargs = td.update_decision_label.await_args
        assert kwargs["forward_return_pct"] == pytest.approx(10.0, abs=1e-6)
        assert kwargs["benchmark_return_pct"] is None
        assert kwargs["excess_return_pct"] is None
        assert kwargs["beat_market"] is None


# ---------------------------------------------------------------------------
# log_decision — feature-vector anchor extraction
# ---------------------------------------------------------------------------


async def test_log_decision_derives_anchor_from_features():
    features = {"price": 123.45, "composite_score": 77.0, "pe_ratio": 12.3}
    db = MagicMock()
    db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=42)))
    db.commit = AsyncMock()

    decision_id = await trading_db.log_decision(
        db, "simple_stock", "AAA", "buy", features,
        ai_signal={"action": "buy", "confidence": 0.8},
        horizon_days=30, benchmark_price=400.0,
    )

    assert decision_id == 42
    params = db.execute.await_args.args[1]
    assert params["decision_price"] == 123.45      # pulled from features["price"]
    assert params["screener_score"] == 77.0        # pulled from features["composite_score"]
    assert params["benchmark_price"] == 400.0
    assert params["horizon_days"] == 30
    assert params["action"] == "buy"


def test_json_default_coerces_decimal_and_datetime():
    from decimal import Decimal
    from datetime import datetime, timezone

    assert trading_db._json_default(Decimal("1.5")) == 1.5
    assert isinstance(trading_db._json_default(Decimal("1.5")), float)
    dt = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone.utc)
    assert trading_db._json_default(dt) == dt.isoformat()