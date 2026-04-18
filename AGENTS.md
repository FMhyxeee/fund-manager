# AGENTS.md

## Repository Definition

This repository implements a personal, self-hosted fund ledger and watchlist service.

`fund-manager` owns:

- canonical fund and portfolio records
- append-only transaction ledger records
- deterministic transaction-backed position lots
- deterministic portfolio read models
- persisted fund watchlist entries
- FastAPI interfaces for the core ledger and watchlist

The repository is not an auto-trading system and does not place orders.

## Current Product Scope

Keep only these product surfaces:

1. Ledger
   - list transactions
   - get one transaction
   - append one transaction through deterministic services
   - rebuild position lot state after ledger mutation
   - read portfolio positions, snapshots, metrics, and valuation history

2. Watchlist
   - list active watchlist funds
   - add or reactivate a fund
   - soft-remove a fund
   - keep watchlist state separate from accounting truth

3. Fund metadata and NAV reads
   - read fund profile
   - read NAV history

## Removed Scope

Do not reintroduce these features unless explicitly requested:

- AI review agents or prompt workflows
- strategy debate, challenger, judge, or report generation
- policy evaluation and decision run persistence
- decision feedback and decision-to-transaction reconciliation links
- scheduler, cron jobs, MCP server, admin CLI, dashboard UI
- CSV import endpoints and AKShare sync jobs
- Polymarket or unrelated external data adapters
- automatic order placement or broker integrations

## Architecture

Keep the repository layered:

- `core/domain`: pure deterministic math/value logic
- `core/services`: ledger, portfolio read, and transaction lot services
- `core/watchlist`: watchlist application service
- `storage`: ORM models, migrations, and repositories
- `apps/api`: FastAPI routes and request/response contracts

Allowed dependency direction:

- `apps/api` -> `core/services`, `core/watchlist`, `storage/repo`
- `core/services` -> `core/domain`, `storage/repo`
- `core/watchlist` -> `storage/repo`
- `storage/repo` -> `storage/models`
- `core/domain` -> no infrastructure dependencies

Disallowed:

- route handlers directly mutating accounting rows when a service exists
- hidden prompt or AI logic defining canonical values
- watchlist state being written into accounting tables
- transaction history rewrites outside an explicit repair workflow

## Data Integrity Rules

1. `transaction` is the authoritative trade ledger.
2. Transaction rows are append-only.
3. `position_lot` rows are deterministic materialized state rebuilt from ledger facts.
4. Missing NAV data must remain explicit; do not silently coerce missing values to zero.
5. Watchlist entries are observation state, not accounting truth and not trade instructions.
6. Removing a watchlist item should soft-remove it with `removed_at`.
7. Every schema change must include a migration.
8. Every accounting or ledger mutation change must include tests.

## API Rules

The public API should remain small:

- `/health`
- `/portfolios`
- `/funds`
- `/transactions`
- `/watchlist`

Do not expose removed workflows through route registration.

## Interface Skill

For agent-assisted interface work, use:

```text
skills/fund-manager-interfaces/SKILL.md
```

This skill documents how to call the current FastAPI surface, when to use in-process services, and which removed interfaces must stay absent.

## Testing Policy

Required tests for changes:

- transaction append validation
- transaction-backed lot sync
- portfolio snapshot and missing-NAV behavior
- watchlist add/list/remove
- API route coverage for `/transactions` and `/watchlist`
- migration smoke test for final core schema

Run:

```powershell
uv run pytest
```

## Change Checklist

Before completing a change, verify:

- Does the ledger remain deterministic and append-only?
- Does transaction append rebuild lot state through a service?
- Does watchlist stay separate from canonical accounting truth?
- Does the API remain limited to the core surface?
- Are removed AI/scheduler/MCP/report/policy features still absent from public entrypoints?
- Do migrations and tests match the simplified schema?
