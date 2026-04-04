# 05-Codex 启动提示词

本文件提供一组适用于当前仓库状态的维护提示词。

使用前提：

- 先读 `AGENTS.md`
- 再读 `README.md` 和 `doc/`
- 先核对当前代码实现，再声明“已支持什么”

说明：

- 这不是产品文档
- 这是给工程代理用的工作提示词模板
- 以“当前仓库已实现内容”为默认上下文，不再按 bootstrap 阶段假设项目是空的

---

## 1. 仓库状态校准

```text
Read AGENTS.md, README.md, and all files under doc/ first.
Then inspect the current codebase before making claims.

Requirements:
- distinguish implemented features from planned features
- verify REST routes, scheduler jobs, and MCP tools from code
- keep deterministic accounting first and append-only history intact
- do not claim workflow or API support unless it exists in code
- update stale docs if code and docs diverge
```

---

## 2. 文档同步

```text
Read AGENTS.md, README.md, and doc/ first.
Audit all project documentation against the real repository state.

Requirements:
- treat README as the current-user entrypoint
- mark blueprint/high-level docs as planning documents where needed
- list exact implemented API routes, scheduler jobs, scripts, and MCP tools
- remove or rewrite claims that the code does not currently support
- keep docs concise and easy to scan
- summarize which docs were updated and what stale claims were fixed
```

---

## 3. Daily 数据同步增强

```text
Read AGENTS.md and doc/ first.
Extend the current daily fund sync flow without bypassing the service layer.

Context:
- the repository already has FundDataSyncService
- daily_snapshot already runs sync first, then saves portfolio_snapshot

Requirements:
- preserve deterministic accounting boundaries
- keep external API details inside data_adapters
- reuse repositories/services instead of writing ad hoc SQL in scripts
- update tests for sync summaries, failure handling, and downstream snapshot behavior
- update README and technical docs if user-facing behavior changes
```

---

## 4. REST API 扩展

```text
Read AGENTS.md, README.md, and doc/ first.
Add or refine FastAPI routes for already-implemented repository capabilities.

Examples:
- fund search
- fund NAV history
- strategy debate trigger
- daily sync trigger

Requirements:
- do not invent new accounting logic in the API layer
- keep API handlers thin
- route all authoritative computation through services or workflows
- return structured response models
- add route tests and refresh README endpoint tables
```

---

## 5. Weekly Review / Strategy Debate 增强

```text
Read AGENTS.md and doc/ first.
Improve the existing weekly review or monthly strategy debate workflows.

Requirements:
- preserve workflow traceability
- keep agent prompts separate from deterministic services
- save structured execution metadata
- verify persisted report/proposal outputs in tests
- update docs if workflow entrypoints or outputs change
```

---

## 6. MCP 扩展

```text
Read AGENTS.md, README.md, and doc/ first.
Extend the optional MCP service for read-oriented access.

Requirements:
- keep MCP tools read-only unless explicitly approved otherwise
- prefer existing tools/services over duplicating logic
- return JSON-safe payloads
- do not expose raw ORM objects
- document any new MCP tools in README and technical docs
```

---

## 7. 账本与快照相关修改

```text
Read AGENTS.md and doc/ first.
Modify accounting-related models or services carefully.

Requirements:
- every schema change must include a migration
- every accounting behavior change must include tests
- missing NAV must remain explicit and must not be coerced to zero
- append-only historical truth must be preserved
- document any changed accounting assumptions
```
