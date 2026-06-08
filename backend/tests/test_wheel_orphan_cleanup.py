"""Tests for the Wheel strategy's orphan self-healing logic.

Covers the two hardening changes that fix stranded option positions:

  1. ``_cleanup_orphaned_option_positions`` — the per-cycle sweep that closes
     never-filled option positions whose orders are all terminal, reverts the
     underlying shares of a dead covered call back to 'assigned', and frees any
     stock stranded in 'selling_calls' with no open call.

  2. ``_find_position`` — the dispatch primitive. The per-ticker loop now keys
     Phase 3 off an open OPTION and Phase 2 off simply holding shares, so a stock
     left with a stale 'selling_calls' label can neither be stranded nor
     misrouted into ``_manage_call_position``.

These are unit tests: the DB session and the ``trading_db`` helpers are mocked,
so no Postgres is required. They assert the orchestration/branching contract,
not the SQL itself (the SQL predicate is mirrored 1:1 in
scripts/cleanup_orphaned_wheel_positions.sql for manual use).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import wheel_strategy


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_result(rows):
    """Build a mock SQLAlchemy Result whose .mappings().all() yields ``rows``.

    Mirrors how the sweep consumes query output:
        result = await db.execute(...)
        rows = result.mappings().all()
    .mappings() and .all() are synchronous on a real Result, so plain MagicMock.
    """
    result = MagicMock()
    result.mappings.return_value.all.return_value = rows
    return result


def _make_db(execute_results):
    """Build a mock AsyncSession.

    ``db.execute`` is awaited and is called once per raw query in the function
    under test (Part 1 SELECT, then Part 2 UPDATE...RETURNING) — so we hand it a
    side_effect list of pre-built results in call order. ``db.commit`` is awaited.
    """
    db = MagicMock()
    db.execute = AsyncMock(side_effect=execute_results)
    db.commit = AsyncMock()
    return db


@pytest.fixture
def patched_trading_db():
    """Patch the trading_db helpers the sweep calls, as AsyncMocks."""
    with patch.object(wheel_strategy, "trading_db") as td:
        td.close_position = AsyncMock()
        td.update_position = AsyncMock()
        td.log_activity = AsyncMock()
        yield td


# ---------------------------------------------------------------------------
# _cleanup_orphaned_option_positions
# ---------------------------------------------------------------------------


async def test_orphaned_call_is_closed_and_stock_reverted(patched_trading_db):
    """A dead covered call is closed and its shares handed back to 'assigned'."""
    orphan = {"id": 101, "ticker": "TMHC", "option_type": "call",
              "option_symbol": "TMHC260618C00060000"}
    db = _make_db([_make_result([orphan]), _make_result([])])  # part1: orphan, part2: none

    with patch.object(wheel_strategy, "_get_open_position_for_ticker",
                      new=AsyncMock(return_value={"id": 55, "asset_type": "stock"})):
        await wheel_strategy._cleanup_orphaned_option_positions(db, "wheel-1")

    # The orphaned option position is closed as 'expired'.
    patched_trading_db.close_position.assert_awaited_once_with(db, 101, "expired")
    # Its underlying shares are reverted so the next cycle sells a fresh call.
    patched_trading_db.update_position.assert_awaited_once_with(
        db, 55, wheel_phase="assigned")
    # And the action is logged + committed.
    assert patched_trading_db.log_activity.await_count == 1
    db.commit.assert_awaited_once()


async def test_orphaned_put_is_closed_without_stock_revert(patched_trading_db):
    """A dead put is closed but no stock revert happens (a put holds no shares)."""
    orphan = {"id": 102, "ticker": "PAGS", "option_type": "put",
              "option_symbol": "PAGS260417P00009000"}
    db = _make_db([_make_result([orphan]), _make_result([])])

    # _get_open_position_for_ticker must NOT be consulted for a put.
    with patch.object(wheel_strategy, "_get_open_position_for_ticker",
                      new=AsyncMock()) as get_pos:
        await wheel_strategy._cleanup_orphaned_option_positions(db, "wheel-1")

    patched_trading_db.close_position.assert_awaited_once_with(db, 102, "expired")
    patched_trading_db.update_position.assert_not_awaited()
    get_pos.assert_not_awaited()
    db.commit.assert_awaited_once()


async def test_stranded_stock_reverted_when_no_orphan_options(patched_trading_db):
    """Part 2: a stock stuck in 'selling_calls' with no open call is freed."""
    db = _make_db([_make_result([]),                       # part1: no orphans
                   _make_result([{"ticker": "CALM"}])])    # part2: one stranded stock

    await wheel_strategy._cleanup_orphaned_option_positions(db, "wheel-1")

    patched_trading_db.close_position.assert_not_awaited()
    # The revert itself is the raw UPDATE; we assert it was logged + committed.
    assert patched_trading_db.log_activity.await_count == 1
    db.commit.assert_awaited_once()


async def test_noop_when_nothing_to_clean(patched_trading_db):
    """No orphans and nothing stranded: no closes/logs, but still commits."""
    db = _make_db([_make_result([]), _make_result([])])

    await wheel_strategy._cleanup_orphaned_option_positions(db, "wheel-1")

    patched_trading_db.close_position.assert_not_awaited()
    patched_trading_db.update_position.assert_not_awaited()
    patched_trading_db.log_activity.assert_not_awaited()
    db.commit.assert_awaited_once()


# ---------------------------------------------------------------------------
# _find_position — dispatch primitive
# ---------------------------------------------------------------------------


def _positions():
    """A ticker holding shares (stale 'selling_calls' label) plus an open call.

    Models the exact state the hardening must handle: a stock can carry a
    'selling_calls' label, so phase alone is ambiguous between the option and
    the shares.
    """
    return [
        {"id": 1, "asset_type": "stock", "wheel_phase": "selling_calls",
         "status": "open", "avg_entry_price": 50.0},
        {"id": 2, "asset_type": "option", "option_type": "call",
         "wheel_phase": "selling_calls", "status": "open", "avg_entry_price": 0.65},
    ]


def test_call_pos_lookup_ignores_stock_with_stale_label():
    """Requiring asset_type='option' returns the call, never the stock."""
    match = wheel_strategy._find_position(
        _positions(), wheel_phase="selling_calls", asset_type="option")
    assert match is not None
    assert match["id"] == 2
    assert match["asset_type"] == "option"


def test_stock_lookup_returns_shares_regardless_of_phase():
    """Phase 2 keys off holding shares, even under a 'selling_calls' label."""
    match = wheel_strategy._find_position(_positions(), asset_type="stock")
    assert match is not None
    assert match["id"] == 1
    assert match["asset_type"] == "stock"


def test_find_position_skips_closed_positions():
    """Only open positions are eligible."""
    positions = [
        {"id": 9, "asset_type": "option", "option_type": "call",
         "wheel_phase": "selling_calls", "status": "closed"},
    ]
    assert wheel_strategy._find_position(
        positions, wheel_phase="selling_calls", asset_type="option") is None


def test_put_lookup_matches_open_put():
    positions = [
        {"id": 7, "asset_type": "option", "option_type": "put",
         "wheel_phase": "selling_puts", "status": "open"},
    ]
    match = wheel_strategy._find_position(
        positions, wheel_phase="selling_puts", asset_type="option")
    assert match is not None and match["id"] == 7