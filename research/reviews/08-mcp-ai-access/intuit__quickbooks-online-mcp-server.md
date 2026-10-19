# intuit/quickbooks-online-mcp-server（QuickBooks 官方 MCP）

- 分类：08 MCP / 外部 AI 接入
- 语言 / 许可证 / 最近提交：TypeScript / Apache-2.0 / 2026-09
- 审查范围：`src/tools/*`（142 个工具）、`src/handlers/*`、`src/auth-server.ts`、`src/types/tool-definition.ts`

## 定位

Intuit 官方 MCP：覆盖 QuickBooks Online 几乎全部实体与报表。

## 工具设计

- 142 个工具：create 25、update 26、delete 20、get 40、search 29、read 2；命名 `verb_object`（`create_journal_entry`、`search_journal_entries`、`get_balance_sheet`、`get_general_ledger`、`get_cash_flow`、`get_aged_receivables`…）；
- **参数直接采用 QBO API 原生结构**（`Line[].JournalEntryLineDetail.PostingType: Debit|Credit`、`AccountRef.value`），对象层用 `.passthrough()` 让未建模的合法字段原样转发；
- 描述里写易错点（如“Description 在 Line 层，不在 JournalEntryLineDetail 里”）；
- 搜索工具统一参数：`criteria[]`（字段/值/操作符）、`asc/desc` 排序、`limit/offset`、`count`、`fetchAll`；
- 返回：文本 + 原始 JSON；
- OAuth 2.0：本地回调服务获取并刷新令牌。

## 可借鉴

- [QB-1] 搜索类工具统一的查询参数（条件数组、排序、分页、只计数、取全部）。
- [QB-2] 描述中点明最常见的结构性错误。
- [QB-3] 报表工具覆盖三大报表、总账、账龄。

## 不采用 / 风险

- 工具数量过多（142 个）且与 API 一一对应：Agent 选择困难、`tools/list` 体积大；原生 API 结构复杂，AI 容易填错；`.passthrough()` 放宽了校验（与 Accounted 的 `additionalProperties:false` 相反）。
- 无 dry-run、无幂等键。

## 对新系统的启示

- 工具数量控制在 20–35 个任务级工具；统一 `search_*` 查询参数形态（filters、sort、page_size、cursor、count_only）；
- 输入 schema 严格（禁止未知字段），用业务友好结构（金额字符串、科目编码/名称），由服务端转换。
