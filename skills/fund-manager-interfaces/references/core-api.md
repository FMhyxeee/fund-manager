# Core API Reference

The simplified `fund-manager` interface is a small FastAPI surface over the domain kernel.

Run locally:

```bash
UV_CACHE_DIR=/tmp/uv-cache uv run fund-manager-api
```

OpenAPI docs:

```text
http://127.0.0.1:8000/api/v1/docs
```

## Health

```http
GET /api/v1/health
```

Returns:

```json
{"status": "ok"}
```

## Portfolios

List portfolios:

```http
GET /api/v1/portfolios
```

Read a deterministic snapshot:

```http
GET /api/v1/portfolios/{portfolio_id}/snapshot?as_of_date=2026-03-15
```

Read position breakdown:

```http
GET /api/v1/portfolios/{portfolio_id}/positions?as_of_date=2026-03-15
```

Read metrics:

```http
GET /api/v1/portfolios/{portfolio_id}/metrics?as_of_date=2026-03-15
```

Read valuation history:

```http
GET /api/v1/portfolios/{portfolio_id}/valuation-history?start_date=2026-03-01&end_date=2026-03-31
```

Notes:

- If `as_of_date` or `end_date` is omitted, the route uses `date.today()`.
- Missing NAV is explicit through `missing_nav=true` and `missing_nav_fund_codes`.
- Portfolio reads are assembled from `position_lot` and `nav_snapshot`; they do not read a persisted `portfolio_snapshot` table.

## Funds

Read fund metadata:

```http
GET /api/v1/funds/{fund_code}
```

Read NAV history:

```http
GET /api/v1/funds/{fund_code}/nav-history?start_date=2026-03-01&end_date=2026-03-31
```

Notes:

- `fund_code` maps to `fund_master.fund_code`.
- NAV reads return points in ascending `nav_date` order.

## Transactions

List transactions:

```http
GET /api/v1/transactions
GET /api/v1/transactions?portfolio_id=1
GET /api/v1/transactions?portfolio_name=main
GET /api/v1/transactions?fund_code=000001
GET /api/v1/transactions?trade_type=buy&start_date=2026-03-01&end_date=2026-03-31&limit=50
```

Constraints:

- `trade_type` must be one of `buy`, `sell`, `dividend`, `convert_in`, `convert_out`, `adjust`.
- `limit` must be from 1 to 200.

Get one transaction:

```http
GET /api/v1/transactions/{transaction_id}
```

Append one authoritative transaction:

```http
POST /api/v1/transactions
Content-Type: application/json

{
  "portfolio_id": 1,
  "fund_code": "000001",
  "fund_name": "Example Fund",
  "trade_date": "2026-03-16",
  "trade_type": "buy",
  "units": "10.000000",
  "gross_amount": "12.0000",
  "fee_amount": "0.0000",
  "nav_per_unit": "1.20000000",
  "external_reference": "broker-20260316-000001-buy",
  "source_name": "api",
  "source_reference": "manual-confirmation",
  "note": "operator-confirmed transaction"
}
```

Append notes:

- Provide either `portfolio_id` or `portfolio_name`.
- If the fund does not exist, `fund_name` is required so the service can explicitly create `fund_master`.
- `buy`, `sell`, `convert_in`, and `convert_out` require positive `units` and positive `gross_amount`.
- `dividend` requires positive `units` or positive `gross_amount`.
- `adjust` requires non-zero `units` or non-zero `gross_amount`.
- `nav_per_unit` must be positive when provided.
- Append returns `lot_sync`; callers should treat that as proof the materialized lot state was rebuilt.

## Watchlist

List active entries:

```http
GET /api/v1/watchlist
```

Include soft-removed entries:

```http
GET /api/v1/watchlist?include_removed=true
```

Add or reactivate a fund:

```http
POST /api/v1/watchlist/items
Content-Type: application/json

{
  "fund_code": "000002",
  "fund_name": "Candidate Fund",
  "category": "broad_index",
  "style_tags": ["index", "broad"],
  "risk_level": "medium",
  "note": "observe",
  "source_name": "api"
}
```

Soft-remove one fund:

```http
DELETE /api/v1/watchlist/items/{fund_code}
```

Notes:

- Watchlist add/reactivate uses `FundWatchlistService.add_item`.
- Watchlist remove uses `FundWatchlistService.remove_item`.
- Removed entries keep history through `removed_at`.
- Watchlist rows are not positions, decisions, or trade instructions.

## In-Process Services

Use these when changing domain code or writing direct service tests:

- `PortfolioService.assemble_portfolio_snapshot`
- `TransactionService.list_transactions`
- `TransactionService.get_transaction`
- `TransactionService.append_transaction`
- `FundWatchlistService.list_items`
- `FundWatchlistService.add_item`
- `FundWatchlistService.remove_item`

Keep business validation inside these services, not in FastAPI route handlers.

## Removed Surfaces

These are intentionally absent in the simplified core:

- `/api/v1/decisions`
- `/api/v1/policies`
- `/api/v1/reports`
- `/api/v1/strategy-proposals`
- `/api/v1/workflows/*`
- MCP server/tools
- scheduler CLI
- admin CLI
- dashboard UI
- AI workflow/runtime modules

Tests should keep asserting representative removed routes return `404`.
