# 观察池与风向标 MVP 设计

## 1. 文档目的

本文档重新定义观察池、风向标和候选基金适配分析在 `fund-manager` 中的正确位置，并给出当前代码状态下的推荐落地方式。

它们不应该被理解成“AI 荐基功能”，而应该被理解成：

> `fund-manager` 内部的 deterministic research signal layer

也就是说，这些能力属于研究型读模型，不是 canonical accounting truth，也不是自动交易指令。

## 2. 背景

当前 `fund-manager` 已经覆盖：
- canonical portfolio truth
- fund master / NAV / snapshot / metrics
- policy / daily decision / feedback / reconciliation
- weekly review / monthly strategy debate

但实际使用中还存在另一类需求：
- 当前市场有哪些基金方向值得观察
- 哪些基金适合作为风向标来判断风格切换
- 某只候选基金与当前组合是互补、重复，还是高 beta 重复暴露

这类需求很重要，但如果实现方式不清晰，很容易让系统边界变形：
- 把观察结果误当成 canonical truth
- 把 research signal 误当成 policy action
- 把 AI 文本推荐误当成 deterministic result

因此，必须先把定位讲清楚，再谈实现。

## 3. 正确定义

### 3.1 观察池是什么

观察池是一个 deterministic 的候选基金集合视图。

它回答的问题是：
- 哪些基金值得继续跟踪
- 它们和当前组合的关系是什么
- 它们应该被放在什么类型的观察名单中

它不回答：
- 今天该不该买
- 该买多少
- 是否应该直接改 policy

### 3.2 风向标是什么

风向标是一个 deterministic 的风格代表集合视图。

它回答的问题是：
- 当前某类风格里有哪些代表基金值得盯
- 哪些基金更适合作为风格跟踪器而不是交易对象

它不是：
- 市场预测引擎
- 自动择时信号
- 交易触发器

### 3.3 Candidate Fit 是什么

candidate fit 是一个 deterministic 的“候选基金 vs 当前组合”的适配分析。

它回答的问题是：
- 这只基金与现有组合重合度高不高
- 它更像互补暴露还是重复暴露
- 它是否属于高 beta 的重复风险

它不是：
- 买入建议
- policy override
- execution command

## 4. 在系统中的位置

在新的系统模型下，这一层明确属于 `Research Signals`。

它的特征应该是：
- deterministic
- explainable
- read-only
- non-canonical
- non-executing

因此它和其他对象的关系应当是：
- `canonical facts`
  - 提供输入
- `deterministic decisions`
  - 不直接被替代
- `research signals`
  - 观察池、风向标、candidate fit 属于这一类
- `AI narratives`
  - 可以引用这些 signals 做解释
- `human execution feedback`
  - 与观察池没有直接写路径关系

## 5. 当前代码中的落点

当前仓库里，这一层的最直接落点是：
- `src/fund_manager/core/watchlist/service.py`

它的职责应该持续保持在 deterministic service 范畴内：
- 加载 candidate universe 与 seed metadata
- 生成 watchlist candidates
- 生成 style leaders
- 生成 candidate fit

它不应该：
- 依赖 prompt
- 依赖某个模型 provider
- 直接把 signal 改写为 policy truth

与 AI workflow 的关系应该是：
- signal outputs 可以进入 `core/fact_packs.py` 里的 workflow inputs
- AI 只消费这些 signal 作为 context
- AI 输出仍然落到 `core/ai_artifacts.py` 的 artifact contract

## 6. 设计目标

本 MVP 的目标不是做“智能荐基”，而是做一层轻量、稳定、可解释的研究读模型。

MVP 目标包括：
1. 输出结构化 watchlist candidates
2. 输出按风格分组的 style leaders
3. 输出单只候选基金与当前组合的 fit 分析
4. 通过本地 service + 至少一种入口（CLI / API / MCP）可用
5. 可作为 weekly review / strategy debate 的上下文输入

## 7. 明确边界

### 7.1 属于 `fund-manager` 的内容

- deterministic universe 筛选
- 候选基金分类与打分
- style leader 计算
- candidate fit 标签判定
- 可解释的 reason / caution / notes 生成
- 结构化 signal 输出

### 7.2 不属于 `fund-manager` 的内容

- 黑盒 AI 荐基
- 基于聊天上下文直接生成观察池
- 把观察池结果写成 policy truth
- 把观察池结果直接转成交易动作
- 因为某只基金在观察池里就默认应该买入

### 7.3 AI 的正确用法

AI 可以：
- 解释观察池变化
- 比较本期与上期 signal
- 把 watchlist / style leader 写进 weekly review narrative
- 在 strategy debate 中引用 signal 作为论据

AI 不可以：
- 自己定义 watchlist score 的 canonical 结果
- 自己定义 fit label
- 把 narrative 反写成 signal truth

## 8. 输出对象设计

MVP 推荐保持三类 deterministic signal output。

### 8.1 Watchlist Candidates

输入：
- `portfolio_id` 或 `portfolio_name`
- `as_of_date`
- `risk_profile`
- `max_results`
- `include_categories`
- `exclude_high_overlap`

输出：
- `core_watchlist`
- `extended_watchlist`

每个候选项包含：
- `fund_code`
- `fund_name`
- `category`
- `fit_label`
- `reason`
- `caution`
- `risk_level`
- `score`

### 8.2 Candidate vs Portfolio Fit

输入：
- `portfolio_id` 或 `portfolio_name`
- `fund_code`
- `as_of_date`

输出：
- `fit_label`
- `overlap_level`
- `estimated_style_impact`
- `reasoning`
- `notes`

### 8.3 Style Leaders

输入：
- `as_of_date`
- `categories`
- `max_per_category`

输出：
- `leaders`

每个 leader 项包含：
- `fund_code`
- `fund_name`
- `category`
- `latest_nav_date`
- `latest_unit_nav_amount`
- `leader_reason`
- `caution`

## 9. 规则设计原则

MVP 阶段坚持三条原则：

### 9.1 先规则，后模型

先用 deterministic rule 做：
- 筛选
- 分组
- 打分
- fit label

不要一开始就做黑盒排序模型。

### 9.2 先可解释，后复杂化

每一个输出都应该能回答：
- 为什么入选
- 为什么排在这里
- 它的主要 caution 是什么

### 9.3 先轻量 Universe，后扩大全市场

MVP 推荐先做：
- 精选基金 universe
- 手工维护标签
- 稳定规则

而不是一开始就尝试全市场自动分类。

## 10. 数据模型建议

MVP 推荐继续走轻量方案：

### 10.1 首选：Seed Data

使用：
- `fund_manager/data/watchlist_seed.json`

保存：
- 基金类别
- 风格标签
- 风险等级
- 是否适合 watchlist
- 是否适合 leader

优点：
- 轻量
- 易维护
- 适合规则快速迭代

### 10.2 后续可选：Signal 配置表

如果未来需要更强的维护能力，再考虑增加单独的 research-signal metadata 表，例如：
- `fund_signal_profile`
- `signal_snapshot`

但即使增加，也应视为 research metadata，不应并入 canonical accounting tables。

## 11. 服务层设计

推荐继续以一个 deterministic service 为核心：

### `FundWatchlistService`

职责：
- 加载 universe / tags
- 生成 watchlist candidates
- 生成 style leaders
- 分析 candidate fit

依赖：
- `FundMasterRepository`
- `NavSnapshotRepository`
- `PortfolioReadService`

关键要求：
- 输入是结构化 portfolio context
- 输出是 deterministic DTO
- 不直接依赖 prompt 或 AI runtime

## 12. 接口设计

### 12.1 CLI

优先保持可本地验证：

- `fund-manager-admin watchlist candidates --portfolio-id 1 --as-of-date 2026-04-13`
- `fund-manager-admin watchlist leaders --as-of-date 2026-04-13`
- `fund-manager-admin watchlist fit --portfolio-id 1 --fund-code 010685 --as-of-date 2026-04-13`

### 12.2 API

推荐暴露：
- `GET /api/v1/watchlist/candidates`
- `GET /api/v1/watchlist/style-leaders`
- `GET /api/v1/watchlist/fit`

### 12.3 MCP / Typed Tools

如果需要给外部 runtime 使用，可暴露：
- `watchlist_candidates`
- `watchlist_style_leaders`
- `watchlist_candidate_fit`

## 13. 与 Workflow 的集成方式

### 13.1 Weekly Review

可以把 research signal 作为 `WeeklyReviewFacts` 的一部分或附加 section：
- 观察池变化
- 风格风向标
- 新增值得跟踪的候选

### 13.2 Strategy Debate

可以把 signal 作为 `StrategyDebateFacts` 的一部分论据输入：
- 为什么认为当前组合缺少某类暴露
- 为什么某只候选更像互补而不是重复

### 13.3 Daily Decision

不建议直接把 signal 变成 deterministic daily action。

换句话说：
- research signals 可以进入 context
- 但不能直接覆写 deterministic decision

## 14. 测试建议

### 单元测试

至少覆盖：
- universe 过滤
- score 规则
- fit label 判定
- empty / missing nav / overlap 边界情况

### 集成测试

至少覆盖：
- service 在真实 portfolio context 中可运行
- CLI / API 输出结构稳定
- 缺失 seed 或缺失 NAV 时的 graceful degradation

## 15. MVP 验收标准

满足以下条件即可视为 MVP 可用：
1. 能基于给定 portfolio 输出结构化 watchlist
2. 能对单只基金输出 fit 分析
3. 能输出按类别分组的 style leaders
4. 输出结果是 deterministic、可解释、可测试的
5. 至少有一个稳定入口可调用
6. 不触碰 canonical accounting truth
7. 不隐式制造交易建议或执行语义

## 16. 当前最合理的后续动作

按当前仓库状态，最值得继续推进的是：
1. 把 signal outputs 的 transport 表达补齐到 API / CLI / MCP
2. 为 signal outputs 增加 provenance 字段，例如 `as_of_date`、`seed_version`、`rule_version`
3. 让 weekly review / strategy debate 在 fact pack 层显式接入 signal sections

## 17. 最终定位

这个能力的正确名称不是“智能荐基”，而是：

> 基于 deterministic rule 的 research signal layer

它的价值在于：
- 让观察池讨论结构化
- 让风格风向标可复用
- 让候选基金适配分析可解释
- 为 weekly review、strategy debate、OpenClaw 编排提供稳定输入

它不应该成为：
- 交易系统的隐式入口
- AI 直觉输出的包装层
- policy truth 的替代品
