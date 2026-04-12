BEGIN;

-- The first repair pass selected both the positive tx:1 row and the new zeroed
-- close row as source material. Append a later row with the same lot_key/run_id
-- so the authoritative resolver keeps the intended positive 012348 snapshot.

INSERT INTO position_lot (
    portfolio_id,
    fund_id,
    source_transaction_id,
    run_id,
    lot_key,
    opened_on,
    as_of_date,
    remaining_units,
    average_cost_per_unit,
    total_cost_amount
)
SELECT
    pl.portfolio_id,
    pl.fund_id,
    pl.source_transaction_id,
    'repair-unified-holdings-20260411-a',
    'initial:012348:20260403:rpr0411a',
    DATE '2026-04-03',
    DATE '2026-04-03',
    pl.remaining_units,
    pl.average_cost_per_unit,
    pl.total_cost_amount
FROM position_lot pl
WHERE pl.lot_key = 'tx:1'
  AND pl.remaining_units > 0
ORDER BY pl.id DESC
LIMIT 1;

INSERT INTO position_lot (
    portfolio_id,
    fund_id,
    source_transaction_id,
    run_id,
    lot_key,
    opened_on,
    as_of_date,
    remaining_units,
    average_cost_per_unit,
    total_cost_amount
)
SELECT
    pl.portfolio_id,
    pl.fund_id,
    pl.source_transaction_id,
    'repair-unified-holdings-20260411-b',
    'initial:012348:20260407:rpr0411b',
    DATE '2026-04-07',
    DATE '2026-04-07',
    pl.remaining_units,
    pl.average_cost_per_unit,
    pl.total_cost_amount
FROM position_lot pl
WHERE pl.lot_key = 'tx:1'
  AND pl.remaining_units > 0
ORDER BY pl.id DESC
LIMIT 1;

COMMIT;
