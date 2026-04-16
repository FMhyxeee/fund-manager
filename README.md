# Fund Manager

Personal, self-hosted investment domain kernel for fund portfolio tracking, review, and policy-backed decision support.

`fund-manager` 是一个以确定性投资真相为核心、以 AI 作为可替换分析层的个人基金组合系统。
它的定位是决策支持，不是自动交易，也不是以 prompt 为中心的 agent 壳。

## 当前状态

截至当前仓库版本，已经落地的主线能力包括：

- 基金主数据、交易、持仓 lot、净值快照、组合快照、报告、策略提案等持久化模型
- 持仓 CSV / 交易 CSV 导入，支持 `dry_run`
- AKShare 适配器，支持基金资料和净值历史读取
- 每日持仓基金数据同步：刷新 `fund_master` 基础资料并增量写入 `nav_snapshot`
- 确定性的组合快照和组合指标计算
- 每日快照任务、每日决策工作流、每周复盘工作流、每月策略辩论工作流
- FastAPI API、HTML Dashboard、可选 MCP read-mostly 服务，以及受控的 append-only 交易写入口
- 已分离的 typed contract
  - `src/fund_manager/core/fact_packs.py`
  - `src/fund_manager/core/ai_artifacts.py`
  - `src/fund_manager/agents/runtime/contracts.py`
  - `src/fund_manager/agents/runtime/shared.py`

README 只描述当前已实现内容；产品规划、历史文档和系统边界说明见 [`doc/`](./doc)。

## 核心能力

- **确定性组合统计**
  - 基于 `position_lot` 和 `nav_snapshot` 计算持仓、市值、浮盈亏、权重、日/周/月收益、区间收益、最大回撤
  - 对缺失净值显式标记，不会 silently 当作 0
- **基金数据同步**
  - 通过 AKShare 获取基金公开资料和净值历史
  - 每日只针对当前持仓基金做增量同步
  - 当前落库重点是 `fund_master` 和 `nav_snapshot`
- **导入与留痕**
  - 导入初始化持仓
  - 导入交易流水
  - 交易、快照、报告、策略提案、事件日志均保留历史记录
- **工作流**
  - `daily_snapshot`: 先同步基金数据，再保存组合快照
  - `daily_decision`: 基于 active policy 生成确定性决策和动作建议
  - `weekly_review`: 生成结构化周报并持久化
  - `monthly_strategy_debate`: Strategy / Challenger / Judge 三方辩论并保存结论
- **契约分层**
  - canonical facts、deterministic decisions、research signals、AI artifacts、human feedback 分层明确
  - workflow 先组装 Fact Pack，再调用 runtime，最后 append-only 持久化 artifact
- **接口层**
  - REST API
  - HTML Dashboard
  - 可选 MCP 服务，提供只读查询、模型组合模拟，以及 OpenClaw 可调用的受控交易追加工具

## 系统结构

```text
fund-manager/
├─ src/fund_manager/
│  ├─ apps/api/          FastAPI 路由与 Dashboard
│  ├─ core/domain/       纯计算逻辑
│  ├─ core/services/     组合统计、基金同步、决策与对账等确定性服务
│  ├─ core/fact_packs.py AI 输入的 deterministic facts contract
│  ├─ core/ai_artifacts.py AI 输出的 typed artifact contract
│  ├─ data_adapters/     AKShare 与 CSV 导入适配器
│  ├─ storage/           SQLAlchemy 模型、Repo、Alembic
│  ├─ agents/tools/      内部 typed tools
│  ├─ agents/workflows/  workflow orchestration 与 artifact 持久化
│  ├─ agents/runtime/    runtime protocol、shared helper、manual adapter
│  ├─ agents/prompts/    prompt 模板
│  ├─ scheduler/         日 / 周 / 月任务
│  └─ mcp/               可选 MCP 传输层
├─ scripts/              批量导入和日报脚本
├─ tests/                单元测试与集成测试
└─ doc/                  蓝图、架构、技术文档、维护提示词
```

## 安装

### 1. 基础安装

```bash
git clone <your-repo-url>
cd fund-manager
uv sync --extra dev --extra data
```

如果不用 `uv`，也可以：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev,data]"
```

### 2. 可选 MCP 依赖

如果需要 MCP 服务，再安装：

```bash
uv sync --extra mcp
```

或：

```bash
pip install -e ".[mcp]"
```

## 初始化数据库

```bash
uv run alembic upgrade head
```

默认 SQLite 数据库位于 `./data/fund_manager.db`。
如果配置 `DATABASE_URL=sqlite:///./...`，目录会自动创建。

## 常用命令

### 启动 API

```bash
uv run fund-manager-api
```

或：

```bash
uv run uvicorn fund_manager.apps.api.main:app --reload
```

默认访问地址：

- API Docs: `http://127.0.0.1:8000/api/v1/docs`
- OpenAPI: `http://127.0.0.1:8000/api/v1/openapi.json`
- Dashboard: `http://127.0.0.1:8000/api/v1/dashboard`

### 运行 Scheduler

```bash
uv run fund-manager-scheduler daily --portfolio-id 1
uv run fund-manager-scheduler weekly --portfolio-id 1
uv run fund-manager-scheduler monthly --portfolio-id 1
```

常用可选参数：

- `--as-of-date YYYY-MM-DD`
- `--job-name daily_snapshot|weekly_review|monthly_strategy_debate`

### 运行 Admin CLI

```bash
uv run fund-manager-admin policy show --portfolio-id 1 --as-of-date 2026-04-12
uv run fund-manager-admin decision run --portfolio-id 1 --decision-date 2026-04-12
uv run fund-manager-admin decision feedback --decision-run-id 1 --action-index 0 --feedback-status executed
uv run fund-manager-admin workflow run daily-snapshot --portfolio-id 1 --as-of-date 2026-04-12
uv run fund-manager-admin workflow run weekly-review --portfolio-id 1 --period-end 2026-04-12
uv run fund-manager-admin workflow run monthly-strategy-debate --portfolio-id 1 --period-end 2026-04-12
```

用途定位：

- `fund-manager-scheduler`: 频率驱动 job 触发
- `fund-manager-admin`: 动作驱动 domain command，适合同机自动化、OpenClaw 编排和人工排障

### 运行脚本

```bash
uv run python scripts/import_all_funds.py
uv run python scripts/import_all_nav_history.py
uv run python scripts/portfolio_daily_report.py
```

脚本定位：

- `import_all_funds.py`: 一次性批量导入基金主数据
- `import_all_nav_history.py`: 批量回填基金净值历史
- `portfolio_daily_report.py`: 基于本地 canonical 数据生成每日持仓报告

## REST API

当前实际提供的 REST 端点如下：

| Method | Path | 说明 |
| --- | --- | --- |
| `GET` | `/api/v1/health` | 健康检查 |
| `GET` | `/api/v1/dashboard` | HTML Dashboard |
| `GET` | `/api/v1/portfolios` | 组合列表 |
| `GET` | `/api/v1/portfolios/{portfolio_id}/snapshot` | 组合快照 |
| `GET` | `/api/v1/portfolios/{portfolio_id}/positions` | 持仓明细 |
| `GET` | `/api/v1/portfolios/{portfolio_id}/metrics` | 组合指标 |
| `GET` | `/api/v1/portfolios/{portfolio_id}/valuation-history` | 组合估值历史 |
| `GET` | `/api/v1/portfolios/{portfolio_id}/latest-report` | 最新周报详情 |
| `GET` | `/api/v1/portfolios/{portfolio_id}/latest-strategy-proposal` | 最新策略提案详情 |
| `GET` | `/api/v1/funds/{fund_code}` | 基金基础资料 |
| `GET` | `/api/v1/funds/{fund_code}/nav-history` | 基金净值历史 |
| `GET` | `/api/v1/policies/active` | 生效中的组合 policy |
| `POST` | `/api/v1/policies` | append-only 创建 policy |
| `GET` | `/api/v1/decisions` | 决策记录列表 |
| `GET` | `/api/v1/decisions/{decision_run_id}` | 单条决策详情 |
| `POST` | `/api/v1/decisions/{decision_run_id}/feedback` | 决策动作反馈 |
| `GET` | `/api/v1/decisions/{decision_run_id}/feedback` | 决策反馈历史 |
| `GET` | `/api/v1/reports` | 周报列表 |
| `GET` | `/api/v1/reports/{report_id}` | 周报详情 |
| `GET` | `/api/v1/strategy-proposals/{proposal_id}` | 策略提案详情 |
| `POST` | `/api/v1/imports/holdings` | 导入持仓 CSV |
| `POST` | `/api/v1/imports/transactions` | 导入交易 CSV |
| `POST` | `/api/v1/workflows/daily-snapshot/run` | 手动触发日快照 |
| `POST` | `/api/v1/workflows/daily-decision/run` | 手动触发日决策 |
| `POST` | `/api/v1/workflows/weekly-review/run` | 手动触发周报 |
| `POST` | `/api/v1/workflows/monthly-strategy-debate/run` | 手动触发月度策略辩论 |

## Dashboard

Dashboard 当前展示：

- 默认组合的汇总统计
- 当前持仓表格
- 缺失净值告警
- 最近的报告记录

模板位于 [`dashboard.html`](./src/fund_manager/apps/api/templates/dashboard.html)。

## MCP 服务

安装 `mcp` extra 后可启动：

```bash
uv run fund-manager-mcp
```

MCP 的定位是 read-mostly transport。唯一当前允许的写能力是 `transaction_append`：它只用于记录操作者已经确认的实际交易，写入 `transaction` 后由确定性服务重建 transaction-backed `position_lot`，并尝试与已记录的执行反馈做 `decision_transaction_link` 对账。它不是自动下单接口，也不会替代人工执行判断。

当前 MCP tools：

- `portfolio_list`
- `portfolio_snapshot`
- `portfolio_positions`
- `portfolio_valuation_history`
- `portfolio_metrics`
- `portfolio_active_policy`
- `fund_profile`
- `fund_nav_history`
- `decision_run_list`
- `decision_run_get`
- `decision_feedback_list`
- `review_report_get`
- `transaction_list`
- `transaction_get`
- `transaction_append`
- `watchlist_candidates`
- `watchlist_candidate_fit`
- `watchlist_style_leaders`
- `polymarket_search_events`
- `polymarket_estimate_time`
- `simulate_model_portfolio`

`transaction_append` 常用参数：

- `portfolio_id` 或 `portfolio_name`：二选一，用于定位组合
- `fund_code` / `fund_name`：基金代码；新基金必须显式传入 `fund_name`
- `trade_date`：ISO 日期，例如 `2026-04-16`
- `trade_type`：`buy`、`sell`、`dividend`、`convert_in`、`convert_out` 或 `adjust`
- `units`、`gross_amount`、`fee_amount`、`nav_per_unit`：建议以字符串传入，避免浮点精度问题
- `external_reference`、`source_reference`、`note`：用于人工执行留痕和后续排障

OpenClaw 可以调用这些 MCP tools 查询事实和记录人工确认后的交易，但不应直接连接数据库，也不应把 AI 建议本身当成交易事实。

当前内部 typed tools 还包括：

- `get_portfolio_metrics`
- `get_portfolio_valuation_history`
- `get_active_policy`
- `run_daily_decision`
- `get_decision_run`
- `record_decision_feedback`

## 主要工作流

核心原则：

1. 先有 deterministic fact pack，再有 AI narrative。
2. AI artifact 不能替代 canonical facts 或 deterministic decision。
3. 人工反馈与交易回挂是执行真相，不能从 AI 建议中自动推断。

### Daily

1. 找出当前组合的有效持仓基金
2. 用 AKShare 刷新基金基础资料
3. 增量写入最新净值到 `nav_snapshot`
4. 保存当日 `portfolio_snapshot`

### Daily Decision

1. 读取 active policy 和组合快照
2. 运行确定性 band / target 评估
3. 生成 append-only `decision_run`
4. 如有人类操作，再通过 `decision_feedback` 和 `decision_transaction_link` 留痕

### Weekly Review

1. 汇总组合事实和估值历史
2. 组装 `WeeklyReviewFacts`
3. 调用 runtime 生成 `ReviewAgentOutput`
4. 渲染 markdown 并持久化到 `review_report`

### Monthly Strategy Debate

1. 整理结构化事实并组装 `StrategyDebateFacts`
2. `StrategyAgent` 提建议
3. `ChallengerAgent` 提反驳
4. `JudgeAgent` 定稿
5. 持久化结构化 AI artifacts、`strategy_proposal` 和 `agent_debate_log`

## Runtime 结构

当前 in-repo runtime 的定位是“最小桥接层”，不是领域真相层：

- `agents/runtime/contracts.py`
  - `ReviewAgent`
  - `StrategyAgent`
  - `ChallengerAgent`
  - `JudgeAgent`
- `agents/runtime/shared.py`
  - `PromptDefinition`
  - prompt 加载
  - manual runtime 的轻量格式化 helper
- `agents/runtime/*_agent.py`
  - 仅保留 manual runtime 实现

生产级 model routing、provider 选择、外部搜索、渠道交互，应该放在 `OpenClaw` 或其他外部 orchestration runtime。

## 测试与质量

当前仓库可收集到 `133` 个测试用例。

```bash
make install
make format
make lint
make typecheck
make test
make check
```

等价命令见 [`Makefile`](./Makefile)。

## 文档索引

- [`doc/01-蓝图.md`](./doc/01-蓝图.md): 产品目标、范围与当前状态
- [`doc/02-高阶方案.md`](./doc/02-高阶方案.md): 架构与主流程
- [`doc/03-技术文档.md`](./doc/03-技术文档.md): 技术结构、接口与运行方式
- [`doc/04-仓库初始化清单.md`](./doc/04-仓库初始化清单.md): bootstrap 记录与完成情况
- [`doc/05-Codex启动提示词.md`](./doc/05-Codex启动提示词.md): 给工程代理用的维护提示词

## 设计原则

1. 确定性优先，LLM 不参与权威账本计算。
2. 历史记录 append-only，可审计、可回放。
3. Agent 负责解释、复盘、挑战和建议，不直接执行交易。
4. 对外部数据源做适配和标准化，不把第三方字段形状泄漏到领域层。

## License

Proprietary，个人使用。
