"""Migrate holding-related data from SQLite to PostgreSQL using pandas."""

import sqlite3

import pandas as pd
from sqlalchemy import create_engine, text

SQLITE_PATH = "data/fund_manager.db"
PG_URL = "postgresql://fundmanager:fundmanager123@localhost:5432/fund_manager"

HOLDING_FUND_CODES = [
    "012348", "003949", "202003", "011506", "017144",
    "001704", "013851", "005669", "013390",
]


def pg_insert(pg, table_name, df):
    if df.empty:
        return 0
    df.to_sql(table_name, pg, if_exists="append", index=False, method="multi")
    return len(df)


def main():
    sqlite3_conn = sqlite3.connect(SQLITE_PATH)
    pg = create_engine(PG_URL)

    placeholders = ",".join(f"'{c}'" for c in HOLDING_FUND_CODES)

    fund_ids_df = pd.read_sql(f"SELECT id, fund_code FROM fund_master WHERE fund_code IN ({placeholders})", sqlite3_conn)
    fund_ids = fund_ids_df["id"].tolist()
    fund_id_list = ",".join(str(i) for i in fund_ids)
    print(f"Funds to migrate: {len(fund_ids)}")

    with pg.begin() as conn:
        for t in ["position_lot", "portfolio_snapshot", "nav_snapshot", "transaction", "fund_master", "portfolio"]:
            conn.execute(text(f"DELETE FROM {t}"))

    # portfolio
    df = pd.read_sql("SELECT * FROM portfolio", sqlite3_conn)
    if not df.empty and "is_default" in df.columns:
        df["is_default"] = df["is_default"].astype(bool)
    pg_insert(pg, "portfolio", df)
    print(f"Portfolios: {len(df)}")

    # fund_master
    df = pd.read_sql(f"SELECT * FROM fund_master WHERE id IN ({fund_id_list})", sqlite3_conn)
    pg_insert(pg, "fund_master", df)
    print(f"Fund master: {len(df)}")

    # nav_snapshot
    df = pd.read_sql(f"SELECT * FROM nav_snapshot WHERE fund_id IN ({fund_id_list})", sqlite3_conn)
    for i in range(0, len(df), 1000):
        pg_insert(pg, "nav_snapshot", df.iloc[i:i+1000])
        print(f"  nav_snapshot: {min(i+1000, len(df))}/{len(df)}")
    print(f"NAV snapshot: {len(df)}")

    # transaction (quoted because reserved word)
    df = pd.read_sql('SELECT * FROM "transaction"', sqlite3_conn)
    pg_insert(pg, "transaction", df)
    print(f"Transactions: {len(df)}")

    # position_lot
    df = pd.read_sql(f"SELECT * FROM position_lot WHERE fund_id IN ({fund_id_list})", sqlite3_conn)
    # Null out broken FK references
    if not df.empty and "source_transaction_id" in df.columns:
        df["source_transaction_id"] = None
    pg_insert(pg, "position_lot", df)
    print(f"Position lots: {len(df)}")

    # portfolio_snapshot
    try:
        df = pd.read_sql("SELECT * FROM portfolio_snapshot", sqlite3_conn)
        pg_insert(pg, "portfolio_snapshot", df)
        print(f"Portfolio snapshots: {len(df)}")
    except Exception as e:
        print(f"Skipped portfolio_snapshot: {e}")

    # Reset sequences
    with pg.begin() as conn:
        for tbl, col in [("portfolio","id"),("fund_master","id"),("transaction","id"),("position_lot","id"),("portfolio_snapshot","id")]:
            try:
                mx = conn.execute(text(f"SELECT COALESCE(MAX({col}),0)+1 FROM {tbl}")).scalar()
                conn.execute(text(f"SELECT setval(pg_get_serial_sequence('{tbl}','{col}'),{mx})"))
            except Exception:
                pass

    sqlite3_conn.close()
    print("\n✅ Migration complete!")


if __name__ == "__main__":
    main()
