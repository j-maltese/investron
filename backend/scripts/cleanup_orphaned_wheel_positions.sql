-- ============================================================================
-- One-time cleanup: orphaned Wheel option positions
-- ============================================================================
--
-- WHY THIS EXISTS
-- ---------------
-- The Wheel strategy submits covered-call / cash-secured-put orders as *day*
-- limit orders. If a day order does not fill, Alpaca expires it at the close of
-- that trading day. The option position row, however, was created with
-- status='open' BEFORE we knew whether the order would fill (see
-- wheel_strategy._sell_call / _sell_put). On fill, _sync_option_orders sets the
-- position's avg_entry_price + cost_basis; on a terminal order it is supposed to
-- close the position.
--
-- Prior to the "fix ghost orders" commit (0860779), the terminal-order branch
-- only matched ('cancelled','rejected') -- it did NOT match 'expired' and never
-- closed the position. Any day order that expired unfilled under that old code
-- left an orphaned option position stuck status='open' with avg_entry_price
-- NULL, forever.
--
-- Those orphans are not self-healing: once an order's status is terminal it
-- falls outside _sync_option_orders' pending-poll filter, so the (now-correct)
-- cleanup code never gets another chance to act on them. They must be cleaned up
-- once, by hand -- that is what this script does.
--
-- SYMPTOMS THIS FIXES
-- -------------------
--   * Activity Log flooded with: "Error processing <TICKER>: float() argument
--     must be a string or a real number, not 'NoneType'" every cycle. The
--     orphaned option (avg_entry_price NULL) was reprocessed by
--     _manage_call_position, which called float(None). (The float() guard commit
--     stops the crash; this script removes the dead rows that caused it.)
--   * Positions tab showing stale option rows stuck in "pending"/Selling Calls
--     with $0.00 premium and an expiration far in the future (e.g. TMHC, CALM).
--
-- HOW TO RUN
-- ----------
--   1. Run SECTION 1 (PREVIEW) first. It is read-only. Confirm the rows listed
--      are genuinely the orphans you expect (TMHC, CALM, ...).
--   2. Then run SECTION 2 (APPLY). It is wrapped in a transaction; if the row
--      counts look wrong, ROLLBACK instead of COMMIT.
--   3. Run against BOTH the production Supabase DB and the local dev DB
--      (localhost:5433) -- they have independent data.
--
-- The script is idempotent: re-running it after a successful apply will match
-- zero rows, because closed positions no longer satisfy the orphan predicate.
-- ============================================================================


-- ============================================================================
-- SECTION 1 -- PREVIEW (read-only). Run this first.
-- ============================================================================

-- 1a. The orphaned OPTION positions that will be CLOSED.
--     An orphan is an open option position that (a) never filled
--     (avg_entry_price IS NULL), (b) has a linked order in a terminal,
--     non-filled state, and (c) has NO linked order that is filled or still
--     live -- so we never close a position whose order is genuinely pending
--     today, nor one that actually filled.
SELECT
    p.id,
    p.strategy_id,
    p.ticker,
    p.option_type,
    p.strike_price,
    p.expiration_date,
    p.wheel_phase,
    p.opened_at,
    (
        SELECT string_agg(DISTINCT o.status, ',')
        FROM trading_orders o
        WHERE o.position_id = p.id
    ) AS linked_order_statuses
FROM trading_positions p
WHERE p.asset_type = 'option'
  AND p.status = 'open'
  AND p.avg_entry_price IS NULL                      -- never filled
  AND EXISTS (
        SELECT 1 FROM trading_orders o
        WHERE o.position_id = p.id
          AND o.status IN ('expired', 'cancelled', 'rejected')
  )
  AND NOT EXISTS (
        SELECT 1 FROM trading_orders o2
        WHERE o2.position_id = p.id
          AND o2.status IN ('filled', 'partially_filled',
                            'pending', 'pending_new', 'submitted',
                            'accepted', 'new')
  )
ORDER BY p.opened_at;

-- 1b. The STOCK positions that will be reverted from 'selling_calls' back to
--     'assigned'. A stock is stranded in 'selling_calls' if, after the orphaned
--     call above is closed, it no longer has any open call option. Reverting it
--     lets the strategy attempt a fresh covered call next cycle. (This preview
--     deliberately ignores the orphans -- it shows stocks whose ONLY open call
--     is an orphan being closed, plus any already missing a call entirely.)
SELECT
    s.id,
    s.strategy_id,
    s.ticker,
    s.quantity,
    s.avg_entry_price,
    s.wheel_phase
FROM trading_positions s
WHERE s.asset_type = 'stock'
  AND s.status = 'open'
  AND s.wheel_phase = 'selling_calls'
  AND NOT EXISTS (
        -- any open call option for this stock that is NOT itself an orphan
        SELECT 1
        FROM trading_positions c
        WHERE c.strategy_id = s.strategy_id
          AND c.ticker = s.ticker
          AND c.asset_type = 'option'
          AND c.option_type = 'call'
          AND c.status = 'open'
          AND NOT (
                c.avg_entry_price IS NULL
                AND EXISTS (
                    SELECT 1 FROM trading_orders o
                    WHERE o.position_id = c.id
                      AND o.status IN ('expired', 'cancelled', 'rejected')
                )
                AND NOT EXISTS (
                    SELECT 1 FROM trading_orders o2
                    WHERE o2.position_id = c.id
                      AND o2.status IN ('filled', 'partially_filled',
                                        'pending', 'pending_new', 'submitted',
                                        'accepted', 'new')
                )
          )
  )
ORDER BY s.ticker;


-- ============================================================================
-- SECTION 2 -- APPLY. Run after confirming the preview above.
-- ============================================================================
-- Wrapped in a transaction so you can inspect the row counts and ROLLBACK if
-- anything looks off. Replace COMMIT with ROLLBACK to abort.

BEGIN;

-- Stash the orphan ids in a temp table so the two UPDATEs below share exactly
-- the same definition of "orphan" and the script stays readable.
CREATE TEMP TABLE _orphaned_options ON COMMIT DROP AS
SELECT p.id
FROM trading_positions p
WHERE p.asset_type = 'option'
  AND p.status = 'open'
  AND p.avg_entry_price IS NULL
  AND EXISTS (
        SELECT 1 FROM trading_orders o
        WHERE o.position_id = p.id
          AND o.status IN ('expired', 'cancelled', 'rejected')
  )
  AND NOT EXISTS (
        SELECT 1 FROM trading_orders o2
        WHERE o2.position_id = p.id
          AND o2.status IN ('filled', 'partially_filled',
                            'pending', 'pending_new', 'submitted',
                            'accepted', 'new')
  );

-- Step 1: close the orphaned option positions. close_reason='expired' matches
-- how _sync_option_orders labels day-order expirations, keeping history consistent.
UPDATE trading_positions
SET status      = 'closed',
    close_reason = 'expired',
    closed_at    = NOW(),
    updated_at   = NOW()
WHERE id IN (SELECT id FROM _orphaned_options);

-- Step 2: revert stranded stocks to 'assigned'. Runs AFTER Step 1, so the
-- just-closed orphans no longer count as "open call options" here -- a plain
-- open-call check is now sufficient. Any stock left in 'selling_calls' with no
-- open call is freed to sell a fresh covered call next cycle.
UPDATE trading_positions s
SET wheel_phase = 'assigned',
    updated_at  = NOW()
WHERE s.asset_type = 'stock'
  AND s.status = 'open'
  AND s.wheel_phase = 'selling_calls'
  AND NOT EXISTS (
        SELECT 1
        FROM trading_positions c
        WHERE c.strategy_id = s.strategy_id
          AND c.ticker = s.ticker
          AND c.asset_type = 'option'
          AND c.option_type = 'call'
          AND c.status = 'open'
  );

-- Inspect the row counts emitted above. If they match the preview, COMMIT.
-- Otherwise run ROLLBACK instead.
COMMIT;