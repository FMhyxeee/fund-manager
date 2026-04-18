# fund-manager

`fund-manager` is a personal, self-hosted fund ledger and watchlist service.

The repository now keeps only the core domain kernel:

- canonical fund and portfolio records
- append-only transaction ledger
- deterministic transaction-backed position lots
- deterministic portfolio read models
- persisted fund watchlist
- FastAPI endpoints for reading and mutating the core data

It does not include AI review workflows, policy decision runs, scheduling, MCP, dashboards, report generation, or broker/order integrations.

## Core Model

Core tables:

- `fund_master`
- `portfolio`
- `transaction`
- `position_lot`
- `nav_snapshot`
- `watchlist_item`

Removed product surfaces:

- decision and policy workflows
- decision feedback and reconciliation links
- review reports and strategy proposals
- agent debate logs and runtime prompts
- scheduler, MCP, admin CLI, dashboard, CSV import endpoints

## API

Run the API locally:

```powershell
uv run fund-manager-api
```

Default OpenAPI docs:

```text
http://127.0.0.1:8000/api/v1/docs
```

### Health

```http
GET /api/v1/health
```

### Portfolios

```http
GET /api/v1/portfolios
GET /api/v1/portfolios/{portfolio_id}/snapshot?as_of_date=2026-03-15
GET /api/v1/portfolios/{portfolio_id}/positions?as_of_date=2026-03-15
GET /api/v1/portfolios/{portfolio_id}/metrics?as_of_date=2026-03-15
GET /api/v1/portfolios/{portfolio_id}/valuation-history?start_date=2026-03-01&end_date=2026-03-31
```

### Funds

```http
GET /api/v1/funds/{fund_code}
GET /api/v1/funds/{fund_code}/nav-history?start_date=2026-03-01&end_date=2026-03-31
```

### Ledger

```http
GET /api/v1/transactions
GET /api/v1/transactions/{transaction_id}
POST /api/v1/transactions
```

Example transaction append:

```json
{
  "portfolio_id": 1,
  "fund_code": "000001",
  "fund_name": "Example Fund",
  "trade_date": "2026-03-16",
  "trade_type": "buy",
  "units": "10.000000",
  "gross_amount": "12.0000",
  "nav_per_unit": "1.20000000",
  "source_name": "api"
}
```

Appending a transaction rebuilds transaction-backed `position_lot` snapshots through deterministic code.

### Watchlist

```http
GET /api/v1/watchlist
GET /api/v1/watchlist?include_removed=true
POST /api/v1/watchlist/items
DELETE /api/v1/watchlist/items/{fund_code}
```

Example watchlist add:

```json
{
  "fund_code": "000002",
  "fund_name": "Candidate Fund",
  "category": "broad_index",
  "style_tags": ["index", "broad"],
  "risk_level": "medium",
  "note": "observe"
}
```

Delete is a soft remove: the historical watchlist row remains with `removed_at`, and active list reads hide it by default.

## Development

```powershell
uv sync --extra dev
uv run pytest
```

Run only the API tests:

```powershell
uv run pytest tests/unit/apps/api/test_api.py
```

Run migrations on a configured database:

```powershell
uv run alembic upgrade head
```

## Boundaries

This is not an auto-trading system. It does not place orders or infer execution. The ledger changes only through explicit transaction append paths.

Watchlist entries are research/observation state. They are not accounting truth, trade instructions, or policy decisions.
