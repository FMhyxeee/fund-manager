# Fund Manager

Personal, self-hosted, agent-driven fund portfolio review and strategy assistant.

一个基于确定性会计核心 + AI Agent 驱动的基金组合管理系统。自动采集基金净值数据，生成持仓分析报告，并通过多 Agent 策略辩论辅助投资决策。

> ⚠️ 这是决策支持系统，**不是**自动交易系统。

## ✨ 功能特性

- **📋 基金主数据管理** — 26,000+ 只公募基金信息，通过 AKShare 自动采集
- **📈 净值历史追踪** — 自动拉取并存储基金 NAV 历史，支持批量导入
- **💼 持仓与交易记录** — CSV 导入或手动录入，append-only 不可篡改
- **📊 确定性组合指标** — 收益率、波动率、夏普比率、最大回撤等
- **🤖 Agent 驱动的周报** — 单 Agent 一键生成持仓分析周报
- **⚔️ 多 Agent 策略辩论** — StrategyAgent → ChallengerAgent → JudgeAgent 三方辩论
- **⏰ 定时任务** — 内置 Scheduler，支持每日/每周/每月自动任务
- **🌐 REST API** — FastAPI 驱动的 8 个 API 端点
- **🖥️ Web Dashboard** — Jinja2 模板渲染，支持亮/暗主题

## 🏗️ 系统架构

```
┌─────────────────────────────────────────────────┐
│                   Web Dashboard                  │
├─────────────────────────────────────────────────┤
│                   REST API (FastAPI)              │
├────────────┬────────────┬───────────────────────┤
│  Scheduler  │   Agents   │     Reports           │
│  (cron)     │  (LLM)     │   (PDF/MD)            │
├────────────┴────────────┴───────────────────────┤
│            Core Services (metrics, snapshots)     │
├─────────────────────────────────────────────────┤
│      SQLAlchemy + Alembic (SQLite / PostgreSQL)   │
├─────────────────────────────────────────────────┤
│         AKShare Data Adapter (26k+ funds)         │
└─────────────────────────────────────────────────┘
```

## 📦 技术栈

| 组件 | 技术 |
|------|------|
| 语言 | Python 3.12+ |
| Web 框架 | FastAPI + Uvicorn |
| ORM | SQLAlchemy 2.0 |
| 数据库迁移 | Alembic |
| 数据源 | AKShare |
| 任务调度 | 内置 Scheduler |
| Agent | Strategy / Challenger / Judge 多 Agent |
| 模板 | Jinja2 (Dashboard) |
| 测试 | pytest (122 tests) |

## 🚀 快速开始

### 1. 安装

```bash
git clone https://github.com/FMhyxeee/fund-manager.git
cd fund-manager
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,data]"
```

### 2. 初始化数据库

```bash
cd src/fund_manager/storage
alembic upgrade head
```

### 3. 导入基金数据

```bash
# 导入全部基金主数据（约 26,000 只）
PYTHONPATH=src python scripts/import_all_funds.py

# 导入单只基金 NAV 历史
PYTHONPATH=src python -c "
from fund_manager.data_adapters.akshare_adapter import AkshareFundDataAdapter
adapter = AkshareFundDataAdapter()
nav = adapter.get_fund_nav_history('012348')
print(f'共 {len(nav.points)} 条记录')
"

# 批量导入所有基金 30 天 NAV（耗时约 1 小时）
PYTHONPATH=src python scripts/import_all_nav_history.py
```

### 4. 启动 API 服务

```bash
PYTHONPATH=src uvicorn fund_manager.apps.api.main:app --reload --port 8000
```

访问：
- API 文档: http://localhost:8000/docs
- Dashboard: http://localhost:8000/dashboard

### 5. 录入持仓

```bash
PYTHONPATH=src python -c "
from sqlalchemy import create_engine, text
from datetime import date

engine = create_engine('sqlite:///data/fund_manager.db')
with engine.connect() as c:
    # 创建组合
    c.execute(text(\"\"\"INSERT INTO portfolio (portfolio_code, portfolio_name, base_currency_code, is_default, created_at, updated_at)
        VALUES ('DEFAULT', '我的组合', 'CNY', 1, datetime('now'), datetime('now'))\"\"\"))
    # 买入记录
    c.execute(text(\"\"\"INSERT INTO \\\"transaction\\\"
        (portfolio_id, fund_id, trade_date, trade_type, units, gross_amount, nav_per_unit, source_name, note, created_at)
        VALUES (1, (SELECT id FROM fund_master WHERE fund_code='012348'),
        '2026-04-02', 'buy', 56544.13, 36617.98, 0.6476, 'manual', '分笔买入', datetime('now'))\"\"\"))
    c.commit()
"
```

## 📊 API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/v1/health` | 健康检查 |
| GET | `/api/v1/funds/search?q=恒生科技` | 基金搜索 |
| GET | `/api/v1/funds/{fund_code}/profile` | 基金详情 |
| GET | `/api/v1/funds/{fund_code}/nav?days=30` | 净值历史 |
| POST | `/api/v1/imports/holdings` | 导入持仓 CSV |
| POST | `/api/v1/imports/transactions` | 导入交易 CSV |
| GET | `/api/v1/portfolios/{id}/snapshot?as_of_date=2026-04-02` | 组合快照 |
| POST | `/api/v1/workflows/weekly-review` | 触发周报 |
| POST | `/api/v1/workflows/strategy-debate` | 触发策略辩论 |

## 🤖 Agent 工作流

### 周报生成

```python
from fund_manager.agents.runtime.strategy_agent import StrategyAgent

agent = StrategyAgent(db_session)
report = agent.run_weekly_review(portfolio_id=1, as_of_date="2026-04-02")
```

### 策略辩论

三方辩论流程：

```
StrategyAgent (提出建议)
    ↓
ChallengerAgent (质疑方案)
    ↓
JudgeAgent (综合评判)
    ↓
最终策略报告
```

辩论过程完整记录在 `agent_debate_log` 表中，可追溯审计。

## 📂 项目结构

```
fund-manager/
├── src/fund_manager/
│   ├── apps/
│   │   └── api/           # FastAPI 路由、模板、依赖注入
│   ├── core/              # 领域模型、配置
│   ├── data_adapters/     # AKShare 数据适配器
│   ├── storage/           # SQLAlchemy 模型、Repo、Alembic 迁移
│   ├── agents/            # Agent prompts、tools、workflows、runtime
│   ├── scheduler/         # 定时任务（日/周/月）
│   └── reports/           # 报告生成
├── tests/
│   ├── unit/              # 单元测试
│   └── integration/       # 集成测试
├── scripts/               # 运维脚本
│   ├── import_all_funds.py
│   ├── import_all_nav_history.py
│   └── portfolio_daily_report.py
├── doc/                   # 设计文档
├── data/                  # SQLite 数据库
└── alembic/               # 数据库迁移
```

## 🧪 测试

```bash
PYTHONPATH=src pytest -v        # 运行全部 122 个测试
PYTHONPATH=src pytest tests/unit/    # 仅单元测试
PYTHONPATH=src pytest tests/integration/  # 仅集成测试
```

## 📋 定时报告

系统内置每日持仓报告脚本，可配合 OpenClaw cron 使用：

```bash
# 手动运行
PYTHONPATH=src python scripts/portfolio_daily_report.py
```

输出示例：

```
📊 每日持仓报告

🔴 天弘恒生科技ETF联接A（012348）
份额: 56,544.13 ｜ 成本: ¥36,617.98（¥0.6476/份）
最新净值: ¥0.6476（2026-04-02）
市值: ¥36,617.98 ｜ 浮动盈亏: ¥-0.00（-0.00%）
近30日波动率: 27.0% ｜ 近30日收益: -13.89%
近5日走势:
  2026-04-02 0.6476 (-1.77%)
  2026-04-01 0.6593 (+1.93%)
  2026-04-01 0.6468 (-0.92%)
  ...

━━━━━━━━━━━━━━
💼 组合总成本: ¥36,617.98
💰 组合总市值: ¥36,617.98
📈 总浮动盈亏: ¥-0.00（-0.00%）
```

## 🔧 设计原则

1. **确定性优先** — 所有会计指标基于持久化数据确定性地计算，不存在幻觉
2. **Append-Only 历史** — 交易记录和快照不可修改，保证审计完整性
3. **Agent 解释而非替代** — AI Agent 提供建议和挑战，不执行交易
4. **数据自托管** — 所有数据存储在本地 SQLite，不依赖第三方 SaaS

## 📄 License

Proprietary — 个人使用
