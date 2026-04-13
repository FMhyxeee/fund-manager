"""Batch import all fund master data from AKShare into the database."""

from __future__ import annotations

import time
import sys

import akshare as ak
from sqlalchemy import select
from sqlalchemy.orm import Session

from fund_manager.storage.db import get_session_factory
from fund_manager.storage.models import FundMaster


def main() -> None:
    Session = get_session_factory()
    session = Session()

    print("Fetching fund list from AKShare...")
    df = ak.fund_name_em()
    total = len(df)
    print(f"Total funds found: {total}")

    # Get existing fund codes to skip
    existing_codes = set(
        r[0] for r in session.execute(select(FundMaster.fund_code)).all()
    )
    print(f"Already in DB: {len(existing_codes)}")

    created = 0
    skipped = 0
    batch_size = 500

    for i, row in df.iterrows():
        fund_code = str(row["基金代码"]).zfill(6)
        fund_name = str(row["基金简称"])
        fund_type = str(row.get("基金类型", ""))

        if fund_code in existing_codes:
            skipped += 1
            continue

        fund = FundMaster(
            fund_code=fund_code,
            fund_name=fund_name,
            fund_type=fund_type if fund_type and fund_type != "nan" else None,
            base_currency_code="CNY",
            source_name="akshare",
        )
        session.add(fund)
        existing_codes.add(fund_code)
        created += 1

        if created % batch_size == 0:
            session.flush()
            print(f"  Progress: {i+1}/{total} (created={created}, skipped={skipped})")

    session.commit()
    print(f"\nDone! Created: {created}, Skipped: {skipped}, Total in DB: {len(existing_codes)}")
    session.close()


if __name__ == "__main__":
    main()
