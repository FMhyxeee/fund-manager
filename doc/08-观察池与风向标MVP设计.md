# 观察池 / 风向标 / 候选基金适配分析 MVP 设计

## 1. 背景

当前 `fund-manager` 已经覆盖：

- canonical 投资数据与组合持仓 truth
- 净值 / 基金资料读写与同步
- portfolio snapshot / metrics / policy / decision / review 等 read-model 与 workflow

但在实际使用中，还存在一类明显需求：

- 当前市场有哪些基金方向值得观察？
- 哪些基金适合当“风向标”，用来判断市场风格是否在切换？
- 某只候选基金与当前组合是高重合、互补，还是只是另一种高波动重复暴露？

这类能力不应被实现为黑盒“自动荐基”，而应沉淀为 `fund-manager` 的基金域 read-model intelligence：

- 观察池（watchlist candidates）
- 风向标池（style leaders / market radar）
- 候选基金与当前组合适配分析（candidate vs portfolio fit）

## 2. 目标

本 MVP 目标是新增一个轻量、可解释、可复用的只读分析层，用于输出：

1. 核心观察池与扩展观察池
2. 按风格/主题分组的强势风向标池
3. 单只候选基金与当前组合的适配分析

要求：

- 不修改 canonical 持仓 / 账本 truth
- 不自动生成交易指令
- 可通过本地 service + 至少一种入口（CLI/API/MCP）验证
- 可集成进 weekly review / strategy debate 等后续 workflow

## 3. 明确边界

### 3.1 属于 `fund-manager` 的内容

- 基于基金 universe 的筛选、打分、分组
- 基于净值历史、收益、回撤、波动的 read-model 计算
- 基金风格/主题标签维护
- 候选基金与 portfolio 的重合度 / 补充度分析
- 观察池与风向标池的结构化输出

### 3.2 不属于 `fund-manager` 的内容

- 自动买卖建议执行
- 对 canonical accounting truth 的直接写入
- 黑盒荐基 / 无解释推荐
- 把观察池结果写成 policy truth 或决策 truth

## 4. MVP 范围

按优先级：

### P1. watchlist candidates

输入：

- `portfolio_id` / `portfolio_name`（可选）
- `as_of_date`
- `risk_profile`（`conservative` / `balanced` / `aggressive`）
- `max_results`
- `include_categories`（可选）
- `exclude_high_overlap`（默认 true）

输出：

- `core_watchlist`
- `extended_watchlist`
- 每只基金包含：
  - `fund_code`
  - `fund_name`
  - `category`
  - `fit_label`
  - `reason`
  - `caution`

### P2. candidate vs portfolio fit

输入：

- `portfolio_id` / `portfolio_name`
- `fund_code`
- `as_of_date`

输出：

- `fit_label`
  - `overlap_high`
  - `complementary`
  - `defensive_addition`
  - `high_beta_duplicate`
  - `neutral`
- `overlap_level`
- `estimated_style_impact`
- `reasoning`
- `notes`

### P3. style leaders

输入：

- `as_of_date`
- `categories`
- `max_per_category`
- `lookback_window`（默认支持 1m / 3m）

输出：

- 分组的 `leaders`
  - `technology_growth`
  - `healthcare_recovery`
  - `broad_index`
  - `consumer`
  - `defensive_dividend`
- 每只基金包含：
  - 区间收益
  - 回撤
  - 波动
  - `leader_reason`
  - `caution`

## 5. 数据模型建议

MVP 不建议一开始做全市场自动分类，先走“精选基金 universe + 手工标签”的轻量方案。

### 5.1 新增 read-model 表（建议）

#### `fund_watchlist_profile`

字段建议：

- `fund_id`
- `fund_code`
- `category`（如 `healthcare`, `broad_index`, `consumer`, `technology_growth`, `defensive_dividend`）
- `style_tags_json`（数组）
- `is_watchlist_eligible`
- `is_leader_eligible`
- `risk_level`
- `notes`
- `created_at`
- `updated_at`

说明：

- MVP 可先对 30~100 只重点基金维护这张表
- 先手工维护，不追求自动化

### 5.2 若不想先建表

MVP 也可先用：

- `data/watchlist_seed.json`
- 或 `data/watchlist_seed.csv`

先跑起来，再决定是否迁表。

## 6. 评分与规则（MVP 简化版）

### 6.1 watchlist score

建议使用可解释规则，不做复杂模型：

`watch_score = relevance_score + diversification_bonus + recovery_bonus - overlap_penalty - overheating_penalty`

说明：

- `relevance_score`：是否属于本轮关注方向
- `diversification_bonus`：是否补当前组合空白暴露
- `recovery_bonus`：是否属于“可观察修复方向”
- `overlap_penalty`：与当前组合高重合则扣分
- `overheating_penalty`：短期涨幅过热则扣分

### 6.2 leader score

`leader_score = return_strength + persistence_score - drawdown_penalty`

说明：

- 不只看涨幅，也要看强势持续性
- 回撤过大或极端波动可以适度降权

### 6.3 fit 规则

候选基金 vs 当前组合的 `fit_label` 可先走规则法：

- 当前组合已有明显同类暴露 + 候选基金高 beta：`high_beta_duplicate`
- 当前组合缺该类暴露：`complementary`
- 当前组合偏进攻 + 候选基金偏防守：`defensive_addition`
- 当前组合已有同类宽基 / 主题：`overlap_high`
- 其他：`neutral`

## 7. 服务层建议

建议新增 service：

### `FundWatchlistService`

负责：

- 加载候选基金 universe / 标签
- 计算观察池
- 计算风向标池
- 生成单基金 fit 分析

建议方法：

- `build_watchlist_candidates(...)`
- `build_style_leaders(...)`
- `analyze_candidate_fit(...)`

依赖：

- `FundMasterRepository`
- `NavSnapshotRepository`
- 现有 `PortfolioReadService` / `PortfolioService`（只读）

## 8. 对外接口建议

### 8.1 CLI

建议先补 admin CLI，最容易验证：

- `fund-manager-admin watchlist candidates --portfolio-id 1 --as-of-date 2026-04-13`
- `fund-manager-admin watchlist leaders --as-of-date 2026-04-13`
- `fund-manager-admin watchlist fit --portfolio-id 1 --fund-code 010685 --as-of-date 2026-04-13`

### 8.2 API

后续补：

- `GET /api/v1/watchlist/candidates`
- `GET /api/v1/watchlist/style-leaders`
- `GET /api/v1/watchlist/fit`

### 8.3 MCP / typed tools

等 service 稳定后补：

- `watchlist_candidates`
- `watchlist_style_leaders`
- `watchlist_candidate_fit`

## 9. 测试建议

### 单元测试

覆盖：

- universe 过滤
- watch_score / leader_score 规则输出
- fit_label 判定
- empty / missing nav / high overlap 边界情况

### 集成测试

覆盖：

- CLI 输出结构
- service 在真实 portfolio 上可运行
- 对缺失标签、缺失净值的 graceful degrade

## 10. 与现有 workflow 的集成方向

MVP 不强制接 workflow，但设计上应方便接入：

- weekly review：追加“观察池变化 / 风格雷达”段落
- strategy debate：作为论据输入
- daily decision：仅作为 context，不直接变成动作建议

## 11. 建议实施顺序

### 第一步

- 先落 `watchlist_seed` 数据源（少量精选基金）
- 实现 `FundWatchlistService`
- 跑通 service + CLI

### 第二步

- 补单元测试 / 集成测试
- 优化输出结构
- 验证对当前组合的 fit 分析可解释性

### 第三步

- 再考虑 API / MCP 暴露
- 再考虑 workflow 集成

## 12. MVP 验收标准

满足以下即可认为 MVP 可用：

1. 能基于给定 portfolio 输出核心/扩展观察池
2. 能对单只候选基金输出 fit 分析
3. 能按类别输出强势风向标基金
4. 有至少一种稳定入口（建议先 CLI）
5. 有测试覆盖关键规则
6. 不触碰 canonical 持仓 / 账本写入

## 13. 备注

该功能的正确定位是：

> 基金域 read-model intelligence / watchlist radar

而不是“自动荐基”。

它的价值在于：

- 让观察池与风向标讨论结构化
- 让组合上下文中的候选基金分析可解释
- 为后续周报、策略讨论、OpenClaw 调用提供稳定接口
