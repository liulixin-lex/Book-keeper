# we-promise/sure（Maybe Finance 社区续作）

- 分类：06 个人/家庭财务
- 语言 / 许可证 / 最近提交：Ruby on Rails + PostgreSQL / AGPL-3.0 / 2026-10-18（原 maybe-finance/maybe 已归档，本仓库为社区延续）
- 审查范围：`app/models/{entry,account/*,balance/*,data_enrichment,concerns/enrichable,exchange_rate*,account_statement,family*}.rb`

## 定位

面向家庭的开源理财应用：多账户（银行、信用卡、投资、加密、房产、贷款）、几十种银行/券商连接器、预算、AI 助手、API。

## 数据模型

- **Entry**（账户条目：日期、金额、币种、名称、可多态为 Transaction / Valuation（估值/余额快照）/ Trade）；
- **Account Anchors**：每个账户以“期初锚点（opening anchor）”和“当前锚点”估值记录为边界，中间是交易、交易所成交与核对点；
- **Balance**（物化的每日余额，含开始/结束余额分量）；
- **DataEnrichment（字段级来源）**：记录某个实体的某个属性由谁设置（rule / ai / 各连接器 / 用户），配合 **字段锁**（用户手工修改的字段被锁定，之后同步或规则不会覆盖）；
- Exchange Rate / Pair、Account Statement（对账单）、Family（家庭多用户）、API Key。

## 算法

- **正向/反向余额计算器**：
  - 正向（ForwardCalculator）：从期初锚点按日累加流水；
  - **反向（ReverseCalculator）**：已知当前余额（连接器报告）时，从“今日期末”向过去逐日倒推期初；
  - **核对点（reconciliation waypoint）**：在有外部报告余额的日期把期末余额**硬重置**为报告值，消除缺失交易造成的漂移，同时保证当日交易只计一次；
  - 导入历史后自动把期初锚点移到最早条目之前，避免锚点落在序列中间导致倒推方向错误。
- 物化器（Materializer）把计算结果写入 balances 表，并做同步缓存。

## 可借鉴

- [SR1] **字段级来源 + 用户修改锁定**：自动化（规则/AI/导入）不得覆盖人工确认过的字段。
- [SR2] 余额锚点 + 外部报告余额作为核对点（重置漂移）——类似“余额断言”，但用于计算而非仅校验。
- [SR3] 反向计算（已知当前余额倒推历史）适合只有“当前余额截图”的上游站点。
- [SR4] 每日余额物化表。

## 不采用 / 风险

- 理财导向；“硬重置余额”在会计账本中不应修改账目，只应生成差异报告/调整分录（需人工确认）。
- AGPL。

## 对新系统的启示

1. 交易字段保存 `field_provenance`（来源：manual/rule:<id>/import:<batch>/mcp:<client>），人工修改即锁定，规则重算时跳过锁定字段；
2. 上游站点账户支持“余额观察记录”（截图、API 报告的余额 + 时间），系统计算账面余额与观察值的差异，差异超阈值生成待办；
3. 每日余额快照表（account, currency, date, balance）供报表与图表使用，回溯写入时失效重算。
