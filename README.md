# Fund Manager

Personal, self-hosted, agent-driven fund portfolio review and strategy assistant.

This repository is bootstrapped for Python 3.12 and follows the layered architecture defined in `AGENTS.md` and the planning documents under `doc/`. The current scaffold keeps domain logic, adapters, storage, agent workflows, and the API surface clearly separated so deterministic accounting can be added safely in later steps.

## Current scope

- Python project initialized with `pyproject.toml`
- developer tooling configured for Ruff, pytest, and mypy
- minimal FastAPI application scaffolded
- package layout created for domain, services, adapters, storage, agents, scheduler, and reports
- placeholder directories added for prompts, templates, migrations, fixtures, and future workflow code

No portfolio business logic, accounting rules, persistence models, or agent workflows are implemented yet.

## Repository layout

```text
fund-manager/
├─ AGENTS.md
├─ README.md
├─ doc/
├─ pyproject.toml
├─ .env.example
├─ Makefile
├─ src/
│  └─ fund_manager/
│     ├─ apps/api/
│     ├─ core/domain/
│     ├─ core/services/
│     ├─ core/rules/
│     ├─ data_adapters/
│     ├─ storage/
│     ├─ agents/
│     ├─ scheduler/
│     └─ reports/
├─ tests/
└─ scripts/
```

## Quick start

1. Install Python 3.12.
2. Create a local `.env` from `.env.example`.
3. Install dependencies:

```powershell
uv sync --extra dev --extra data
```

4. Run the API:

```powershell
uv run uvicorn fund_manager.apps.api.main:app --reload
```

5. Run checks:

```powershell
uv run ruff check src tests
uv run mypy src
uv run pytest
```

## Developer commands

For cross-shell workflows, a `Makefile` is included:

- `make install`
- `make format`
- `make lint`
- `make typecheck`
- `make test`
- `make check`
- `make run`

## Next implementation steps

1. add typed SQLAlchemy models and the first Alembic migration
2. build import and normalization adapters
3. implement deterministic portfolio metrics and tests
4. add weekly review workflow scaffolding
5. connect storage, reports, and agent tooling
