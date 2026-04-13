#!/usr/bin/env python3
"""Backfill full NAV history for ALL funds into PostgreSQL.

1. Fetches all fund codes from akshare
2. Inserts into fund_master (PG)
3. For each fund, fetches NAV history and inserts into nav_snapshot (PG)
"""

import os
import sys
import time

import akshare as ak
import pandas as pd
from sqlalchemy import create_engine, text

PG_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql://fundmanager:fundmanager123@localhost:5432/fund_manager",
)
BATCH_SIZE = 500
RATE_LIMIT = 0.3  # seconds between requests


def get_engine():
    return create_engine(PG_URL, pool_size=5, max_overflow=10)


def sync_fund_master(engine):
    """Pull all fund codes from akshare and upsert into PG."""
    print(f"[{time.strftime('%H:%M:%S')}] 拉取全市场基金列表...")
    df = ak.fund_name_em()
    print(f"[{time.strftime('%H:%M:%S')}] 拉到 {len(df)} 只基金")

    # Rename columns to match our schema
    # akshare returns: 基金代码, 基金简称, 基金类型, 拼音缩写
    df = df.rename(columns={
        "基金代码": "fund_code",
        "基金简称": "fund_name",
        "基金类型": "fund_type",
    })
    df = df[["fund_code", "fund_name", "fund_type"]]
    df["base_currency_code"] = "CNY"

    with engine.begin() as conn:
        # Get existing funds
        existing = pd.read_sql("SELECT fund_code FROM fund_master", conn)
        existing_codes = set(existing["fund_code"].tolist())

        new_funds = df[~df["fund_code"].isin(existing_codes)]
        if len(new_funds) > 0:
            new_funds.to_sql("fund_master", conn, if_exists="append", index=False)
            print(f"[{time.strftime('%H:%M:%S')}] 新增 {len(new_funds)} 只基金到 fund_master")
        else:
            print(f"[{time.strftime('%H:%M:%S')}] fund_master 已是最新")

    return df


def get_funds_needing_nav(engine):
    """Get funds with little or no NAV data."""
    with engine.begin() as conn:
        result = conn.execute(text("""
            SELECT fm.id, fm.fund_code, fm.fund_name,
                   COALESCE(ns.cnt, 0) as nav_cnt
            FROM fund_master fm
            LEFT JOIN (
                SELECT fund_id, COUNT(*) as cnt
                FROM nav_snapshot
                GROUP BY fund_id
            ) ns ON fm.id = ns.fund_id
            WHERE COALESCE(ns.cnt, 0) < 100
            ORDER BY fm.id
        """))
        rows = result.fetchall()
    return rows


def backfill_nav(engine, funds):
    total = len(funds)
    print(f"[{time.strftime('%H:%M:%S')}] 需要补全净值: {total} 只基金")

    success = 0
    fail = 0
    skipped = 0
    start_time = time.time()

    for i, (fund_id, fund_code, fund_name, nav_cnt) in enumerate(funds):
        try:
            df = ak.fund_open_fund_info_em(symbol=fund_code, indicator="单位净值走势")

            if len(df) == 0:
                skipped += 1
                continue

            df["净值日期"] = pd.to_datetime(df["净值日期"])

            # Get accumulated NAV
            acc_map = {}
            try:
                df_acc = ak.fund_open_fund_info_em(symbol=fund_code, indicator="累计净值走势")
                df_acc["净值日期"] = pd.to_datetime(df_acc["净值日期"])
                acc_map = dict(
                    zip(df_acc["净值日期"].dt.strftime("%Y-%m-%d"), df_acc["累计净值"])
                )
            except Exception:
                pass

            # Prepare rows
            rows = []
            for _, row in df.iterrows():
                date_str = row["净值日期"].strftime("%Y-%m-%d")
                unit_nav = float(row["单位净值"])
                acc_nav = acc_map.get(date_str, unit_nav)
                rows.append((fund_id, date_str, unit_nav, acc_nav, "akshare"))

            # Delete old + insert new in one transaction
            with engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM nav_snapshot WHERE fund_id = :fid"),
                    {"fid": fund_id},
                )
                conn.execute(
                    text("""
                        INSERT INTO nav_snapshot
                            (fund_id, nav_date, unit_nav_amount, accumulated_nav_amount, source_name)
                        VALUES (:fid, :dt, :uv, :av, :src)
                    """),
                    [
                        {"fid": r[0], "dt": r[1], "uv": r[2], "av": r[3], "src": r[4]}
                        for r in rows
                    ],
                )

            success += 1

            if (i + 1) % 100 == 0 or (i + 1) == total:
                elapsed = time.time() - start_time
                rate = (i + 1) / elapsed
                eta = (total - i - 1) / rate / 60
                print(
                    f"[{time.strftime('%H:%M:%S')}] {i+1}/{total} | "
                    f"成功{success} 失败{fail} 跳过{skipped} | "
                    f"速率{rate:.1f}/s ETA:{eta:.0f}min"
                )

            time.sleep(RATE_LIMIT)

        except Exception as e:
            fail += 1
            if fail <= 10 or fail % 100 == 0:
                print(f"[{time.strftime('%H:%M:%S')}] ❌ {fund_code} {fund_name}: {e}")
            time.sleep(0.5)

    elapsed = time.time() - start_time
    print(
        f"\n✅ 完成! 成功{success} 失败{fail} 跳过{skipped} "
        f"耗时{elapsed/60:.1f}分钟"
    )


def main():
    start_time = time.time()
    engine = get_engine()

    # Step 1: Sync fund_master
    sync_fund_master(engine)

    # Step 2: Get funds needing NAV
    funds = get_funds_needing_nav(engine)

    if not funds:
        print("所有基金净值数据已完整！")
        return

    # Step 3: Backfill NAV
    backfill_nav(engine, funds)

    engine.dispose()


if __name__ == "__main__":
    main()
