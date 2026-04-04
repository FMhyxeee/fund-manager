# Fund Manager

Personal, self-hosted, agent-driven fund portfolio review and strategy assistant.

`fund-manager` 是一个以确定性账本为核心、以 Agent 为分析层的个人基金组合管理系统。
它的定位是决策支持，不是自动交易。

## 当前状态

截至当前仓库版本，已经落地的主线能力包括：

- 基金主数据、交易、持仓 lot、净值快照、组合快照、报告、策略提案等持久化模型
- 持仓 CSV / 交易 CSV 导入，支持 `dry_run`
- AKShare 适配器，支持基金资料和净值历史读取
- 每日持仓基金数据同步：刷新 `fund_master` 基础资料并增量写入 `nav_snapshot`
- 确定性的组合快照和组合指标计算
- 每日快照任务、每周复盘工作流、每月策略辩论工作流
- FastAPI API、HTML Dashboard、可选 MCP 只读服务

README 只描述当前已实现内容；产品规划和历史文档见 [`doc/`](./doc)。

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
  - `weekly_review`: 生成结构化周报并持久化
  - `monthly_strategy_debate`: Strategy / Challenger / Judge 三方辩论并保存结论
- **接口层**
  - REST API
  - HTML Dashboard
  - 可选 MCP 服务，提供只读查询和模型组合模拟

## 系统结构

```text
fund-manager/
├─ src/fund_manager/
│  ├─ apps/api/          FastAPI 路由与 Dashboard
│  ├─ core/domain/       纯计算逻辑
│  ├─ core/services/     组合统计、基金同步等确定性服务
│  ├─ data_adapters/     AKShare 与 CSV 导入适配器
│  ├─ storage/           SQLAlchemy 模型、Repo、Alembic
│  ├─ agents/            Agent runtime、tools、workflows、prompts
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
| `GET` | `/api/v1/funds/{fund_code}` | 基金基础资料 |
| `GET` | `/api/v1/reports` | 周报列表 |
| `POST` | `/api/v1/imports/holdings` | 导入持仓 CSV |
| `POST` | `/api/v1/imports/transactions` | 导入交易 CSV |
| `POST` | `/api/v1/workflows/weekly-review/run` | 手动触发周报 |

当前尚未开放为 REST 端点、但代码中已有能力的内容：

- monthly strategy debate 的 HTTP 触发入口
- fund search / NAV history 的 HTTP 查询入口
- daily sync 的独立 HTTP 触发入口

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

当前 MCP tools：

- `portfolio_list`
- `portfolio_snapshot`
- `portfolio_positions`
- `portfolio_valuation_history`
- `portfolio_metrics`
- `fund_profile`
- `fund_nav_history`
- `simulate_model_portfolio`

## 主要工作流

### Daily

1. 找出当前组合的有效持仓基金
2. 用 AKShare 刷新基金基础资料
3. 增量写入最新净值到 `nav_snapshot`
4. 保存当日 `portfolio_snapshot`

### Weekly Review

1. 汇总组合事实和估值历史
2. 调用 ReviewAgent 产出结构化周报
3. 渲染 markdown 并持久化到 `review_report`

### Monthly Strategy Debate

1. 整理结构化事实
2. `StrategyAgent` 提建议
3. `ChallengerAgent` 提反驳
4. `JudgeAgent` 定稿
5. 持久化到 `strategy_proposal` 和 `agent_debate_log`

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
