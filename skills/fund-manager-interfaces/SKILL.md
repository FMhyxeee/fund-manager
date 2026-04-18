---
name: fund-manager-interfaces
description: Use when calling, documenting, testing, or changing fund-manager interfaces, including FastAPI endpoints, core services, ledger transaction append flows, portfolio reads, fund reads, watchlist operations, and OpenClaw or agent integration with fund-manager.
---

# fund-manager Interfaces

Use this skill when you need to operate or modify the simplified `fund-manager` interface surface.

## First Checks

1. Read `AGENTS.md` for current scope and guardrails.
2. For concrete endpoint shapes and examples, read `references/core-api.md`.
3. Confirm the database is migrated before treating API behavior as valid:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run alembic upgrade head
```

4. Run focused tests after interface work:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/unit/apps/api/test_api.py
```

For broader changes, run the full suite:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q
```

## Interface Choice

- Use FastAPI for OpenClaw, scripts, and external callers.
- Use `core/services` or `core/watchlist` directly for in-process domain changes and tests.
- Use repositories only from services or tests; do not put domain behavior in route handlers.
- Use direct SQL only for diagnostics, migrations, or explicit repair workflows.

Current public API root is `/api/v1`. Keep the public surface limited to:

- `/health`
- `/portfolios`
- `/funds`
- `/transactions`
- `/watchlist`

Do not reintroduce removed routes for decisions, policies, reports, workflows, MCP, scheduler, admin CLI, dashboards, or AI runtimes unless the user explicitly asks for that product direction.

## Ledger Rules

- `transaction` is the authoritative append-only trade ledger.
- `POST /api/v1/transactions` is the controlled ledger write path.
- Transaction append must go through `TransactionService.append_transaction`.
- Appending a transaction must rebuild deterministic `position_lot` state through `TransactionLotSyncService`.
- Never infer an executed trade from a watchlist entry, AI narrative, or natural-language suggestion.

## Watchlist Rules

- Watchlist entries are observation state.
- Adding a watchlist item may upsert `fund_master`, but it must not mutate transactions or positions.
- Removing a watchlist item is a soft remove via `removed_at`.
- Active reads hide removed rows unless `include_removed=true`.

## Error Contract

API errors use a stable envelope:

```json
{
  "detail": "Portfolio not found",
  "error": {
    "code": "portfolio_not_found",
    "message": "Portfolio not found",
    "details": null
  }
}
```

Prefer branching on `error.code`, not on free-form text.

## Change Checklist

Before finishing interface work:

- The endpoint/service still matches `references/core-api.md`.
- Ledger writes remain append-only and deterministic.
- Watchlist remains separate from accounting truth.
- Route handlers delegate business behavior to services.
- New schema fields have migrations.
- Tests cover the touched endpoint or service path.
