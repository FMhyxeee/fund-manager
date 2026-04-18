# 05-Codex 启动提示词

> 当前状态（2026-04-18）：本文是历史提示词模板。涉及 AI workflow、Fact Pack、AI Artifact、CLI、Scheduler、MCP 的任务指令不再适用于当前精简核心。维护接口时优先使用 `skills/fund-manager-interfaces/SKILL.md`。

本文件提供适用于当前仓库状态的维护提示词模板。

使用前提：

- 先读 `AGENTS.md`
- 再读 `README.md` 和 `doc/`
- 先核对当前代码实现，再声明“已支持什么”

说明：

- 这不是产品文档
- 这是给工程代理用的工作提示词模板
- 默认假设仓库已经不是 bootstrap 阶段，而是一个正在持续演进的领域内核

---

## 1. 仓库状态校准

```text
Read AGENTS.md, README.md, and doc/ first.
Then inspect the current codebase before making claims.

Requirements:
- distinguish implemented features from planned features
- treat fund-manager as an investment domain kernel, not an AI shell
- verify API routes, CLI commands, scheduler jobs, and MCP tools from code
- verify runtime structure from code:
  - core/fact_packs.py
  - core/ai_artifacts.py
  - agents/runtime/contracts.py
  - agents/runtime/shared.py
- keep deterministic accounting first and append-only history intact
- update stale docs if code and docs diverge
```

---

## 2. 文档同步

```text
Read AGENTS.md, README.md, and doc/ first.
Audit all project documentation against the real repository state.

Requirements:
- unify terminology across README, AGENTS, and doc/
- use the following stable concepts consistently:
  - canonical facts
  - deterministic decisions
  - research signals
  - fact packs
  - AI artifacts
  - human execution feedback
- mention actual module ownership when relevant
- do not describe runtime implementation files as owners of canonical DTOs
- summarize which docs were updated and what stale claims were removed
```

---

## 3. 确定性领域逻辑修改

```text
Read AGENTS.md and doc/ first.
Modify deterministic services carefully.

Requirements:
- preserve canonical truth and append-only history
- keep business logic in core/services or core/domain
- update tests together with the change
- never move accounting truth into prompts or runtime adapters
- if a workflow needs AI, expose deterministic inputs through fact packs instead
```

---

## 4. AI Workflow / Runtime 修改

```text
Read AGENTS.md and doc/ first.
Improve weekly review, strategy debate, or other AI-adjacent flows.

Requirements:
- facts belong in core/fact_packs.py
- AI outputs belong in core/ai_artifacts.py
- runtime protocols belong in agents/runtime/contracts.py
- shared prompt helpers belong in agents/runtime/shared.py
- manual agent modules are adapters only
- keep persistence append-only
- keep facts and AI artifacts separate in workflow outputs
```

---

## 5. REST API / CLI / MCP 扩展

```text
Read AGENTS.md, README.md, and doc/ first.
Add or refine external interfaces for already-implemented domain capabilities.

Requirements:
- API is the main canonical read/write surface
- CLI is the main same-machine automation/debug surface
- MCP stays read-mostly unless explicitly approved otherwise
- return structured DTOs, not raw ORM objects
- keep route handlers thin and push truth into services/workflows
- update README and technical docs when user-facing interfaces change
```

---

## 6. Signal Layer 修改

```text
Read AGENTS.md and doc/ first.
Work on watchlist, style leaders, candidate fit, or other research-signal features.

Requirements:
- keep these outputs deterministic, explainable, and reproducible
- do not treat signal outputs as canonical accounting truth
- do not silently turn signal outputs into policy truth or execution advice
- if new signal DTOs are introduced, make their semantics explicit
- update doc/08 and related architecture docs when the signal layer changes
```

---

## 7. 高风险修改提醒

```text
Before making changes, check whether the task touches:
- financial formulas
- schema semantics
- policy evaluation behavior
- decision persistence
- feedback reconciliation
- script-vs-service write boundaries

If yes:
- keep the change small
- back it with tests
- document any changed assumptions
```
