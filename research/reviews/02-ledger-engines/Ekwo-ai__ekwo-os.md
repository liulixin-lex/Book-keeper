# Ekwo-ai/ekwo-os

- 分类：02 账本引擎（Postgres 复式会计内核 + CLI + MCP）
- 语言 / 许可证 / 最近提交：SQL (Postgres/Supabase) + TypeScript / AGPL-3.0（格式库 MIT）/ 2026-10-18
- 审查范围：`README.md`、`supabase/migrations/*entries*.sql`（共 182 个迁移）、`packages/mcp/{README.md,src/server.ts,src/tools/*}`

## 定位

“会计规则即数据”的开源会计内核：整个复式记账逻辑以 Postgres schema、触发器和函数实现，Supabase 自动给出 REST + OpenAPI，行级安全（RLS）控制权限，再加一个 MCP 服务让 AI 以用户身份操作账簿。

## 数据模型

- **单据层与分录层分离**：document（发票、账单等业务单据）与 entry（会计分录）通过外键关联，一张单据最多对应一张分录；单据回答“业务是什么”，分录回答“科目怎么记”。
- `entries`：company、journal（日记账）、fiscal_year、`number`（**过账时才分配**，格式 `CODE/YYYY/NNNN`，草稿不占号）、entry_date、reference、state（draft/posted/cancelled）、document_id、`reversed_entry_id`、币种、`total_debit/total_credit`（触发器从分录行维护，**不允许手写**）、`is_balanced`（生成列）。
- CHECK：`state <> 'posted' or total_debit = total_credit`、已过账必须有编号。
- `entry_lines`：account、`debit/credit`（都 ≥0 且只有一侧非零）、`balance`（生成列 = debit−credit）、原币 `currency_code + amount_currency`、contact（往来方）、`date_maturity`（到期日，直接驱动账龄分析）、tax 与 `tax_line`、申报格子 `declaration_box/box_amount`、**核销字段 `matching_number`（核销标记）+ `matched_amount`（已核销金额，CHECK 不超过行金额）**。
- **冲销只翻转借贷方向，从不写负数。**
- 期间锁：`lock_date`（会计锁账日）与 `tax_lock_date`（税务锁账日）分开，触发器拒绝锁定日期及之前的写入；会计年度可关闭/重开/最终关闭。
- 编号：按日记账+年度的计数器行加锁分配，原子且连续。

## 记账逻辑与算法

- 分录只能由 schema 函数（`post_document`、`post_payment`、`reverse_entry`…）生成，函数内带会计规则；人只直接录入联系人、草稿单据、付款、银行流水。
- 税务规则、科目表、申报格式按国家打包为“country pack”（带版本与一年样例账作为验证）。
- 报表（试算平衡、总账、账龄、增值税申报、财务报表、财务分析指标）全部由数据库函数计算——“同一个余额只能有一个实现”。

## 追溯与审计

- 审计日志可通过 MCP 的 `read_audit_log` 读取；已过账分录不可删除、不可编辑，只能冲销或通过红字单据撤销。

## 导入、分类与对账

- 银行账户、银行流水导入（`import_bank_statement`）、`reconcile/unreconcile`、`settle_from_statement`（从流水直接核销）；整套历史账导入（`import_books`）与期初余额（`opening_balance`）。

## API 与扩展（重点：MCP）

- MCP 工具约 60 个，按任务命名：`list_companies`、`get_company`、`list_accounts`、`search_contacts`、`create_document`、`post_document`、`cancel_document`、`reverse_entry`、`record_payment`、`reconcile`、`import_bank_statement`、`trial_balance`、`general_ledger`、`financial_statement`、`lock_period`、`close_fiscal_year`、`read_audit_log`……另有 prompts（`close_month`、`prepare_vat_return`、`review_year`）。
- **服务端 INSTRUCTIONS**：握手时就告诉 Agent 第一次会话的正确顺序（先 list_companies → get_company 看年度与锁账日 → list_accounts → 搜联系人再建 → 建草稿给用户看 → 用户同意后过账），以及“如何更正”“被拒绝时怎么办”。
- **命名化拒绝**：数据库报错以错误名开头（`period_locked`、`entry_unbalanced`、`document_total_mismatch`、`reversal_date_needed`），后跟一句“下一步该做什么”，并要求 Agent 照做而不是绕过。测试会检查说明里提到的每个工具/错误都真实存在。
- **以用户身份行事**：拒绝 service_role 密钥；直连数据库模式必须指定 `ACT_AS_USER_ID` 并在事务内切换到该用户的 RLS 身份。
- 远程 MCP：Streamable HTTP、无状态；OAuth 2.1（RFC 9728 受保护资源元数据、RFC 8414、RFC 7591 动态注册），授权时用户选择是否允许写入。
- 金额统一为十进制字符串，日期 ISO，ID 为 UUID；未配置时仍能列出工具，调用返回 `not_configured` 并说明要设置什么。

## 可借鉴

- [EK1] 单据（业务）层与分录（会计）层分离，分录只能由过账函数生成。
- [EK2] 数据库层强制：已过账必须平衡、借贷单侧非负、汇总字段由触发器维护、锁账日触发器拒绝写入。
- [EK3] 草稿不占号，过账时按“日记账/年度”原子分配连续编号。
- [EK4] 冲销翻转借贷方向而非写负数；会计锁账与税务锁账分开。
- [EK5] 分录行级核销（matching_number + matched_amount，部分核销）与到期日（账龄）。
- [EK6] 报表只有一个实现（数据库函数），API/MCP/前端都调用它。
- [EK7] MCP：服务端 instructions 写清首次会话流程与更正规则；命名化错误 + 下一步提示；以用户身份执行、拒绝超级密钥；OAuth 远程接入；用户授权时选择只读/可写。
- [EK8] 规则（税、科目表、申报格式）作为带版本的数据包，并附样例账验证。

## 不采用 / 风险

- AGPL-3.0：只参考设计。
- 依赖 Supabase（PostgREST + RLS）；我们可用自托管 Postgres + 应用层权限实现同等约束。
- 增值税/电子发票/各国申报对当前业务不需要。

## 对新系统的启示

1. 业务单据（来源凭证/订单/流水）与会计分录分层，分录只能由“过账服务”生成。
2. 数据库约束 + 触发器兜底平衡、锁账、编号；应用层校验只是第一道防线。
3. MCP 设计照搬这套“instructions + 任务型工具 + prompts + 命名化错误 + 以 Token 所属用户身份执行”的模式。
4. 分录行支持部分核销与往来方，用于订单↔兑换、收入↔到账的匹配。
5. 所有报表在服务端单一实现。
