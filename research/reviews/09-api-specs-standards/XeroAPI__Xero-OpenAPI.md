# XeroAPI/Xero-OpenAPI

- 分类：09 API 规范与标准
- 语言 / 许可证 / 最近提交：OpenAPI 3.0 YAML / MIT / 2026（官方维护，xero_accounting.yaml 约 93 万字节、138 个路径）
- 审查范围：`xero_accounting.yaml` 公共参数、Journals / ManualJournals / BankTransactions / Reports / History / Attachments 路径与 Journal 结构，`xero-webhooks.yaml`

## 定位

主流云记账 SaaS 的官方 API 规范：会计、银行流水、资产、文件、工资、项目、Webhook。可作为“记账系统对外 API 应该长什么样”的工业参照。

## 值得采用的 API 约定

- **`Idempotency-Key` 请求头**（最长 128 字符）：所有创建/更新可安全重试；
- **`summarizeErrors` 参数**：批量写入时，`true` = 任一失败则整体返回 400 并汇总错误；`false` = 返回 200，逐条给出成功对象与带 `ValidationErrors` 的失败对象（`HasValidationErrors` 标记）；
- **`If-Modified-Since` 请求头**：只返回该时间之后创建或修改的记录（增量同步）；
- **`unitdp`**：单价可选 4 位小数；
- **`where` / `order` 过滤排序表达式**，`page` / `pageSize` 分页；
- **Journals（系统生成的总账分录）只读**，按 `JournalNumber` 连续编号；`offset=<JournalNumber>` 增量拉取全部分录；`paymentsOnly=true` 切换收付实现制视图（默认权责发生制）；每条 Journal 带 `SourceID + SourceType`（来自哪张单据）；
- 业务单据（Invoice、BankTransaction、ManualJournal…）与总账分录分离：单据可编辑/作废，总账分录由系统派生、不可直接改；
- **`/{Entity}/{id}/History`**：每个实体都有变更历史与备注；**`/{Entity}/{id}/Attachments`**：统一附件子资源；
- **Reports**：TrialBalance、BalanceSheet、ProfitAndLoss、AgedReceivables/Payables、BankSummary、BudgetSummary、ExecutiveSummary——以参数（日期、期间数、时间框架、跟踪类别）生成；
- Tracking Categories（最多两个跟踪维度）；LinkedTransactions（费用转嫁关联）；Allocations（贷项通知/预付款/超额付款分配到发票）；
- Webhook：事件（资源、事件类型、租户、时间）+ 签名校验 + “Intent to receive”验证握手。

## 可借鉴

- [XA-1] 幂等键请求头 + 批量写入的两种错误汇总模式。
- [XA-2] 增量同步：`If-Modified-Since` 与按连续分录号 `offset` 拉取。
- [XA-3] 单据与系统派生总账分录分离；总账分录只读、连续编号、带来源。
- [XA-4] 每个实体统一的 History 与 Attachments 子资源。
- [XA-5] 收付实现制 / 权责发生制双视图。
- [XA-6] Webhook 签名 + 订阅验证握手。

## 不采用 / 风险

- PascalCase 字段与包装数组（`{"Invoices":[...]}`）风格较旧；新系统采用 snake_case + 统一信封。

## 对新系统的启示

1. REST：`Idempotency-Key` 头必填于写接口；批量接口 `mode=atomic|partial`；
2. `GET /ledger-entries?after_seq=` 增量拉取不可变分录流；所有列表支持 `updated_since`；
3. 所有实体提供 `/history`（审计事件）与 `/attachments`（凭证）子资源。
