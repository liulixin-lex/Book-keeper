# apideck-libraries/openapi-specs（Unified Accounting API）

- 分类：09 API 规范与标准
- 语言 / 许可证 / 最近提交：OpenAPI 3.x YAML / Apache-2.0 / 2026（accounting.yml 约 5 万行）
- 审查范围：`accounting.yml` 公共参数、Meta / Links、LedgerAccount、JournalEntry / JournalEntryLineItem 结构，路径清单

## 定位

统一会计 API：把 QuickBooks、Xero、NetSuite、Sage 等几十个记账系统抽象成一个规范模型。它代表了“各家记账系统的公共最小模型”，适合作为我们对外 API 的命名与字段参照。

## 设计要点

- **资源齐全**：ledger-accounts、journal-entries、general-ledger-transactions、invoices、bills、payments、bill-payments、credit-notes、expenses、customers、suppliers、tax-rates、tracking-categories、departments、locations、subsidiaries、fiscal-periods、attachments/{reference_type}/{reference_id}、bank-feed-accounts / statements、trial-balance、balance-sheet、profit-and-loss、aged-debtors/creditors；多数资源有 `/batch`；
- **LedgerAccount**：
  - `classification`（asset / equity / expense / liability / revenue / income / other_income / other_expense / costs_of_sales）；
  - `type`（accounts_payable / accounts_receivable / bank / credit_card / current_asset / fixed_asset / current_liability / non_current_liability / equity / expense / revenue / sales…）；
  - 另有 `sub_type`、`nominal_code` / `code`、`fully_qualified_name`、`parent_account` / `sub_accounts`、`level`、`header`（分组科目）、`currency`、`opening_balance` / `current_balance`、`last_reconciliation_date`、`row_version`；
- **JournalEntry**：`number`、`journal_symbol`、`currency` + `currency_rate`、`posted_at`、`status`、`memo`、`accounting_period`、`tax_inclusive`、`tracking_categories`、**`source_type` + `source_id`**、`attachments`、`custom_fields`、`row_version`；
- **JournalEntryLineItem**：`type`（debit / credit）、`total_amount`、**`base_currency_amount`**、`ledger_account`、`tracking_categories`、`customer` / `supplier` / `employee`、`department_id`、`location_id`、`line_number`、`source_id`；
- **列表约定**：`cursor` 分页（`meta.cursors.previous/current/next`、`links.previous/current/next`、`meta.items_on_page`、`total_count`）、`limit` 1–200（默认 20）、`filter[...]` / `sort[by,direction]`、**`fields` 稀疏字段选择**、`raw`（附带原始响应调试）、`pass_through`；
- **`row_version`**：乐观并发版本号；`meta.warnings`：非致命警告（请求成功但某些可选步骤降级）；
- `x-apideck-weights`：字段重要程度（critical / high / medium / low / edge-case），说明哪些字段是跨系统公共核心。

## 可借鉴

- [AD-1] 科目 `classification` + `type` + `sub_type` 三层分类，`header` 标记分组科目。
- [AD-2] 分录行 `base_currency_amount` 与原币金额并存；行级维度（部门、地点、往来方、跟踪类别）。
- [AD-3] 游标分页 + meta / links 结构 + 稀疏字段 `fields`。
- [AD-4] `row_version` 乐观并发；`meta.warnings` 非致命警告。
- [AD-5] 附件以 `{reference_type}/{reference_id}` 多态挂载到任意实体。
- [AD-6] 字段重要度权重：设计数据模型时区分核心字段与边缘字段。

## 不采用 / 风险

- 统一模型为兼容多家系统而宽松（大量可选字段），我们的内部模型应更严格。

## 对新系统的启示

1. 对外 API 字段命名尽量与该统一模型一致（便于未来对接其他系统导出/导入）；
2. 列表接口：`cursor` + `limit` + `filter` + `sort` + `fields`；响应 `{data, meta:{cursors, total_count, warnings}, links}`；
3. 所有可变实体带 `version`（整数），更新须提交 `If-Match`。
