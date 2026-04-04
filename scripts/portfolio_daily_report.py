#!/usr/bin/env python3
"""每日持仓分析报告 - 被子主组合"""

from __future__ import annotations

import os
import sys
from datetime import date

import numpy as np
from sqlalchemy import text

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from fund_manager.core.services.fund_data_sync_service import FundDataSyncService
from fund_manager.core.services.portfolio_service import PortfolioService
from fund_manager.storage.db import get_engine, get_session_factory

PORTFOLIO_ID = 1  # 被子主组合


def _normalize_daily_return_ratio(value) -> float | None:
    """Handle legacy rows that stored percentage points instead of ratios."""
    if value is None:
        return None
    normalized = float(value)
    return normalized / 100 if abs(normalized) > 0.2 else normalized


def _refresh_portfolio_nav() -> None:
    """Refresh held funds through the canonical sync service before reporting."""
    session = get_session_factory()()
    try:
        result = FundDataSyncService(session).sync_portfolio_funds(
            PORTFOLIO_ID,
            as_of_date=date.today(),
        )
        session.commit()
    finally:
        session.close()

    for detail in result.funds:
        if detail.nav_records_inserted > 0:
            print(f"Updated {detail.fund_code}: +{detail.nav_records_inserted} NAV records")
        for warning in detail.warnings:
            print(f"[warn] {detail.fund_code}: {warning}", file=sys.stderr)
        for error in detail.errors:
            print(f"[warn] {detail.fund_code}: {error}", file=sys.stderr)


def _load_recent_nav_rows(fund_code: str) -> list[tuple]:
    engine = get_engine()
    with engine.connect() as connection:
        return list(
            connection.execute(
                text(
                    """SELECT nav_date, unit_nav_amount, daily_return_ratio
                    FROM nav_snapshot
                    WHERE fund_id = (SELECT id FROM fund_master WHERE fund_code=:fc)
                    ORDER BY nav_date DESC
                    LIMIT 30"""
                ),
                {"fc": fund_code},
            ).fetchall()
        )


def generate_report(*, as_of_date: date | None = None) -> str:
    """Generate a human-readable report from canonical position lots."""
    effective_date = as_of_date or date.today()
    session = get_session_factory()()
    try:
        snapshot = PortfolioService(session).assemble_portfolio_snapshot(
            PORTFOLIO_ID,
            as_of_date=effective_date,
        )
    finally:
        session.close()

    if not snapshot.positions:
        return "📭 当前无持仓"

    lines = ["📊 每日持仓报告", ""]

    for position in snapshot.positions:
        if position.latest_nav_per_unit is None or position.current_value_amount is None:
            lines.append(f"**{position.fund_name}（{position.fund_code}）** - 无净值数据")
            lines.append("")
            continue

        recent_nav_rows = _load_recent_nav_rows(position.fund_code)
        if len(recent_nav_rows) > 1:
            daily_returns = [
                normalized
                for row in recent_nav_rows
                if (normalized := _normalize_daily_return_ratio(row[2])) is not None
            ]
            vol_30d = np.std(daily_returns) * np.sqrt(252) * 100 if daily_returns else 0.0
            month_ret = (
                float(recent_nav_rows[0][1]) / float(recent_nav_rows[-1][1]) - 1
            ) * 100
        else:
            vol_30d = 0.0
            month_ret = 0.0

        recent_lines: list[str] = []
        for nav_date, unit_nav, daily_return_ratio in recent_nav_rows[:5]:
            normalized_return = _normalize_daily_return_ratio(daily_return_ratio)
            chg = (
                f"{normalized_return * 100:+.2f}%"
                if normalized_return is not None
                else "N/A"
            )
            recent_lines.append(f"{nav_date} {float(unit_nav):.4f} ({chg})")

        pnl = float(position.unrealized_pnl_amount or 0)
        pnl_pct = (
            pnl / float(position.total_cost_amount) * 100
            if position.total_cost_amount
            else 0.0
        )
        emoji = "🔴" if pnl < 0 else "🟢"

        lines.append(f"{emoji} **{position.fund_name}（{position.fund_code}）**")
        lines.append(
            "份额: "
            f"{float(position.units):,.2f} ｜ 成本: ¥{float(position.total_cost_amount):,.2f}"
            f"（¥{float(position.average_cost_per_unit):.4f}/份）"
        )
        lines.append(
            "最新净值: "
            f"¥{float(position.latest_nav_per_unit):.4f}（{position.latest_nav_date}）"
        )
        lines.append(
            "市值: "
            f"¥{float(position.current_value_amount):,.2f} ｜ 浮动盈亏: ¥{pnl:+,.2f}"
            f"（{pnl_pct:+.2f}%）"
        )
        lines.append(f"近30日波动率: {vol_30d:.1f}% ｜ 近30日收益: {month_ret:+.2f}%")
        lines.append("近5日走势:")
        lines.extend(f"  {line}" for line in recent_lines)
        lines.append("")

    if snapshot.total_market_value_amount is not None and snapshot.unrealized_pnl_amount is not None:
        total_cost = float(snapshot.total_cost_amount)
        total_market_value = float(snapshot.total_market_value_amount)
        total_pnl = float(snapshot.unrealized_pnl_amount)
        total_pnl_pct = (total_pnl / total_cost * 100) if total_cost else 0.0
        lines.append("━━━━━━━━━━━━━━")
        lines.append(f"💼 组合总成本: ¥{total_cost:,.2f}")
        lines.append(f"💰 组合总市值: ¥{total_market_value:,.2f}")
        lines.append(f"📈 总浮动盈亏: ¥{total_pnl:+,.2f}（{total_pnl_pct:+.2f}%）")

    return "\n".join(lines)


if __name__ == "__main__":
    _refresh_portfolio_nav()
    print(generate_report())
