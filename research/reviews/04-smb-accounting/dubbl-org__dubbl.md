# dubbl-org/dubbl

- 分类：04 中小企业会计软件（API-first，Xero/QuickBooks 替代）
- 语言 / 许可证 / 最近提交：TypeScript（Next.js + Drizzle + PostgreSQL）/ Apache-2.0 / 2026-10-11
- 审查范围：`README.md`、`lib/db/schema/{bookkeeping,audit,mcp}.ts`、`lib/money.ts`、`lib/mcp/{server,auth}.ts`、`lib/mcp/tools/*`（约 50 个工具文件）

## 定位

功能全面的开源会计平台（复式记账、发票、账单、银行、费用、库存、薪资、项目、CRM、固定资产、预算、税务、25+ 报表），完整 REST API + MCP 服务（OAuth 2.1）。

## 数据模型

- `currency`：代码、名称、符号、**小数位数**；`exchange_rate` 表；
- `fiscal_year`：起止日期、`is_closed`；`period_lock`：锁账日期；
- `chart_account`：code、name、type、sub_type、parent_id、currency_code、is_active、默认税率、**reporting_code（报表编码）**、**is_system（系统科目不可删）**、软删除；
- `journal_entry`：entry_number（组织内序号）、date、description、reference、fiscal_year、**source_type + source_id（来源：invoice/bill/expense/bank/payment/credit_note/debit_note/manual）**、created_by、posted_at、**voided_at + void_reason**、**auto_reverse_date（自动冲回日，用于计提）**、**reversed_by_entry_id / reverses_entry_id（冲销互指）**、软删除；
- `journal_line`：account、description、`debit_amount` / `credit_amount`（**整数最小单位**）、currency_code、**exchange_rate（整数，6 位小数定点）**、cost_center、project；
- `cost_center`（层级）、`tag` + `entity_tag`（任意实体打标签）、`attachment`；
- `audit_log`：用户、动作、实体类型/ID、`changes`（JSONB 差异）、IP、User-Agent；
- MCP：`mcp_oauth_client`、`mcp_oauth_code`、`mcp_access_token`（**仅存 SHA-256 哈希**、过期时间、角色）、`mcp_refresh_token`。

## 记账逻辑与算法

- 金额全部整数最小单位，**按 ISO 4217 的真实小数位（JPY 0、KWD 3）换算**；税率用基点（1000 = 10.00%）；汇率 6 位定点整数；
- 凭证状态 draft / posted / void；自动冲回计提凭证；期间锁定与会计年度关闭；
- 定期日记账、收入确认计划、计提计划、合并报表。

## API 与扩展（MCP）

- MCP 工具按领域拆分约 50 个文件（accounts、entries、bank-transactions、bank-rules、period-close、opening-balances、reports、bulk、trash、webhooks……）；工具描述中明确“金额为整数分”，参数用 zod 严格校验（分页上限 100）；
- MCP 访问令牌每次请求校验：哈希匹配、未过期、**成员关系仍然存在**（离职即失效），角色取当前成员角色；
- REST API Key 管理、Webhook、回收站（trash）。

## 可借鉴

- [DB1] 分录行存原币整数金额 + 定点整数汇率；币种表定义真实小数位。
- [DB2] 凭证来源（source_type/source_id）、作废原因、冲销互指、自动冲回日。
- [DB3] 科目 reporting_code 与 is_system 标记。
- [DB4] 审计日志记录 JSON 差异 + IP + UA。
- [DB5] MCP OAuth 2.1：令牌只存哈希、每次校验成员关系与角色。
- [DB6] MCP 工具按领域模块化，与 REST 共享服务层。
- [DB7] 任意实体打标签（多对多）。

## 不采用 / 风险

- 范围过大（薪资、CRM、库存）；审批工作流模块（用户要求去掉）。

## 对新系统的启示

1. 数据库字段：`amount_minor BIGINT` + `currency`；汇率 `rate_e12`（或 NUMERIC(30,12)）定点；
2. 交易表：来源、冲销互指、作废原因必填；
3. Token 表只存哈希；Token 与用户/角色绑定，用户停用即失效；
4. 审计日志存字段级差异与请求上下文（IP、UA、Token ID、request_id）。
