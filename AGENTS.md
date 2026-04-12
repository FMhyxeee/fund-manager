# AGENTS.md

## 1. Repository Purpose

This repository implements a **personal, self-hosted, agent-driven fund portfolio review and strategy assistant**.

Primary goals:
- Track and explain personal fund holdings and transactions.
- Compute authoritative portfolio metrics using deterministic code.
- Generate deterministic policy-backed daily decision runs.
- Capture manual execution feedback from the operator.
- Reconcile imported transactions back to prior decision feedback for auditability.
- Run scheduled review workflows (daily / weekly / monthly).
- Support multi-agent discussion for strategy analysis.
- Persist reports, decision runs, manual feedback, strategy proposals, and debate logs for long-term review.

This system is a **decision-support system with a manual execution loop**, not an auto-trading system.

---

## 2. Non-Goals

Do **not** implement or assume the following in v1 unless explicitly requested:
- Automatic fund buying or selling.
- Broker / custodian / exchange integrations for order submission.
- Direct integration with trading permissions.
- Real-money execution pipelines or background order dispatch.
- Hidden LLM-only accounting logic.
- Multi-tenant SaaS behaviors.
- Public API hardening for external customers.

---

## 3. Core Product Rules

1. **Deterministic accounting first**
   - All authoritative metrics must come from deterministic Python code.
   - LLMs may explain and challenge results, but must not define canonical accounting values.

2. **Append-only historical truth**
   - Historical snapshots, reports, and strategy proposals are append-only.
   - Never overwrite prior investment conclusions unless the user explicitly requests a correction workflow.

3. **Evidence-backed strategy outputs**
   - Every strategy conclusion must reference structured data produced by tools or services.
   - Never produce unsupported “investment advice” language.

4. **Manual execution is first-class**
   - The human operator decides whether a suggested action was executed, skipped, or deferred.
   - The system may persist manual feedback and reconcile later imported transactions back to that feedback.
   - The system must not infer that a trade happened only because an agent recommended it.

5. **No direct agent mutation of core accounting tables**
   - Agents must call domain tools.
   - Agents must not directly write SQL or mutate accounting records without going through controlled services.

6. **Personal deployment assumption**
   - The system is built for one trusted operator.
   - Optimize for clarity, maintainability, and auditability over enterprise complexity.

---

## 4. Architecture Guardrails

### 4.1 Layering

Keep the repository layered:
- `core/domain`: pure business entities and value logic.
- `core/services`: deterministic business services.
- `data_adapters`: external data acquisition and normalization.
- `storage`: persistence models, migrations, repositories.
- `agents/tools`: controlled tools exposed to agents.
- `agents/workflows`: orchestration and loop logic.
- `scheduler`: timed triggers and automation entrypoints.
- `mcp`: optional read-oriented transport layer for external agent clients.
- `apps/api`: external API surface.

### 4.2 Dependency direction

Allowed dependency direction:
- `apps/api` -> `core/services`, `storage/repo`, `agents/workflows`
- `mcp` -> `agents/tools`, `core/services`, `storage/repo`
- `agents/workflows` -> `agents/tools`, `core/services`, `storage/repo`
- `agents/tools` -> `core/services`, `storage/repo`, `data_adapters`
- `data_adapters` -> external APIs only
- `core/domain` -> no infrastructure dependencies

Disallowed:
- Domain logic depending on API frameworks.
- Prompt text embedded inside core business services.
- Data adapter logic mixed into accounting computation modules.

Decision evaluation, manual feedback recording, and transaction reconciliation belong in
`core/services`, with persistence flowing through `storage/repo`.

---

## 5. Data Integrity Rules

1. Every schema change must include a migration.
2. Every accounting logic change must include or update tests.
3. Snapshot tables are append-only unless a repair command is explicitly designed.
4. Imported external data must be normalized before persistence.
5. Data source provenance should be stored when practical.
6. Time series operations must be explicit about dates and ordering.
7. Never silently coerce missing numeric values to zero unless a business rule explicitly allows it.
8. Opening holdings imports are append-only bootstrap snapshot batches. Services reading `position_lot` must resolve the latest authoritative batch or transaction-derived lot state, not sum every historical bootstrap import together.
9. If required NAV data is missing, services must surface an incomplete snapshot state explicitly. They must not persist a canonical complete-valued portfolio snapshot by guessing, backfilling, or silently treating missing NAVs as zero.
10. Scheduled or scripted market-data refreshes must write through repositories/services. Do not duplicate persistence logic in one-off scripts when a core service can own it.
11. `decision_run`, `decision_feedback`, and `decision_transaction_link` are append-only audit artifacts. New state should be recorded as new rows, not by rewriting prior conclusions.
12. `transaction` remains the authoritative trade ledger. Reconciliation should add link records, not mutate imported transactions to embed agent state.
13. Manual feedback must reference a concrete deterministic action, preferably by `decision_run` plus `action_index`, rather than fuzzy natural-language matching.

---

## 6. Authoritative Computation Policy

The following values must be computed in deterministic services only:
- current market value
- total cost
- average cost
- unrealized PnL
- realized PnL
- portfolio weight
- daily / weekly / monthly return
- drawdown
- rebalance gap
- policy band breaches
- suggested rebalance amount
- feedback-to-transaction reconciliation matches
- transaction normalization results

LLMs may:
- summarize metrics
- compare periods
- explain likely drivers
- challenge assumptions
- organize next actions

LLMs may not:
- invent missing holdings
- invent fund data
- replace canonical metrics
- rewrite transaction history without an explicit repair workflow

---

## 7. Agent Design Rules

### 7.1 Agent roles

The expected agent roles are:
- `DataAgent`
- `ReviewAgent`
- `StrategyAgent`
- `ChallengerAgent`
- `JudgeAgent`
- optional `CoordinatorAgent`

### 7.2 Agent behavior constraints

Each agent should:
- use structured tools where possible
- operate on a bounded context
- return concise, structured outputs
- distinguish facts vs interpretation vs recommendation

Each agent must avoid:
- directly editing accounting tables
- making execution decisions automatically
- marking a trade as executed unless the operator explicitly triggers a manual-feedback write path
- generating unsupported predictions stated as facts
- duplicating data-fetch logic that should live in tools

### 7.3 Debate rule

For weekly and monthly strategy workflows that produce a strategy proposal:
- `StrategyAgent` must propose
- `ChallengerAgent` must critique
- `JudgeAgent` must finalize

No final strategy proposal should be saved without challenge review unless the user explicitly disables it.

### 7.4 Daily deterministic decision stage

The daily decision stage is not a free-form agent recommendation pass.

For this stage:
- policy evaluation must come from deterministic services
- the persisted artifact is `decision_run`
- agents may explain, challenge, or summarize a deterministic decision, but should not replace it
- manual execution feedback, when present, must be stored separately from the original decision artifact

### 7.5 Manual weekly review stage

The first weekly review workflow may be implemented as a manual, single-agent review flow before multi-agent debate is added.

For this stage:
- `CoordinatorAgent` prepares context only from deterministic services and repositories
- `ReviewAgent` receives structured facts only, not raw database access or hidden business rules
- weekly review output should be rendered as markdown and stored in `review_report`
- execution metadata should be saved for traceability, including run id, trigger source, prompt reference when available, and tool call summaries
- this workflow must not persist a strategy proposal or imply that challenge review has already happened

---

## 8. Tooling Rules for Agent Tools

Agent tools should be:
- typed
- side-effect-aware
- deterministic where possible
- minimal in scope
- easy to trace in logs

Preferred tool pattern:
1. validate inputs
2. call service/repo
3. return structured result
4. include metadata if relevant

For tools that record manual execution feedback:
- require explicit `decision_run` identity plus `action_index`
- require an explicit feedback status such as `executed`, `skipped`, or `deferred`
- keep reconciliation logic in services, not in route handlers or prompts

Application services used by tools or APIs should prefer explicit structured DTOs over leaking ORM models directly.

Avoid tools that:
- do too many unrelated actions
- both compute and persist multiple entities without clear intent
- return unstructured giant text blobs when structured JSON-like output is more appropriate

---

## 9. Prompt / Markdown Conventions

Prompt files should live under `agents/prompts/`.

Prompt files should:
- define role
- define allowed tools
- define expected output structure
- explicitly require separation of fact / interpretation / recommendation
- avoid hidden business logic that belongs in Python code

Do not place sensitive credentials in prompt files.

---

## 10. Coding Standards

### Python
- Prefer Python 3.11+ features when stable and appropriate.
- Use type hints for public functions and service interfaces.
- Prefer `dataclass`, `pydantic`, or typed ORM models where appropriate.
- Keep functions small and composable.
- Prefer explicit names over abbreviations.

### Style
- Follow clean, readable structure over cleverness.
- Prefer pure functions in domain and metrics logic.
- Keep I/O at the edges.
- Add docstrings for non-obvious business rules.

### Errors
- Fail loudly on invalid accounting assumptions.
- Raise explicit exceptions for normalization failures.
- Do not swallow external data adapter errors silently.

---

## 11. Testing Policy

### Mandatory unit tests
- transaction normalization
- cost basis updates
- current value calculation
- portfolio weight calculation
- period return calculation
- drawdown calculation
- rebalance gap calculation
- deterministic policy decision evaluation
- manual decision feedback recording
- feedback-to-transaction reconciliation matching

### Mandatory integration tests
- holdings import pipeline
- transaction import pipeline
- transaction import pipeline with decision reconciliation
- daily decision workflow happy path
- fund public data adapter normalization
- weekly review workflow happy path

### Recommended tests
- monthly strategy debate workflow
- malformed CSV import
- missing NAV data fallback handling
- manual feedback API / tool entrypoints

When changing core financial logic, update tests first or together with the change.

---

## 12. Observability and Logging

Every workflow run should be traceable.

Minimum logging expectations:
- workflow name
- run id
- trigger source
- relevant portfolio id
- start / end timestamps
- tool call summaries
- persistence outcomes
- failure reason when any step fails

Important:
- Logging must not expose secrets.
- Strategy and report artifacts should be persistable independently of raw trace logs.

---

## 13. Configuration and Secrets

- Store secrets in environment variables or local config files excluded from version control.
- Commit `.env.example`, never commit `.env` with real credentials.
- Keep provider auth wiring isolated from domain logic.
- Design the code so model provider changes do not require rewriting accounting modules.

---

## 14. OpenClaw / Runtime Assumptions

This repository should assume:
- personal self-hosted runtime
- OpenClaw or equivalent orchestration runtime
- OpenAI Codex OAuth as a preferred development/runtime login mode where supported
- optional secondary providers such as GLM for debate roles

Runtime-specific code should be isolated behind adapter or bridge modules.

---

## 15. Repository Tasks Codex Can Safely Help With

Codex is encouraged to:
- scaffold modules
- create migrations
- implement deterministic services
- implement adapters
- write tests
- refactor for layering
- improve prompts
- improve workflow orchestration
- improve documentation

Codex should be cautious with:
- modifying financial formulas
- altering persisted schema semantics
- changing transaction normalization rules
- changing any tool used in strategy persistence

For these changes, Codex should prefer small, test-backed edits.

---

## 16. Change Checklist

Before completing a change, verify:
- Does it preserve deterministic accounting truth?
- Does it keep domain logic outside prompts?
- Does it include tests where needed?
- Does it preserve append-only history assumptions?
- Does it keep agent permissions constrained?
- Does it avoid implying auto-trading behavior?

---

## 17. Preferred Build Order

When the repository is still early-stage, prefer implementing in this order:
1. schema and models
2. import and normalization
3. deterministic metrics
4. portfolio snapshot generation
5. single-agent weekly review
6. multi-agent debate workflow
7. scheduler and automation
8. dashboard and polish

---

## 18. Output Style for Generated Reports

Reports should generally use this structure:
1. summary
2. key metrics
3. what happened
4. key drivers
5. risks / concerns
6. proposed actions
7. open questions

Strategy proposals should generally use:
1. thesis
2. evidence
3. proposed actions
4. counterarguments
5. final judgment
6. confidence level

---

## 19. Hard Constraints

Never implement in v1 unless explicitly requested:
- automatic order placement
- password scraping from consumer apps
- unauthorized access to private platforms
- unsupported claims of guaranteed returns
- hidden mutation of authoritative accounting records by agents

---

## 20. If Requirements Conflict

Prioritize in this order:
1. user explicit instruction
2. deterministic accounting correctness
3. data integrity and auditability
4. architecture clarity
5. agent convenience
6. UI polish
