# AGENTS.md

## 1. Repository Definition

This repository implements a **personal, self-hosted investment domain kernel** for fund portfolio tracking, review, and policy-backed decision support.

`fund-manager` is the system that owns:
- canonical portfolio facts
- deterministic accounting and policy evaluation
- append-only audit artifacts
- manual execution feedback and reconciliation
- stable typed interfaces for other runtimes and agents

AI is **not** the center of this repository.

AI is a **replaceable analysis layer** that may consume structured facts from `fund-manager` and produce explanations, critiques, summaries, and strategy narratives. The repository must remain correct even when no LLM is available.

This system is a **decision-support system with a manual execution loop**, not an auto-trading system.

---

## 2. System Model

Everything in the repository should be classified into one of the following artifact classes.

### 2.1 Canonical Facts

Owned by `fund-manager`.

Examples:
- `portfolio`
- `fund_master`
- `transaction`
- `position_lot`
- `nav_snapshot`
- `portfolio_snapshot`
- deterministic portfolio metrics

Rules:
- must be computed or normalized by deterministic code
- must never depend on prompt-only logic
- may be corrected only through explicit repair workflows

### 2.2 Deterministic Decisions

Owned by `fund-manager`.

Examples:
- policy evaluation results
- band-breach detection
- suggested rebalance amount
- `decision_run`

Rules:
- generated from canonical facts plus deterministic policy rules
- append-only once persisted
- may be explained by AI, but not replaced by AI

### 2.3 Research Signals

Owned by `fund-manager` when they are implemented as deterministic read models.

Examples:
- watchlist candidates
- style leaders
- candidate-vs-portfolio fit analysis
- future market radar or signal snapshots

Rules:
- not part of canonical accounting truth
- not equivalent to policy truth
- not equivalent to execution instructions
- must remain explainable and reproducible from structured inputs

### 2.4 AI Narratives

Produced by AI runtimes, optionally persisted by `fund-manager` as append-only artifacts.

Examples:
- weekly review narrative
- strategy proposal
- challenge output
- judge output
- markdown reports generated from structured facts

Rules:
- must be clearly separated from canonical facts
- must identify facts vs interpretation vs recommendation vs uncertainty
- must never be treated as accounting truth

### 2.5 Human Execution Feedback

Owned by `fund-manager`.

Examples:
- `decision_feedback`
- `decision_transaction_link`

Rules:
- must reference concrete deterministic actions
- must be append-only
- actual execution is decided by the operator, not inferred from AI output

---

## 3. Non-Goals

Do **not** implement or assume the following in v1 unless explicitly requested:
- automatic fund buying or selling
- broker / custodian / exchange integrations for order submission
- direct integration with trading permissions
- real-money execution pipelines or background order dispatch
- hidden LLM-only accounting logic
- AI-defined canonical metrics
- multi-tenant SaaS behaviors
- public API hardening for external customers

---

## 4. Core Product Rules

1. **Deterministic truth first**
   - All authoritative portfolio facts and decisions must come from deterministic Python code.
   - LLMs may explain or challenge results, but must not define canonical values.

2. **Stable without AI**
   - Core domain flows must remain correct when no LLM is configured.
   - Import, sync, snapshot, policy evaluation, decision generation, feedback recording, and reconciliation must all work without AI.

3. **Append-only historical truth**
   - Historical snapshots, reports, decisions, strategy proposals, and feedback records are append-only.
   - Never silently overwrite prior conclusions.

4. **Truth, signal, and narrative must stay separate**
   - Canonical facts are not research signals.
   - Research signals are not deterministic decisions.
   - AI narratives are not canonical facts.

5. **Manual execution is first-class**
   - The human operator decides whether a suggested action was executed, skipped, or deferred.
   - The system must not infer that a trade happened only because a decision or AI proposal existed.

6. **No direct agent mutation of core accounting tables**
   - Agents must call domain tools or APIs.
   - Agents must not directly write SQL or mutate accounting records without controlled services.

7. **Personal deployment assumption**
   - The system is built for one trusted operator.
   - Optimize for clarity, maintainability, and auditability over enterprise complexity.

---

## 5. Boundary with OpenClaw

`fund-manager` owns the investment-domain source of truth.

`fund-manager` is responsible for:
- canonical portfolio data and persistence
- deterministic accounting and policy evaluation
- append-only audit artifacts such as snapshots, decisions, reports, feedback, and reconciliation links
- deterministic research signals such as watchlist, candidate fit, and style-leader outputs
- fund-domain ingestion paths such as AKShare sync, holdings import, transaction import, and NAV refresh
- typed domain interfaces exposed through API, CLI, MCP, or internal tools

`OpenClaw` is responsible for:
- agent runtime, model/profile selection, auth context, and tool permissions
- prompt orchestration and sub-agent routing
- channel interaction such as chat replies, Feishu delivery, inbox-style summaries, and notifications
- external search and other cross-project tools that are not fund-specific
- orchestration concerns such as heartbeat checks, cron triggers, retry policy, and “who should be told”

Coordination rule:
- `OpenClaw` may call `fund-manager`, schedule `fund-manager`, or summarize `fund-manager` outputs.
- `fund-manager` must not depend on `OpenClaw` internals to remain correct.
- `OpenClaw` must not bypass `fund-manager` services by writing the database directly or re-implementing portfolio truth in prompts.

Practical split:
- “What is the portfolio state?” belongs in `fund-manager`.
- “Which policy rules fired today?” belongs in `fund-manager`.
- “What are the current watchlist or style-leader signals?” belongs in `fund-manager`.
- “How should this be explained to the human?” belongs in `OpenClaw` or an AI runtime adapter.
- “Which model should be used for the weekly review?” belongs in `OpenClaw`.
- “Should the human receive a Feishu summary right now?” belongs in `OpenClaw`.

For an action-level ownership checklist, see [`doc/06-边界与接口清单.md`](./doc/06-%E8%BE%B9%E7%95%8C%E4%B8%8E%E6%8E%A5%E5%8F%A3%E6%B8%85%E5%8D%95.md).

---

## 6. Architecture Guardrails

### 6.1 Layering

Keep the repository layered:
- `core/domain`: pure business entities and value logic
- `core/services`: deterministic business services and decision logic
- `core/watchlist` or future deterministic signal modules: research-signal read models
- `core/fact_packs.py`: typed deterministic facts prepared for AI-facing workflows
- `core/ai_artifacts.py`: typed AI artifacts persisted or transported separately from truth
- `data_adapters`: external data acquisition and normalization
- `storage`: persistence models, migrations, repositories
- `agents/tools`: controlled tools exposed to workflows or external runtimes
- `agents/workflows`: orchestration of domain services and persisted artifacts
- `agents/runtime/contracts.py`: runtime-facing protocols only
- `agents/runtime/shared.py`: prompt metadata loading and tiny shared formatting helpers
- `agents/runtime/*_agent.py`: manual or lightweight adapter implementations only
- `scheduler`: timed triggers and automation entrypoints
- `mcp`: optional transport layer for external agent clients
- `apps/api`: external API surface

### 6.2 Dependency direction

Allowed dependency direction:
- `apps/api` -> `core/services`, `core/watchlist`, `storage/repo`, `agents/workflows`
- `mcp` -> `agents/tools`, `core/services`, `core/watchlist`, `storage/repo`
- `agents/workflows` -> `agents/tools`, `core/services`, `core/watchlist`, `storage/repo`
- `agents/tools` -> `core/services`, `core/watchlist`, `storage/repo`, `data_adapters`
- `data_adapters` -> external APIs only
- `core/domain` -> no infrastructure dependencies

Disallowed:
- domain logic depending on API frameworks
- prompt text embedded inside core deterministic services
- data adapter logic mixed into accounting computation modules
- AI-only inference defining canonical truth
- runtime helper modules becoming hidden homes for canonical DTOs or persisted artifact schemas

Decision evaluation, manual feedback recording, transaction reconciliation, and deterministic signal generation belong in Python services, with persistence flowing through `storage/repo`.

---

## 7. Data Integrity Rules

1. Every schema change must include a migration.
2. Every accounting or deterministic decision logic change must include or update tests.
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
14. Research signals must not be written back into canonical accounting tables.
15. AI-generated narratives must be persisted as their own artifacts, never as silent mutations to canonical fact tables.

---

## 8. Authoritative Computation Policy

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
- deterministic watchlist scores and fit labels

LLMs may:
- summarize metrics
- compare periods
- explain likely drivers
- challenge assumptions
- organize next actions
- produce review and strategy narratives from structured facts

LLMs may not:
- invent missing holdings
- invent fund data
- replace canonical metrics
- redefine policy evaluation results
- rewrite transaction history without an explicit repair workflow
- turn research signals into canonical truth by prompt convention alone

---

## 9. AI Design Rules

### 9.1 AI input contract

AI should receive structured **Fact Packs**, not raw database access and not hidden business rules.

A Fact Pack should contain:
- stable identifiers such as `run_id`, `portfolio_id`, `as_of_date`, and period bounds
- deterministic facts and metrics only
- provenance or source metadata when relevant
- explicit notes about missing data, assumptions, and incompleteness

Current code guidance:
- weekly and strategy workflow inputs belong in `core/fact_packs.py`
- do not redefine workflow input DTOs inside `agents/runtime/*`

### 9.2 AI output contract

AI outputs should be structured and typed before persistence.

Every non-trivial AI artifact should distinguish:
- facts used
- interpretation
- recommendation
- counterarguments or alternatives
- uncertainty / confidence

Markdown may be generated for humans, but the canonical persisted AI artifact should have a structured payload behind it.

Current code guidance:
- review / strategy / challenge / judge outputs belong in `core/ai_artifacts.py`
- do not treat runtime implementation modules as the owner of persisted artifact schemas

### 9.3 AI workflow persistence rule

When `fund-manager` persists AI outputs:
- keep them append-only
- store run metadata
- store prompt or template references when available
- store model name when available
- store tool-call summaries when available

### 9.4 AI replacement rule

The repository must be able to:
- swap models
- swap providers
- move orchestration into `OpenClaw`
- disable AI entirely

without rewriting deterministic accounting modules.

---

## 10. Agent Design Rules

### 10.1 Expected roles

Expected roles may include:
- `ReviewAgent`
- `StrategyAgent`
- `ChallengerAgent`
- `JudgeAgent`
- optional `CoordinatorAgent`

The repository may keep lightweight in-repo manual agents for testing and deterministic scaffolding, but production-grade model routing belongs outside the domain kernel.

Current code guidance:
- protocols live in `agents/runtime/contracts.py`
- prompt loading and shared runtime metadata live in `agents/runtime/shared.py`
- manual implementations live in `agents/runtime/review_agent.py`, `strategy_agent.py`, `challenger_agent.py`, and `judge_agent.py`
- these modules are adapters, not the home of canonical truth, fact DTOs, or persisted artifact DTOs

### 10.2 Agent behavior constraints

Each agent should:
- use structured tools where possible
- operate on bounded context
- return concise, structured outputs
- distinguish facts vs interpretation vs recommendation

Each agent must avoid:
- directly editing accounting tables
- making execution decisions automatically
- marking a trade as executed unless the operator explicitly triggers a manual-feedback write path
- generating unsupported predictions stated as facts
- duplicating data-fetch logic that should live in tools

### 10.3 Debate rule

For weekly and monthly strategy workflows that produce a strategy proposal:
- `StrategyAgent` proposes
- `ChallengerAgent` critiques
- `JudgeAgent` finalizes

No final strategy proposal should be saved without challenge review unless the user explicitly disables it.

### 10.4 Daily deterministic decision stage

The daily decision stage is not a free-form AI recommendation pass.

For this stage:
- policy evaluation must come from deterministic services
- the persisted artifact is `decision_run`
- agents may explain, challenge, or summarize a deterministic decision, but must not replace it
- manual execution feedback, when present, must be stored separately from the original decision artifact

### 10.5 Weekly and monthly AI stages

For review and strategy workflows:
- a deterministic coordinator prepares structured facts
- AI consumes the facts and returns typed artifacts
- final persistence keeps facts and AI artifacts separate
- these workflows must not silently mutate policy truth or accounting truth

---

## 11. Tooling Rules for Agent Tools

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
- return unstructured giant text blobs when structured output is more appropriate
- hide side effects behind read-sounding names

---

## 12. Prompt / Markdown Conventions

Prompt files should live under `agents/prompts/`.

Prompt files should:
- define role
- define allowed tools
- define expected output structure
- explicitly require separation of fact / interpretation / recommendation / uncertainty
- avoid hidden business logic that belongs in Python code

Do not place sensitive credentials in prompt files.

---

## 13. Coding Standards

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

## 14. Testing Policy

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
- deterministic signal outputs such as watchlist scoring and fit-label rules when changed

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
- signal layer APIs and tool surfaces

When changing core financial logic, update tests first or together with the change.

---

## 15. Observability and Logging

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

For AI-backed artifacts, log when available:
- model or provider name
- prompt/template reference
- fact pack reference or summary

Important:
- logging must not expose secrets
- strategy and report artifacts should be persistable independently of raw trace logs

---

## 16. Configuration and Secrets

- Store secrets in environment variables or local config files excluded from version control.
- Commit `.env.example`, never commit `.env` with real credentials.
- Keep provider auth wiring isolated from domain logic.
- Design the code so model provider changes do not require rewriting accounting modules.

---

## 17. OpenClaw / Runtime Assumptions

This repository should assume:
- personal self-hosted runtime
- `OpenClaw` or equivalent orchestration runtime
- optional external model providers
- optional provider-specific model routing outside the domain kernel

Runtime-specific code should be isolated behind adapter or bridge modules.

---

## 18. Repository Tasks Codex Can Safely Help With

Codex is encouraged to:
- scaffold modules
- create migrations
- implement deterministic services
- implement signal read models
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
- changing policy evaluation semantics
- changing any tool used in strategy persistence

For these changes, Codex should prefer small, test-backed edits.

---

## 19. Change Checklist

Before completing a change, verify:
- Does it preserve deterministic accounting truth?
- Does it keep domain logic outside prompts?
- Does it include tests where needed?
- Does it preserve append-only history assumptions?
- Does it keep agent permissions constrained?
- Does it avoid implying auto-trading behavior?
- Does it clearly separate truth, signal, narrative, and human feedback?
- Would the core flow still work if AI were disabled?

---

## 20. Preferred Build Order

When the repository is still early-stage, prefer implementing in this order:
1. schema and models
2. import and normalization
3. deterministic metrics and policy evaluation
4. portfolio snapshot generation
5. manual execution loop
6. deterministic signal layer
7. single-agent weekly review
8. multi-agent debate workflow
9. scheduler and automation
10. dashboard and polish

---

## 21. Output Style for Generated Reports

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

## 22. Hard Constraints

Never implement in v1 unless explicitly requested:
- automatic order placement
- password scraping from consumer apps
- unauthorized access to private platforms
- unsupported claims of guaranteed returns
- hidden mutation of authoritative accounting records by agents
- prompt-only canonical accounting

---

## 23. If Requirements Conflict

Prioritize in this order:
1. user explicit instruction
2. deterministic accounting correctness
3. data integrity and auditability
4. architecture clarity
5. stable separation of truth / signal / narrative
6. agent convenience
7. UI polish
