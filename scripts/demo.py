#!/usr/bin/env python3
"""
Fund Manager Demo — 一键演示系统核心功能
运行: PYTHONPATH=src python scripts/demo.py
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

import numpy as np
from datetime import date, timedelta
from sqlalchemy import text

from fund_manager.core.config import get_settings
from fund_manager.core.services.portfolio_service import PortfolioService
from fund_manager.storage.db import get_engine, get_session_factory

engine = get_engine()
DATABASE_URL = get_settings().database_url
DB_PATH = (
    DATABASE_URL.removeprefix("sqlite:///./")
    if DATABASE_URL.startswith("sqlite:///./")
    else DATABASE_URL.removeprefix("sqlite:///")
)

BANNER = """
╔══════════════════════════════════════════════╗
║        Fund Manager v0.1.0 — Demo            ║
║   Agent-Driven Fund Portfolio System         ║
╚══════════════════════════════════════════════╝
"""

DIVIDER = "\n" + "─" * 50 + "\n"


def step(title: str):
    print(f"\n{'━' * 50}")
    print(f"  {title}")
    print(f"{'━' * 50}")


def _normalize_daily_return_ratio(value) -> float | None:
    """Handle legacy rows that stored percentage points instead of ratios."""
    if value is None:
        return None
    normalized = float(value)
    return normalized / 100 if abs(normalized) > 0.2 else normalized


def demo_fund_search():
    """演示基金搜索"""
    step("🔍 基金搜索")
    keywords = ["恒生科技", "茅台", "新能源", "半导体"]
    with engine.connect() as c:
        for kw in keywords:
            rows = c.execute(
                text("SELECT fund_code, fund_name FROM fund_master WHERE fund_name LIKE :kw LIMIT 3"),
                {"kw": f"%{kw}%"},
            ).fetchall()
            print(f"\n  搜索 '{kw}' — 找到相关基金:")
            for r in rows:
                print(f"    {r[0]}  {r[1]}")
            if not rows:
                print(f"    (无结果)")


def demo_nav_history():
    """演示净值查询与分析"""
    step("📈 净值历史分析 — 天弘恒生科技ETF联接A（012348）")
    
    fund_code = "012348"
    with engine.connect() as c:
        info = c.execute(
            text("SELECT fund_code, fund_name FROM fund_master WHERE fund_code=:fc"),
            {"fc": fund_code},
        ).fetchone()
        
        rows = c.execute(
            text("SELECT nav_date, unit_nav_amount, daily_return_ratio FROM nav_snapshot "
                 "WHERE fund_id=(SELECT id FROM fund_master WHERE fund_code=:fc) "
                 "ORDER BY nav_date"),
            {"fc": fund_code},
        ).fetchall()

    if not rows:
        print("  ⚠️ 无 NAV 数据，请先运行 import_all_nav_history.py")
        return

    navs = np.array([float(r[1]) for r in rows])
    returns = np.array(
        [
            normalized
            for _, _, raw_ratio in rows[1:]
            if (normalized := _normalize_daily_return_ratio(raw_ratio)) is not None
        ]
    )

    print(f"\n  基金: {info[1]}（{info[0]}）")
    print(f"  数据: {rows[0][0]} ~ {rows[-1][0]}（{len(rows)} 个交易日）")
    print(f"  最新净值: {navs[-1]:.4f}")
    print(f"  成立以来: {(navs[-1] / navs[0] - 1) * 100:+.2f}%")

    # 分阶段收益
    print(f"\n  分阶段收益:")
    for label, days in [("近1周", 5), ("近1月", 22), ("近3月", 66), ("近1年", 252)]:
        if len(navs) >= days:
            r = (navs[-1] / navs[-days] - 1) * 100
            emoji = "🟢" if r > 0 else "🔴"
            print(f"    {emoji} {label}: {r:+.2f}%")

    # 风险指标
    ann_vol = np.std(returns) * np.sqrt(252) * 100
    ann_ret = np.mean(returns) * 252 * 100
    sharpe = (ann_ret - 2.0) / ann_vol if ann_vol > 0 else 0
    peak = np.maximum.accumulate(navs)
    dd = (navs - peak) / peak
    max_dd = dd.min() * 100

    print(f"\n  风险指标:")
    print(f"    年化波动率: {ann_vol:.2f}%")
    print(f"    年化收益: {ann_ret:.2f}%")
    print(f"    夏普比率: {sharpe:.2f}")
    print(f"    最大回撤: {max_dd:.2f}%")


def demo_portfolio_snapshot():
    """演示组合快照"""
    step("💼 持仓组合快照")
    session = get_session_factory()()
    try:
        snapshot = PortfolioService(session).assemble_portfolio_snapshot(
            1,
            as_of_date=date.today(),
        )
    finally:
        session.close()

    if not snapshot.positions:
        print("  ⚠️ 无持仓记录")
        print("  提示: 运行以下命令录入示例持仓:")
        print('    PYTHONPATH=src python scripts/demo.py --setup')
        return

    for position in snapshot.positions:
        if position.latest_nav_per_unit is None or position.current_value_amount is None:
            continue
        units = float(position.units)
        cost = float(position.total_cost_amount)
        nav = float(position.latest_nav_per_unit)
        value = float(position.current_value_amount)
        pnl = float(position.unrealized_pnl_amount or 0)
        pnl_pct = (pnl / cost * 100) if cost > 0 else 0
        emoji = "🔴" if pnl < 0 else "🟢"

        print(f"\n  {emoji} {position.fund_name}（{position.fund_code}）")
        print(f"    份额: {units:,.2f}")
        print(f"    成本: ¥{cost:,.2f}（¥{float(position.average_cost_per_unit):.4f}/份）")
        print(f"    净值: ¥{nav:.4f}（{position.latest_nav_date}）")
        print(f"    市值: ¥{value:,.2f}")
        print(f"    盈亏: ¥{pnl:+,.2f}（{pnl_pct:+.2f}%）")

    if snapshot.total_market_value_amount is not None and snapshot.unrealized_pnl_amount is not None:
        total_cost = float(snapshot.total_cost_amount)
        total_value = float(snapshot.total_market_value_amount)
        total_pnl = float(snapshot.unrealized_pnl_amount)
        total_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
        emoji = "🔴" if total_pnl < 0 else "🟢"
        print(f"\n  {'━' * 40}")
        print(f"  {emoji} 组合总计")
        print(f"    总成本: ¥{total_cost:,.2f}")
        print(f"    总市值: ¥{total_value:,.2f}")
        print(f"    总盈亏: ¥{total_pnl:+,.2f}（{total_pct:+.2f}%）")


def demo_db_stats():
    """演示数据库统计"""
    step("📊 数据库统计")
    with engine.connect() as c:
        funds = c.execute(text("SELECT count(*) FROM fund_master")).scalar()
        nav = c.execute(text("SELECT count(*) FROM nav_snapshot")).scalar()
        tx = c.execute(text("SELECT count(*) FROM \"transaction\"")).scalar()
        portfolios = c.execute(text("SELECT count(*) FROM portfolio")).scalar()

    print(f"\n  基金主数据: {funds:,} 只")
    print(f"  NAV 记录:   {nav:,} 条")
    print(f"  交易记录:   {tx} 笔")
    print(f"  投资组合:   {portfolios} 个")


def setup_demo_data():
    """创建演示数据"""
    step("🔧 创建演示数据")

    with engine.connect() as c:
        # 检查是否已有数据
        existing = c.execute(text("SELECT count(*) FROM portfolio")).scalar()
        if existing > 0:
            print("  已有持仓数据，跳过")
            return

        # 创建组合
        c.execute(text("""INSERT INTO portfolio (portfolio_code, portfolio_name, base_currency_code, is_default, created_at, updated_at)
            VALUES ('DEFAULT', '我的组合', 'CNY', 1, datetime('now'), datetime('now'))"""))

        # 买入 012348 恒生科技
        c.execute(text("""INSERT INTO "transaction"
            (portfolio_id, fund_id, trade_date, trade_type, units, gross_amount, nav_per_unit, source_name, note, created_at)
            VALUES (1, (SELECT id FROM fund_master WHERE fund_code='012348'),
            '2026-04-02', 'buy', 56544.13, 36617.98, 0.6476, 'demo', '演示数据', datetime('now'))"""))
        c.execute(text("""INSERT INTO position_lot
            (portfolio_id, fund_id, source_transaction_id, run_id, lot_key, opened_on, as_of_date, remaining_units, average_cost_per_unit, total_cost_amount, created_at)
            VALUES (1, (SELECT id FROM fund_master WHERE fund_code='012348'), 1, 'demo-bootstrap', 'tx:1', '2026-04-02', '2026-04-02', 56544.13, 0.6476, 36617.98, datetime('now'))"""))

        c.commit()
        print("  ✅ 已创建演示持仓: 天弘恒生科技ETF联接A（012348）")
        print("     56,544.13 份 / 成本 ¥36,617.98")


def main():
    print(BANNER)

    if "--setup" in sys.argv:
        setup_demo_data()
        return

    # 检查数据库
    if not os.path.exists(DB_PATH):
        print("⚠️ 数据库不存在，请先运行:")
        print("  cd src/fund_manager/storage && alembic upgrade head")
        print("  PYTHONPATH=src python scripts/import_all_funds.py")
        return

    demo_db_stats()
    demo_fund_search()
    demo_nav_history()
    demo_portfolio_snapshot()

    print(DIVIDER)
    print("  Demo 完成！")
    print("  启动 API: PYTHONPATH=src uvicorn fund_manager.apps.api.main:app --reload")
    print("  查看文档: http://localhost:8000/docs")
    print("  Dashboard: http://localhost:8000/dashboard")


if __name__ == "__main__":
    main()
