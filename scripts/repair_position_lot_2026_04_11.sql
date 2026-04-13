BEGIN;

DO $$
BEGIN
    IF EXISTS (
        SELECT 1
        FROM position_lot
        WHERE run_id IN (
            'repair-close-tx1-20260411',
            'repair-unified-holdings-20260411-a',
            'repair-unified-holdings-20260411-b'
        )
    ) THEN
        RAISE EXCEPTION 'Repair run_id already exists; aborting to avoid duplicate repair rows.';
    END IF;
END $$;

-- Close the orphan tx:1 lot on 2026-04-03 so later bootstrap batches do not
-- double-count 012348 alongside the repaired opening snapshot batches.
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
    COALESCE(pl.source_transaction_id, 1),
    'repair-close-tx1-20260411',
    pl.lot_key,
    pl.opened_on,
    DATE '2026-04-03',
    0,
    pl.average_cost_per_unit,
    0
FROM position_lot pl
WHERE pl.lot_key = 'tx:1'
ORDER BY pl.id DESC
LIMIT 1;

-- Create a unified 2026-04-03 bootstrap batch with the nine held funds that
-- existed after 003949 was added and before the three funds were later sold.
WITH source_lots AS (
    SELECT
        fm.fund_code,
        pl.portfolio_id,
        pl.fund_id,
        pl.remaining_units,
        pl.average_cost_per_unit,
        pl.total_cost_amount
    FROM position_lot pl
    JOIN fund_master fm ON fm.id = pl.fund_id
    WHERE pl.lot_key = 'tx:1'
      AND pl.remaining_units > 0

    UNION ALL

    SELECT
        fm.fund_code,
        pl.portfolio_id,
        pl.fund_id,
        pl.remaining_units,
        pl.average_cost_per_unit,
        pl.total_cost_amount
    FROM position_lot pl
    JOIN fund_master fm ON fm.id = pl.fund_id
    WHERE pl.run_id = 'holdings-import-20260403-08ca9250'

    UNION ALL

    SELECT
        fm.fund_code,
        pl.portfolio_id,
        pl.fund_id,
        pl.remaining_units,
        pl.average_cost_per_unit,
        pl.total_cost_amount
    FROM position_lot pl
    JOIN fund_master fm ON fm.id = pl.fund_id
    WHERE pl.run_id = 'manual-holding-003949'
)
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
    src.portfolio_id,
    src.fund_id,
    NULL,
    'repair-unified-holdings-20260411-a',
    'initial:' || src.fund_code || ':20260403:rpr0411a',
    DATE '2026-04-03',
    DATE '2026-04-03',
    src.remaining_units,
    src.average_cost_per_unit,
    src.total_cost_amount
FROM source_lots src
ORDER BY src.fund_code;

-- Create the 2026-04-07 current-holdings bootstrap batch after the three sold
-- funds were removed. This becomes the latest authoritative initial batch.
WITH source_lots AS (
    SELECT
        fm.fund_code,
        pl.portfolio_id,
        pl.fund_id,
        pl.remaining_units,
        pl.average_cost_per_unit,
        pl.total_cost_amount
    FROM position_lot pl
    JOIN fund_master fm ON fm.id = pl.fund_id
    WHERE pl.lot_key = 'tx:1'
      AND pl.remaining_units > 0

    UNION ALL

    SELECT
        fm.fund_code,
        pl.portfolio_id,
        pl.fund_id,
        pl.remaining_units,
        pl.average_cost_per_unit,
        pl.total_cost_amount
    FROM position_lot pl
    JOIN fund_master fm ON fm.id = pl.fund_id
    WHERE pl.run_id = 'holdings-import-20260403-08ca9250'

    UNION ALL

    SELECT
        fm.fund_code,
        pl.portfolio_id,
        pl.fund_id,
        pl.remaining_units,
        pl.average_cost_per_unit,
        pl.total_cost_amount
    FROM position_lot pl
    JOIN fund_master fm ON fm.id = pl.fund_id
    WHERE pl.run_id = 'manual-holding-003949'
)
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
    src.portfolio_id,
    src.fund_id,
    NULL,
    'repair-unified-holdings-20260411-b',
    'initial:' || src.fund_code || ':20260407:rpr0411b',
    DATE '2026-04-07',
    DATE '2026-04-07',
    src.remaining_units,
    src.average_cost_per_unit,
    src.total_cost_amount
FROM source_lots src
WHERE src.fund_code IN (
    '003949',
    '011506',
    '012348',
    '013390',
    '017144',
    '202003'
)
ORDER BY src.fund_code;

COMMIT;
