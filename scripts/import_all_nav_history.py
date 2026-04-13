"""Batch import NAV history for all funds from AKShare."""

from __future__ import annotations

import time
import traceback
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_manager.data_adapters.akshare_adapter import get_fund_nav_history
from fund_manager.storage.db import get_session_factory
from fund_manager.storage.models import FundMaster, NavSnapshot

BATCH_SIZE = 50
DELAY_SECONDS = 0.3  # rate limit between API calls
NAV_DAYS = 30  # how many days of history to pull


def main() -> None:
    SessionFactory = get_session_factory()

    print(f"Loading funds without NAV data...")
    session = SessionFactory()

    # Find funds that have no NAV snapshots yet
    funds_with_nav = set(
        r[0] for r in session.execute(
            select(NavSnapshot.fund_id).distinct()
        ).all()
    )

    all_funds = session.execute(
        select(FundMaster.id, FundMaster.fund_code, FundMaster.fund_name)
        .order_by(FundMaster.id.asc())
    ).all()

    funds_to_process = [
        (fid, fcode, fname) for fid, fcode, fname in all_funds
        if fid not in funds_with_nav
    ]

    total = len(funds_to_process)
    print(f"Total funds: {len(all_funds)}, With NAV: {len(funds_with_nav)}, To process: {total}")
    session.close()

    success = 0
    failed = 0
    no_data = 0

    for i, (fund_id, fund_code, fund_name) in enumerate(funds_to_process):
        try:
            end = date.today() - timedelta(days=1)
            start = end - timedelta(days=NAV_DAYS)

            nav_history = get_fund_nav_history(fund_code, start_date=start, end_date=end)

            if not nav_history.points:
                no_data += 1
                if (i + 1) % 100 == 0:
                    print(f"  [{i+1}/{total}] {fund_code} {fund_name}: no NAV data")
                continue

            session = SessionFactory()
            try:
                # Check existing dates
                existing_dates = set(
                    r[0] for r in session.execute(
                        select(NavSnapshot.nav_date).where(NavSnapshot.fund_id == fund_id)
                    ).all()
                )

                added = 0
                for pt in nav_history.points:
                    if pt.nav_date in existing_dates:
                        continue
                    snap = NavSnapshot(
                        fund_id=fund_id,
                        nav_date=pt.nav_date,
                        unit_nav_amount=pt.unit_nav,
                        accumulated_nav_amount=pt.accumulated_nav,
                        daily_return_ratio=pt.daily_return_pct / 100 if pt.daily_return_pct else None,
                        source_name="akshare",
                    )
                    session.add(snap)
                    added += 1

                if added > 0:
                    session.commit()
                    success += 1
                else:
                    no_data += 1
            finally:
                session.close()

            if (i + 1) % 100 == 0:
                print(f"  [{i+1}/{total}] success={success}, failed={failed}, no_data={no_data}")

        except Exception as e:
            failed += 1
            if failed <= 20:
                print(f"  [{i+1}/{total}] ERROR {fund_code}: {e}")
            session.rollback()

        time.sleep(DELAY_SECONDS)

    print(f"\nDone! Success: {success}, Failed: {failed}, No data: {no_data}")


if __name__ == "__main__":
    main()
