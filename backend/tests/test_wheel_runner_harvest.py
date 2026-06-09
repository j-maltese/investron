"""Tests for the Wheel runner-harvest features (Levers A + B + the BS proxy).

Covers the three hardening pieces that let the Wheel exit / protect a position
that has run far above its basis (the TMHC problem):

  * ``_is_runner`` — the gate that classifies a deeply-appreciated position.
  * ``_estimate_delta`` — Black-Scholes |delta| fallback that replaced the
    mis-scaled moneyness proxy when Alpaca omits greeks.
  * ``_select_best_option`` with ``delta_max_override`` — the mechanism Lever A
    relies on to write a near-the-money call on a runner (relaxed ceiling +
    OTM-only floor).
  * ``_check_trailing_stop`` — Lever B's peak-based trailing stop.

Pure helpers are tested directly; ``_check_trailing_stop`` mocks the DB session,
``trading_db`` helpers, ``alpaca_client``, and ``_get_adjusted_cost_basis`` so no
Postgres or Alpaca access is needed.
"""

from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import wheel_strategy, alpaca_client


# Baseline wheel config used across the option-selection tests.
BASE_CONFIG = {
    "delta_min": 0.15,
    "delta_max": 0.30,
    "yield_min": 0.04,
    "yield_max": 1.00,
    "expiration_min_days": 7,
    "expiration_max_days": 45,
    "open_interest_min": 0,        # no OI data on test contracts → skip the check
    "runner_gain_pct": 20.0,
    "delta_max_runner": 0.60,
    "trailing_stop_enabled": True,
    "trailing_stop_pct": 10.0,
}


# ---------------------------------------------------------------------------
# _is_runner
# ---------------------------------------------------------------------------


def test_is_runner_true_above_threshold():
    # TMHC: adj basis 54.55, current 71.46 → +31% > 20% threshold.
    assert wheel_strategy._is_runner(71.46, 54.55, BASE_CONFIG) is True


def test_is_runner_false_near_basis():
    # Only +10% over basis — below the 20% runner threshold.
    assert wheel_strategy._is_runner(55.0, 50.0, BASE_CONFIG) is False


def test_is_runner_exactly_at_threshold_is_runner():
    # current == basis * 1.20 → boundary counts as a runner (>=).
    assert wheel_strategy._is_runner(60.0, 50.0, BASE_CONFIG) is True


def test_is_runner_false_on_bad_basis():
    assert wheel_strategy._is_runner(71.46, 0.0, BASE_CONFIG) is False
    assert wheel_strategy._is_runner(71.46, -5.0, BASE_CONFIG) is False


# ---------------------------------------------------------------------------
# _estimate_delta (Black-Scholes)
# ---------------------------------------------------------------------------


def test_estimate_delta_atm_call_near_half():
    # At-the-money call delta should sit around 0.5 — the whole point of the BS
    # fix (the old moneyness proxy returned ~1.0 here).
    d = wheel_strategy._estimate_delta("call", S=100, K=100, dte_days=30, iv=0.30)
    assert 0.45 < d < 0.60


def test_estimate_delta_itm_call_high():
    d = wheel_strategy._estimate_delta("call", S=100, K=80, dte_days=30, iv=0.30)
    assert d > 0.85


def test_estimate_delta_otm_call_low():
    d = wheel_strategy._estimate_delta("call", S=100, K=130, dte_days=30, iv=0.30)
    assert d < 0.15


def test_estimate_delta_atm_put_magnitude():
    # |put delta| at the money is also ~0.5.
    d = wheel_strategy._estimate_delta("put", S=100, K=100, dte_days=30, iv=0.30)
    assert 0.40 < d < 0.55


def test_estimate_delta_degenerate_falls_back_to_intrinsic():
    # iv=0 (or dte=0) → intrinsic signal: ITM call = 1.0, OTM call = 0.0.
    assert wheel_strategy._estimate_delta("call", S=100, K=80, dte_days=30, iv=0.0) == 1.0
    assert wheel_strategy._estimate_delta("call", S=100, K=130, dte_days=30, iv=0.0) == 0.0


# ---------------------------------------------------------------------------
# _select_best_option with delta_max_override (Lever A mechanism)
# ---------------------------------------------------------------------------


def _call_chain():
    """A 3-strike call chain around a $71.46 stock, expiring in 30 days.

    Deltas supplied directly (real-greek path), so _estimate_delta isn't
    invoked. $70 is ITM, $72.5 just OTM, $80 far OTM.
    """
    exp = (date.today() + timedelta(days=30)).isoformat()

    def sym(strike):
        return alpaca_client.build_occ_symbol("TMHC", exp, "call", strike)

    return [
        {"symbol": sym(70.0), "delta": 0.58, "bid_price": 3.50},   # ITM
        {"symbol": sym(72.5), "delta": 0.45, "bid_price": 2.00},   # just OTM
        {"symbol": sym(80.0), "delta": 0.12, "bid_price": 0.20},   # far OTM
    ]


def test_standard_band_rejects_all_near_money_calls():
    # With the default 0.15–0.30 ceiling, every strike fails (this is exactly
    # the TMHC situation): $70/$72.5 too high-delta, $80 too low.
    ranked, _ = wheel_strategy._select_best_option(
        _call_chain(), "call", BASE_CONFIG, 71.46, min_strike=68.0,
    )
    assert ranked == []


def test_runner_override_admits_near_money_otm_call():
    # Runner-mode: raise the ceiling to 0.60 AND floor the strike at the current
    # price (OTM-only). The $72.5 call (delta 0.45, above current) now passes;
    # the $70 ITM strike is excluded by the floor; $80 still fails delta_min.
    exp = (date.today() + timedelta(days=30)).isoformat()
    expected = alpaca_client.build_occ_symbol("TMHC", exp, "call", 72.5)

    ranked, _ = wheel_strategy._select_best_option(
        _call_chain(), "call", BASE_CONFIG, 71.46,
        min_strike=max(68.0, 71.46), delta_max_override=0.60,
    )
    assert len(ranked) == 1
    assert ranked[0]["symbol"] == expected


# ---------------------------------------------------------------------------
# _check_trailing_stop (Lever B)
# ---------------------------------------------------------------------------


@pytest.fixture
def patched_tb_and_alpaca():
    """Patch trading_db, alpaca_client, and _get_adjusted_cost_basis for the
    trailing-stop tests."""
    with patch.object(wheel_strategy, "trading_db") as td, \
         patch.object(wheel_strategy, "alpaca_client") as ac, \
         patch.object(wheel_strategy, "_get_adjusted_cost_basis",
                      new=AsyncMock(return_value=54.55)) as basis:
        td.update_position = AsyncMock()
        td.insert_order = AsyncMock()
        td.close_position = AsyncMock()
        td.log_activity = AsyncMock()
        ac.submit_stock_order = AsyncMock(
            return_value={"alpaca_order_id": "ord-1", "status": "submitted"})
        yield td, ac, basis


def _strategy(**config_overrides):
    cfg = {**BASE_CONFIG, **config_overrides}
    return {"id": "wheel", "config": cfg}


async def test_trailing_stop_disabled_is_noop(patched_tb_and_alpaca):
    td, ac, basis = patched_tb_and_alpaca
    pos = {"id": 1, "quantity": 100, "avg_entry_price": 55.0, "peak_price": 90.0}
    sold = await wheel_strategy._check_trailing_stop(
        MagicMock(), _strategy(trailing_stop_enabled=False), "TMHC", pos, 80.0)
    assert sold is False
    basis.assert_not_awaited()       # bails before any work
    ac.submit_stock_order.assert_not_awaited()


async def test_trailing_stop_skips_non_runner(patched_tb_and_alpaca):
    td, ac, basis = patched_tb_and_alpaca
    basis.return_value = 78.0        # current 80 is only +2.6% over basis → not a runner
    pos = {"id": 1, "quantity": 100, "avg_entry_price": 79.0, "peak_price": 95.0}
    sold = await wheel_strategy._check_trailing_stop(
        MagicMock(), _strategy(), "TMHC", pos, 80.0)
    assert sold is False
    ac.submit_stock_order.assert_not_awaited()
    td.close_position.assert_not_awaited()


async def test_trailing_stop_within_band_updates_peak_no_sell(patched_tb_and_alpaca):
    td, ac, basis = patched_tb_and_alpaca
    # Runner (current 71.46 vs basis 54.55, +31%); no stored peak yet, price is
    # above the trailing trigger → seed the peak, don't sell.
    pos = {"id": 1, "quantity": 100, "avg_entry_price": 55.0, "peak_price": None}
    sold = await wheel_strategy._check_trailing_stop(
        MagicMock(), _strategy(), "TMHC", pos, 71.46)
    assert sold is False
    td.update_position.assert_awaited_once()
    # peak seeded to the current price
    _, kwargs = td.update_position.await_args
    assert kwargs["peak_price"] == pytest.approx(71.46, abs=0.01)
    ac.submit_stock_order.assert_not_awaited()


async def test_trailing_stop_triggers_sell_below_peak(patched_tb_and_alpaca):
    td, ac, basis = patched_tb_and_alpaca
    # Runner that has pulled back: basis 54.55, peak 90, current 80.
    # Runner check: 80 >= 54.55*1.2 (65.46) ✓. Trigger: 80 <= 90*0.90 (81) ✓ → sell.
    pos = {"id": 7, "quantity": 100, "avg_entry_price": 55.0, "peak_price": 90.0}
    sold = await wheel_strategy._check_trailing_stop(
        MagicMock(), _strategy(), "TMHC", pos, 80.0)
    assert sold is True
    ac.submit_stock_order.assert_awaited_once()
    # Closed as 'trailing_stop' with realized P&L = (80 - 55) * 100 = 2500.
    args, _ = td.close_position.await_args
    assert args[1] == 7 and args[2] == "trailing_stop"
    assert args[3] == pytest.approx(2500.0)


async def test_trailing_stop_holds_when_above_trigger(patched_tb_and_alpaca):
    td, ac, basis = patched_tb_and_alpaca
    # Runner still near its peak (90 → 88, only -2.2%, trigger is 81) → hold.
    pos = {"id": 7, "quantity": 100, "avg_entry_price": 55.0, "peak_price": 90.0}
    sold = await wheel_strategy._check_trailing_stop(
        MagicMock(), _strategy(), "TMHC", pos, 88.0)
    assert sold is False
    ac.submit_stock_order.assert_not_awaited()


# ---------------------------------------------------------------------------
# _get_alpaca_share_qty (covered-call pre-flight coverage helper)
# ---------------------------------------------------------------------------


async def test_share_qty_returns_held_equity_quantity():
    positions = [
        {"symbol": "TMHC", "asset_class": "us_equity", "qty": 100.0},
        {"symbol": "PAGS", "asset_class": "us_equity", "qty": 5.0},
        {"symbol": "TMHC260618C00072500", "asset_class": "us_option", "qty": -1.0},
    ]
    with patch.object(wheel_strategy.alpaca_client, "get_positions",
                      new=AsyncMock(return_value=positions)):
        assert await wheel_strategy._get_alpaca_share_qty("TMHC") == 100.0
        # PAGS: the cross-strategy phantom case — Alpaca holds only 5 (< 100).
        assert await wheel_strategy._get_alpaca_share_qty("PAGS") == 5.0


async def test_share_qty_zero_when_not_held():
    with patch.object(wheel_strategy.alpaca_client, "get_positions",
                      new=AsyncMock(return_value=[])):
        assert await wheel_strategy._get_alpaca_share_qty("PAGS") == 0.0


async def test_share_qty_none_on_api_error():
    # API failure → None (caller falls through, doesn't block on a transient error).
    with patch.object(wheel_strategy.alpaca_client, "get_positions",
                      new=AsyncMock(side_effect=RuntimeError("alpaca down"))):
        assert await wheel_strategy._get_alpaca_share_qty("PAGS") is None


async def test_share_qty_ignores_option_legs_of_same_root():
    # A short option on the underlying must not be mistaken for equity shares.
    positions = [{"symbol": "PAGS260717C00010000", "asset_class": "us_option", "qty": -1.0}]
    with patch.object(wheel_strategy.alpaca_client, "get_positions",
                      new=AsyncMock(return_value=positions)):
        assert await wheel_strategy._get_alpaca_share_qty("PAGS") == 0.0
