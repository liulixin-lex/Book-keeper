# 16 接口索引（由代码生成）

> 由 `v2/scripts/contracts.py` 根据 OpenAPI 与 MCP 工具注册表生成，请勿手工修改。
> 版本 2.0.0；REST 账套接口前缀 `/api/v1/books/{book_id}`（表中以 `…` 表示）。设计说明见 08（REST）与 09（MCP）号文档。

## REST

### accounts

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `…/accounts` | ledger:read | List Accounts |
| POST | `…/accounts` | config:write | Create Account |
| GET | `…/accounts/{account_ref}` | ledger:read | Get Account |
| PATCH | `…/accounts/{account_ref}` | config:write | Update Account |
| POST | `…/accounts:apply-template` | config:write | Apply Template |

### ai

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `…/ai/providers` | admin:read | Providers without keys (only the last 4 characters). |
| POST | `…/ai/providers` | config:write，仅网页端 | Add a provider; the key is sealed with BK_MASTER_KEY. Web app only. |
| DELETE | `…/ai/providers/{provider_id}` | config:write，仅网页端 | Remove a provider and drop it from task routing. Web app only. |
| PATCH | `…/ai/providers/{provider_id}` | config:write，仅网页端 | Change a provider; a new Base URL needs the key again. Web app only. |
| POST | `…/ai/providers/{provider_id}:test` | config:write，仅网页端 | A tiny request to the provider: does it answer, which models does it list. |
| GET | `…/ai/routes` | admin:read | Provider + model per task (识别, AI 助手), in fallback order. |
| PUT | `…/ai/routes` | config:write，仅网页端 | Set the provider + model order per task. Web app only. |
| GET | `…/ai/status` | ledger:read | Whether each AI task can run (a provider is routed, or BK_AI_* is set). No configuration details. |
| GET | `…/ai/usage` | admin:read | Calls, tokens and estimated cost per provider, model and task. |

### audit

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `…/audit-events` | admin:read | List Events |
| GET | `…/audit-events/verify` | admin:read | Verify |
| GET | `…/change-sets` | ledger:read | List Change Sets |
| GET | `…/change-sets/{change_set_id}` | ledger:read | Get Change Set |

### auth

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `/api/v1/auth/login` | — | Login |
| POST | `/api/v1/auth/logout` | — | Logout |
| GET | `/api/v1/auth/me` | — | Me |
| POST | `/api/v1/auth/password` | — | Change Password |

### books

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/v1/books` | — | List Books |
| POST | `/api/v1/books` | — | Create Book |
| GET | `…` | ledger:read | The book, your role and permissions, and the token tiers you may hand out (ordinary members: user tiers). |
| PATCH | `…` | admin | Update Book |
| GET | `…/members` | admin:read | List Members |
| DELETE | `…/members/{user_id}` | admin | Remove Member |
| PUT | `…/members/{user_id}` | admin | Set Member |

### business

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `…/fee-rules` | admin:read | List Fee Rules |
| POST | `…/fee-rules` | config:write | Create a rule or a new version (same code, later valid_from). Existing postings keep their |
| POST | `…/fee-rules/{code}:retire` | config:write | Retire Fee Rule |
| GET | `…/fee-rules:evaluate` | ledger:read | Which rule applies and the fee it gives — the same selection used when posting. |
| GET | `…/transaction-types` | ledger:read | How to enter each type: input schema, an example request and the default accounts. |

### exports

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `…/exports/{fmt}` | ledger:read | Journal lines of the range (all when omitted) in entry order; the Beancount file passes bean-check. |

### files

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `…/attachments` | ledger:write | Create Attachment |
| POST | `…/files` | ledger:write 或 import:write | Upload File |
| GET | `…/files/{file_id}` | files:read | Get File |
| GET | `…/files/{file_id}/content` | files:read | Download File |

### health

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/healthz` | — | Healthz |
| GET | `/readyz` | — | Readyz |

### imports

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `…/import-batches` | ledger:read | 批次列表，新的在前。每批带 `open_records`：尚未入账的记录数（待补全的，以及已补全、等完成导入的）。 |
| POST | `…/import-batches` | import:write | Structured records (e.g. read by an AI from screenshots) or an uploaded file_id → staged batch. |
| GET | `…/import-batches/{batch_id}` | ledger:read | Get Batch |
| POST | `…/import-batches/{batch_id}:commit` | import:write | Commit Batch |
| POST | `…/import-batches/{batch_id}:decide-matches` | import:write | Answer all of a batch's "may already be booked" questions at once. |
| POST | `…/import-batches/{batch_id}:retry` | import:write | Read a batch whose AI read failed again, with the same files. |
| POST | `…/import-batches/{batch_id}:revert` | import:write | Revert Batch |
| POST | `…/import-batches:upload` | import:write | Upload a statement and stage it as a batch. An AI 识别 source returns at once with a batch 识别中 that the |
| GET | `…/import-sources` | ledger:read | List Sources |
| POST | `…/import-sources` | import:write | Create Source |
| PATCH | `…/import-sources/{ref}` | import:write | Update Source |
| POST | `…/import-sources:preview` | import:write | Try a source setup on a sample file before saving it: the file's top rows, the records it would read |
| GET | `…/match-suggestions` | ledger:read | Pending suggestions (oldest first); ``batch_id`` narrows them to one import. |
| POST | `…/match-suggestions/{suggestion_id}:accept` | import:write | Accept |
| POST | `…/match-suggestions/{suggestion_id}:reject` | import:write | Reject |
| GET | `…/pairing-rules` | admin:read | List Pairing |
| POST | `…/pairing-rules` | rules:write | Save Pairing |
| GET | `…/rules` | admin:read | List Rules |
| POST | `…/rules` | rules:write | Save Rule |
| POST | `…/rules/{ref}:disable` | rules:write | Disable Rule |
| POST | `…/rules/{ref}:enable` | rules:write | Enable Rule |
| POST | `…/rules:apply` | import:write | Apply Rules |
| POST | `…/rules:test` | ledger:read | Test Rule |
| GET | `…/source-records` | ledger:read | Search Records |
| PATCH | `…/source-records/{record_id}` | import:write | Classify |
| POST | `…/source-records/{record_id}:link` | import:write | Link |
| POST | `…/source-records:ignore` | import:write | Ignore |

### jobs

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `…/jobs/{job_id}` | ledger:read | Get Job |

### ledger

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `…/balances` | ledger:read | Get Balances |
| GET | `…/check-runs` | ledger:read | List Check Runs |
| GET | `…/check-runs/{run_id}` | ledger:read | Get Check Run |
| POST | `…/checks:run` | ledger:read | Run Checks |
| GET | `…/journal-entries` | ledger:read | List Entries |
| GET | `…/journal-entries/{ref}` | ledger:read | Get Entry |
| GET | `…/reports/trial-balance` | ledger:read | Trial Balance |

### meta

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/v1/meta/capabilities` | — | Capabilities |
| GET | `/api/v1/meta/enums` | — | Enums |

### operations

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| POST | `…/change-sets/{change_set_id}:undo` | ledger:write | Revert every write of one request by appending: delete what it created, restore what it deleted, |
| GET | `…/mcp-calls` | admin:read | Mcp Calls |
| GET | `…/work-items` | ledger:read | Work Items |
| GET | `…/work-items/summary` | ledger:read | Work Summary |

### reference

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `…/commodities` | ledger:read | List Commodities |
| POST | `…/commodities` | config:write | Add a currency or unit; it is shared by all books. |
| PATCH | `…/commodities/{code}` | config:write | Update Commodity |
| GET | `…/commodity-price-rules` | ledger:read | List Price Rules |
| POST | `…/commodity-price-rules` | config:write | Create Price Rule |
| GET | `…/counterparties` | ledger:read | List Counterparties |
| POST | `…/counterparties` | reference:write | Create Counterparty |
| GET | `…/counterparties/{counterparty_id}` | ledger:read | Get Counterparty |
| PATCH | `…/counterparties/{counterparty_id}` | reference:write | Update Counterparty |
| POST | `…/counterparties/{counterparty_id}/accounts` | reference:write | Add Counterparty Account |
| POST | `…/counterparties/{counterparty_id}/aliases` | reference:write | Add Alias |
| GET | `…/counterparties:resolve` | ledger:read | Resolve Counterparty |
| POST | `…/dimension-types` | config:write | Create Dimension Type |
| POST | `…/dimension-types/{type_code}/values` | reference:write | Create Dimension Value |
| PATCH | `…/dimension-values/{value_id}` | reference:write | Update Dimension Value |
| GET | `…/dimensions` | ledger:read | List Dimensions |
| GET | `…/fx-rates` | ledger:read | List Fx Rates |
| POST | `…/fx-rates` | config:write | Add Fx Rate |
| GET | `…/tags` | ledger:read | Tags in use with their transaction counts (set them on transactions via create / PATCH ``tags``). |

### reports

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `…/reports` | ledger:read | Available reports with their parameters; every report row carries a ``drilldown``. |
| GET | `…/reports/credit-purchases` | ledger:read | Credit Purchases |
| GET | `…/reports/fees` | ledger:read | Fees |
| GET | `…/reports/income-statement` | ledger:read | Income Statement |
| GET | `…/reports/operations` | ledger:read | Operations |
| GET | `…/reports/query` | ledger:read | Query |
| GET | `…/reports/sales` | ledger:read | Sales |
| GET | `…/reports/summary` | ledger:read | Summary |

### tokens

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `…/tokens` | ledger:read | List Tokens |
| POST | `…/tokens` | ledger:read（令牌另需 admin） | Create Token |
| POST | `…/tokens/{token_id}:revoke` | ledger:read（令牌另需 admin） | Revoke Token |
| POST | `…/tokens/{token_id}:rotate` | ledger:read（令牌另需 admin） | Rotate Token |

### transactions

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `…/transactions` | ledger:read | List Transactions |
| POST | `…/transactions` | ledger:write | Create Transaction |
| DELETE | `…/transactions/{ref}` | ledger:write | Delete (the entry is reversed; history stays). ``:restore`` or undoing the change set brings it back. |
| GET | `…/transactions/{ref}` | ledger:read | Get Transaction |
| PATCH | `…/transactions/{ref}` | ledger:write | Change any field; ``inputs`` only needs the changed keys. Affects the books → re-posted in place. |
| GET | `…/transactions/{ref}/explain` | ledger:read | How the inputs became journal lines: resolved inputs, fee rule candidates and reasons, lines, links. |
| POST | `…/transactions/{ref}:restore` | ledger:write | Bring back a deleted transaction with the lines it had. |
| POST | `…/transactions:batch` | ledger:write | Record up to 200 transactions in one call. Results keep input order. |
| POST | `…/transactions:repost` | ledger:write | Re-run fee rules and rates on sales / credit purchases; append ?dry_run=true to see the effect first. |

### users

| 方法 | 路径 | 权限 | 说明 |
|---|---|---|---|
| GET | `/api/v1/users` | — | List Users |
| POST | `/api/v1/users` | — | Create User |

共 124 个 REST 操作。

## MCP 工具

| 工具 | 名称 | 类型 | 所需 scope | 共享操作 / REST |
|---|---|---|---|---|
| `apply_rules` | 执行规则 | 写 | import:write | rules.apply |
| `classify_records` | 分类来源记录 | 写 | import:write | source_records_classify |
| `commit_import` | 完成导入 | 高影响 | import:write | imports.commit |
| `create_transaction` | 记账 | 写 | ledger:write | transactions.create |
| `create_transactions` | 批量记账 | 写 | ledger:write | transactions.batch |
| `delete_transaction` | 删除交易 | 高影响 | ledger:write | transactions.delete |
| `evaluate_fee` | 试算手续费 | 只读 | ledger:read | fee_rules_evaluate |
| `explain_posting` | 解释分录 | 只读 | ledger:read | transactions_explain |
| `export_ledger` | 导出账本 | 只读 | ledger:read | exports_get |
| `get_admin_info` | 管理信息 | 只读 | admin:read | members_list |
| `get_audit_trail` | 审计记录 | 只读 | admin:read | audit_events_list |
| `get_balances` | 科目余额 | 只读 | ledger:read | balances_get |
| `get_context` | 账套上下文 | 只读 | ledger:read | meta_capabilities |
| `get_import_batch` | 导入批次 | 只读 | ledger:read | import_batches_get |
| `get_reference` | 基础资料 | 只读 | ledger:read | transaction_types_list |
| `get_transaction` | 交易详情 | 只读 | ledger:read | transactions_get |
| `import_records` | 导入账单 | 写 | import:write | import_batches_create |
| `list_pending_work` | 待处理事项 | 只读 | ledger:read | work_items_list |
| `manage_fee_rule` | 手续费规则 | 高影响 | config:write | fee_rules_save |
| `manage_import_source` | 导入来源 | 写 | import:write | import_sources_create |
| `manage_pairing_rule` | 配对规则 | 写 | rules:write | pairing_rules_save |
| `manage_rule` | 分类规则 | 写 | rules:write | rules_save |
| `query_ledger` | 自定义汇总 | 只读 | ledger:read | reports_query |
| `repost_transactions` | 按新规则重算 | 高影响 | ledger:write | transactions.repost |
| `resolve_match` | 处理匹配 | 写 | import:write | match_suggestions_accept |
| `restore_transaction` | 恢复交易 | 写 | ledger:write | transactions.restore |
| `revert_import` | 撤销导入 | 高影响 | import:write | imports.revert |
| `run_checks` | 健康检查 | 只读 | ledger:read | checks_run |
| `run_report` | 运行报表 | 只读 | ledger:read | reports_get |
| `search_accounts` | 查找科目 | 只读 | ledger:read | accounts_list |
| `search_counterparties` | 查找往来方 | 只读 | ledger:read | counterparties_list |
| `search_source_records` | 查找来源记录 | 只读 | ledger:read | source_records_list |
| `search_transactions` | 查找交易 | 只读 | ledger:read | transactions_list |
| `undo_change_set` | 撤销变更集 | 高影响 | ledger:write | change_sets.undo |
| `update_transaction` | 修改交易 | 写 | ledger:write | transactions.edit |
| `upsert_reference` | 维护基础资料 | 写 | reference:write | counterparties_create |

共 36 个工具；写工具另有 `dry_run` 与 `idempotency_key` 参数。
