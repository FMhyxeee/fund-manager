# Fund Manager

Personal, self-hosted, agent-driven fund portfolio review and strategy assistant.

This project is building a deterministic accounting core plus agent-assisted review workflows for a single trusted operator. It is a decision-support system, not an auto-trading system.

## Principles

- deterministic accounting first
- append-only historical truth for snapshots, reports, and proposals
- agents may explain and challenge evidence, but must not replace canonical metrics or execute trades

## Current scope

The repository is past the scaffold-only stage. Today it includes a working persistence and data-ingestion foundation, while deterministic portfolio metrics and review workflows are still the next milestone.

## Implemented components

- typed SQLAlchemy models plus an initial Alembic migration for `fund_master`, `portfolio`, `transaction`, `position_lot`, `nav_snapshot`, `portfolio_snapshot`, `review_report`, `strategy_proposal`, `agent_debate_log`, and `system_event_log`
- repository helpers for `fund_master`, `portfolio`, `transaction`, and append-only `position_lot` writes
- CSV importers for opening holdings snapshots and normalized transaction history
- normalized AKShare adapter functions for fund search, fund profile lookup, and NAV history retrieval
- a minimal FastAPI app with `/api/v1/health`
- unit and integration tests covering models, migrations, import pipelines, AKShare normalization, and API health
- package scaffolding for domain/services, agent tools/workflows/runtime, scheduler, and reports

## Not implemented yet

- deterministic portfolio metrics in `core/domain/metrics.py`
- portfolio snapshot assembly from stored positions plus NAV history
- review report generation and persisted workflow runs
- agent prompts, debate workflows, scheduler jobs, and runtime orchestration
- any trading or execution behavior

## Import commands

Dry-run holdings bootstrap import:

```powershell
uv run python -m fund_manager.data_adapters.import_holdings .\path\to\holdings.csv --dry-run
```

Dry-run transaction import:

```powershell
uv run python -m fund_manager.data_adapters.import_transactions .\path\to\transactions.csv --dry-run
```

The holdings importer seeds append-only `position_lot` opening snapshots for portfolios that do not yet have full transaction history. The transaction importer validates and appends normalized `transaction` records without rewriting prior history.

## Repository layout

```text
fund-manager/
|- AGENTS.md
|- README.md
|- doc/
|- pyproject.toml
|- src/fund_manager/
|  |- apps/api/
|  |- core/
|  |- data_adapters/
|  |- storage/
|  |- agents/
|  |- scheduler/
|  `- reports/
|- tests/
`- scripts/
```

## Quick start

```powershell
uv sync --extra dev --extra data
uv run uvicorn fund_manager.apps.api.main:app --reload
uv run pytest
```

## Next implementation steps

1. implement deterministic portfolio metrics and accounting assumptions in `core/domain/metrics.py`
2. build services that assemble portfolio snapshots from authoritative persisted data
3. add the first review-report workflow on top of deterministic services
4. layer agent tools, prompts, and scheduler entrypoints onto that evidence-backed core
