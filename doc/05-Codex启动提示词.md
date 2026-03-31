# 05-Codex 启动提示词

本文件用于给 Codex 提供一组可直接复制使用的启动提示词（prompts）。

目标：让 Codex 在本仓库中按正确顺序工作，优先完成基础设施、账本内核、数据适配、workflow 和测试。

使用原则：
- 每次只给 Codex 一个清晰目标。
- 优先让 Codex 读 `AGENTS.md` 和 `docs/`。
- 先要求它输出计划，再开始修改文件。
- 对账本、收益率、回撤、导入逻辑必须要求测试。
- 不要一上来让 Codex 同时做前后端和多 agent。

---

## 1. 仓库初始化提示词

```text
Read AGENTS.md and all files under docs/ first.
Then bootstrap this repository for a Python 3.12 project.

Requirements:
- create a clean package structure based on the documented architecture
- initialize pyproject.toml
- configure Ruff, pytest, and mypy
- add .env.example
- add a minimal FastAPI app scaffold
- add a Makefile or equivalent developer commands
- do not implement business logic yet
- summarize the created files and explain why each exists
```

---

## 2. 数据库模型初始化提示词

```text
Read AGENTS.md and docs/ first.
Implement the first version of the persistence layer using SQLAlchemy 2.x and Alembic.

Create models and initial migration for:
- fund_master
- portfolio
- position_lot
- transaction
- nav_snapshot
- portfolio_snapshot
- review_report
- strategy_proposal
- agent_debate_log
- system_event_log

Requirements:
- use typed SQLAlchemy models
- preserve append-only historical truth where applicable
- include indexes for common lookup paths
- keep naming explicit and stable
- add tests for model creation and migration smoke checks
- provide a short schema rationale after implementation
```

---

## 3. 持仓导入器提示词

```text
Read AGENTS.md and docs/ first.
Implement the first version of import_holdings.py.

Input format:
fund_code,fund_name,units,avg_cost,total_cost,portfolio_name

Requirements:
- validate required fields
- normalize numeric precision safely
- support dry-run mode
- create or reuse the target portfolio
- upsert or append according to repository rules, but do not destroy historical truth
- produce a clear import summary
- add unit tests and fixture-based tests
- document assumptions in code comments and README if necessary
```

---

## 4. 交易流水导入器提示词

```text
Read AGENTS.md and docs/ first.
Implement import_transactions.py for personal fund transactions.

Requirements:
- support buy, sell, dividend, convert_in, convert_out, adjust
- validate date, amount, units, and trade_type
- preserve source metadata and notes
- reject invalid rows with actionable error messages
- support dry-run mode
- generate an import report
- add tests for happy path and malformed input cases
```

---

## 5. AKShare 适配器提示词

```text
Read AGENTS.md and docs/ first.
Implement akshare_adapter.py for public fund data.

Initial capabilities:
- search_fund
- get_fund_profile
- get_fund_nav_history

Requirements:
- isolate AKShare-specific details in the adapter layer
- return normalized internal DTOs instead of raw third-party payloads
- handle empty or partial results gracefully
- add retry-safe behavior where reasonable
- add tests using mocks, not live network calls
- explain extension points for future fund-related endpoints
```

---

## 6. 核心指标计算提示词

```text
Read AGENTS.md and docs/ first.
Implement core portfolio metrics in core/domain/metrics.py and related services.

Metrics to implement first:
- current_value
- unrealized_pnl
- weight
- daily_return
- period_return
- max_drawdown

Requirements:
- deterministic logic only
- pure functions where possible
- explicit handling for missing NAV values
- clear separation between domain logic and persistence access
- comprehensive unit tests with edge cases
- include a short note on accounting assumptions
```

---

## 7. 组合服务提示词

```text
Read AGENTS.md and docs/ first.
Implement the first version of portfolio_service.py and analytics_service.py.

Requirements:
- expose application-level methods to assemble portfolio snapshots
- compute metrics from stored positions and NAV history
- avoid embedding prompt logic in services
- return structured DTOs suitable for agent tools and API responses
- add integration tests using a temporary database
```

---

## 8. Agent Tools 提示词

```text
Read AGENTS.md and docs/ first.
Implement the first version of agent tool functions.

Create tools for:
- get_portfolio_snapshot
- get_position_breakdown
- get_fund_master
- get_fund_nav_history
- compute_portfolio_metrics
- compute_drawdown
- detect_risk_flags
- save_review_report
- save_strategy_proposal
- save_agent_debate_log

Requirements:
- keep the tool layer thin
- route all authoritative computation through deterministic services
- return structured, serializable payloads
- never let agents mutate raw accounting records directly
- add tests for tool outputs and failure handling
```

---

## 9. 单 Agent 周报工作流提示词

```text
Read AGENTS.md and docs/ first.
Implement the first manual weekly review workflow.

Scope:
- coordinator prepares context from deterministic services
- ReviewAgent receives structured facts only
- workflow generates markdown weekly review output
- report is stored in review_report

Requirements:
- do not implement multi-agent debate yet
- keep prompt text in dedicated files under agents/prompts/
- save execution metadata for later traceability
- include a short example of output structure
```

---

## 10. 多 Agent 策略辩论提示词

```text
Read AGENTS.md and docs/ first.
Implement the first multi-agent strategy debate workflow.

Agents:
- StrategyAgent
- ChallengerAgent
- JudgeAgent

Requirements:
- coordinator provides the same evidence base to all agents
- ChallengerAgent must critique the proposal, not restate it
- JudgeAgent must synthesize and produce a final recommendation
- persist final proposal and debate summaries
- keep prompts isolated in markdown files
- do not add automatic trading or execution
- add tests for workflow orchestration boundaries
```

---

## 11. 调度系统提示词

```text
Read AGENTS.md and docs/ first.
Implement the scheduler layer for manual and timed workflow triggers.

Requirements:
- support daily, weekly, and monthly jobs
- separate scheduling from workflow business logic
- log start, success, and failure events
- make it easy to run a workflow manually for local development
- add tests for schedule registration and job triggering logic
```

---

## 12. API 层提示词

```text
Read AGENTS.md and docs/ first.
Implement the first version of the FastAPI layer.

Suggested endpoints:
- GET /health
- GET /portfolios
- GET /portfolios/{id}/snapshot
- GET /funds/{fund_code}
- GET /reports
- POST /imports/holdings
- POST /imports/transactions
- POST /workflows/weekly-review/run

Requirements:
- keep the API thin
- validate inputs with Pydantic v2
- do not leak ORM models directly
- return consistent response models
- add API tests
```

---

## 13. README 完善提示词

```text
Read AGENTS.md and docs/ first.
Improve README.md after the initial implementation milestone.

Requirements:
- document setup steps
- explain project boundaries clearly
- document repository structure
- describe how to run tests and local workflows
- include a short architecture summary
- keep the README concise but practical
```

---

## 14. 重构提示词

```text
Read AGENTS.md and docs/ first.
Review the current repository and propose a refactor plan.

Focus on:
- separation of domain logic and adapters
- duplication in services
- testability of accounting logic
- clarity of workflow orchestration
- boundaries between deterministic logic and agent logic

Do not refactor immediately.
First produce:
- a problem list
- a ranked refactor plan
- estimated risk by module
```

---

## 15. Bug 修复提示词

```text
Read AGENTS.md and docs/ first.
Investigate the reported bug thoroughly.

Requirements:
- reproduce the issue first
- identify whether it is a domain logic bug, persistence bug, workflow bug, or adapter bug
- explain root cause clearly
- propose the smallest safe fix
- add or update tests so the bug is locked down
- summarize what changed and why
```

---

## 16. 代码审查提示词

```text
Read AGENTS.md and docs/ first.
Review the current implementation as if you are the repository maintainer.

Focus on:
- correctness of deterministic portfolio logic
- append-only historical behavior
- adapter isolation
- workflow clarity
- prompt/business-logic separation
- test coverage gaps
- future maintenance risks

Return:
- critical issues
- medium-priority issues
- optional improvements
```

---

## 17. 给 Codex 的总原则短提示

可以把下面这段作为很多任务前面的固定前缀：

```text
Before changing anything, read AGENTS.md and all files under docs/.
Follow repository rules strictly.
Prefer deterministic portfolio logic over LLM assumptions.
Keep adapters, services, workflows, and prompts separated.
Add tests for all accounting and import behavior.
Preserve append-only historical data.
```

