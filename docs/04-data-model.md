# 04 数据模型

> 数据库：PostgreSQL 18。命名：表名复数 snake_case；主键 `id TEXT`，值为 `<前缀>_<ULID>`。
> 通用列（除特别说明外每张可变表都有）：`created_at timestamptz NOT NULL DEFAULT now()`、`updated_at timestamptz`、`version integer NOT NULL DEFAULT 1`。
> 金额列：`bigint`，单位为该商品的最小单位（由 `commodities.scale` 决定），**借方为正、贷方为负**。汇率：`numeric(28,12)`。
>
> 2026-10-19 迁移 0011 精简了数据模型（17 号文档 §6）：下文已删去期间、锁账、预览、对账、核销、余额断言等表与相关列。

## 1. 实体关系总览

```
books ─┬─ book_members ── users ── sessions
       ├─ api_tokens / oauth_grants
       ├─ accounts (树) ── account_balances / daily_balances
       ├─ dimension_types ── dimension_values
       ├─ counterparties ─┬─ counterparty_aliases
       │                  └─ counterparty_accounts
       ├─ transaction_types
       ├─ fee_rules (版本)
       ├─ transactions ─┬─ transaction_sources ── source_records ── import_batches ── sources
       │                ├─ transaction_links
       │                └─ journal_entries ── journal_lines ── journal_line_dimensions
       ├─ rules ── rule_runs
       ├─ match_suggestions / match_exclusions / pairing_rules
       ├─ files ── attachments（多态）
       ├─ audit_events / change_sets / idempotency_keys / mcp_calls
       └─ outbox_events ── webhook_endpoints ── webhook_deliveries
全局：commodities、fx_rates、jobs、job_schedules
```

## 2. ID 前缀

| 前缀 | 实体 | 前缀 | 实体 |
|---|---|---|---|
| `usr` | users | `txn` | transactions |
| `ses` | sessions | `tln` | transaction_links |
| `bk` | books | `jen` | journal_entries |
| `tok` | api_tokens | `jln` | journal_lines |
| `oac` / `ogr` | oauth_clients / oauth_grants | | |
| `cpr` | commodity_price_rules | | |
| `fxr` | fx_rates | `src` | sources |
| `acc` | accounts | `imb` | import_batches |
| `dmt` / `dmv` | dimension_types / values | `srec` | source_records |
| `cpt` | counterparties | `rul` / `rrn` | rules / rule_runs |
| `cal` | counterparty_aliases | `msg` / `mex` | match_suggestions / exclusions |
| `cpa` | counterparty_accounts | | |
| `prl` | pairing_rules | | |
| `tty` | transaction_types | | |
| `tpl` | （保留） | | |
| `fee` | fee_rules | `rpt` / `chk` | report_runs / check_runs |
| `aud` | audit_events | `chs` | change_sets |
| `fil` / `att` | files / attachments | `tag` | tags |
| | | `job` | jobs |
| `obx` / `whe` / `whd` | outbox / webhook 端点 / 投递 | `mcp` | mcp_calls |

## 3. 身份与权限

### users
| 列 | 类型 | 约束 / 说明 |
|---|---|---|
| id | text | PK `usr_` |
| email | citext | UNIQUE NOT NULL |
| display_name | text | NOT NULL |
| password_hash | text | argon2id |
| is_active | boolean | DEFAULT true |
| is_superadmin | boolean | 系统级管理（创建账套、用户） |
| totp_secret_enc | bytea | 可选二次验证（加密存储） |
| last_login_at | timestamptz | |

### sessions
`id, user_id → users, token_hash char(64) UNIQUE, csrf_secret, ip inet, user_agent, created_at, expires_at, revoked_at`。

### book_members
`book_id, user_id, role`，PK(book_id, user_id)。`role ∈ {owner, admin, accountant, viewer}`。

### api_tokens
| 列 | 类型 | 说明 |
|---|---|---|
| id | text | `tok_` |
| book_id | text | 令牌绑定单一账套（连接级上下文绑定） |
| user_id | text | 以该用户身份执行；有效权限 = 用户角色 ∩ 令牌作用域 |
| name | text | |
| token_hash | char(64) | sha256，UNIQUE；明文只在创建时返回一次 |
| token_prefix | text | 明文前 12 位，用于识别（如 `bk_pat_3fA9…`） |
| scopes | text[] | 见 08 号文档；默认 `{ledger:read}` |
| preset | text | `reader` / `bookkeeper` / `admin` / `custom`，决定 MCP 暴露的工具集 |
| mcp_enabled | boolean | 是否允许用于 MCP |
| ip_allowlist | cidr[] | 可选 |
| rate_limit_per_min | integer | 默认 120 |
| expires_at / last_used_at / last_used_ip / revoked_at | | |

### oauth_clients / oauth_grants
- `oauth_clients(id, client_id UNIQUE, client_name, redirect_uris text[], token_endpoint_auth_method, created_via ∈ {dcr, manual}, created_at)`；
- `oauth_grants(id, client_id, user_id, book_id, scopes text[], preset, code_hash, code_challenge, code_challenge_method, code_expires_at, access_token_hash, access_expires_at, refresh_token_hash, refresh_expires_at, resource text, revoked_at, created_at)`。

## 4. 账套与商品

### books
| 列 | 类型 | 说明 |
|---|---|---|
| id | text | `bk_` |
| name | text | |
| base_commodity | text | FK commodities.code，创建后不可改 |
| timezone | text | 默认 `Asia/Shanghai`；业务日期 = 发生时间在此时区的日期 |
| rounding_mode | text | `half_up`（默认）/ `half_even` |
| fiscal_year_start_month | smallint | 默认 1 |
| journal_codes | text[] | 凭证字，默认 `{记}` |
| rounding_tolerance_per_line | integer | 本位币尾差容差（每行最小单位数），默认 1 |
| fx_lookback_days | smallint | 汇率向前回溯天数，默认 7 |
| settings | jsonb | 其他账套级设置（如汇兑损益实现方式 `fx_realization: immediate|defer`） |
| status | text | `active` / `archived` |

### commodities（全局）
`code text PK`（`CNY`、`USD`、`GBP`、`HKD`、`UCR`…）、`name`、`kind ∈ {fiat, credit, other}`、`scale smallint CHECK 0..8`、`symbol`、`is_active`。
上游额度定义为 `kind=credit` 的商品（如 `UCR`，scale 4），其与本位币的名义换算通过价格规则表达。

### commodity_price_rules
| 列 | 说明 |
|---|---|
| id `cpr_`, book_id | |
| commodity, quote_commodity | 如 `UCR → CNY` |
| rate | numeric(28,12) |
| purpose | `nominal_valuation`（名义估值，用于报表折算额度余额）/ `conversion`（固定换算约定） |
| valid_from, valid_to | 生效区间；EXCLUDE 约束保证同一 (book, commodity, quote, purpose) 区间不重叠 |
| note | |

### fx_rates（全局）
`id fxr_, base, quote, rate_date date, rate numeric(28,12) CHECK > 0, rate_type ∈ {reference, actual, derived, manual}, source text, fetched_at, raw jsonb`；UNIQUE(base, quote, rate_date, rate_type, source)。

## 5. 科目与维度

### accounts
| 列 | 类型 | 说明 |
|---|---|---|
| id | text | `acc_` |
| book_id | text | |
| code | varchar(32) | UNIQUE(book_id, code)；子科目编码必须以父科目编码为前缀 |
| name | text | |
| parent_id | text | 自引用 |
| level | smallint | 由触发器维护 |
| is_group | boolean | 分组科目不可记账 |
| classification | text | `asset` / `liability` / `equity` / `revenue` / `expense` |
| normal_side | text | `debit` / `credit`，默认由分类推导，备抵科目反向 |
| role | text | 见 5.1；可空（普通明细科目） |
| is_default_for_role | boolean | 部分唯一索引 UNIQUE(book_id, role) WHERE is_default_for_role |
| allowed_commodities | text[] | NULL = 任意 |
| open_date / close_date | date | 记账日期须在区间内 |
| balance_rule | text | `any` / `normal_side_only`（余额不得出现反向） |
| manual_entry_allowed | boolean | 手工凭证是否可用此科目 |
| required_dimensions / forbidden_dimensions | text[] | 维度类型代码 |
| standard_code | text | 国标科目代码映射 |
| is_system | boolean | 系统科目不可删除、不可改角色 |
| is_active | boolean | |
| description | text | |

#### 5.1 科目角色（`role`）

| 角色 | 含义 | 角色 | 含义 |
|---|---|---|---|
| `funds` | 资金账户（现金、银行、钱包、平台余额统称） | `revenue_operating` | 主营业务收入 |
| `receivable` | 应收账款 | `revenue_other` | 其他业务收入 |
| `other_receivable` | 其他应收款 | `non_operating_income` | 营业外收入 |
| `prepaid` | 预付账款 | `cost_operating` | 主营业务成本 |
| `payable` | 应付账款 | `expense_selling` | 销售费用 |
| `advance_received` | 预收账款 | `expense_admin` | 管理费用 |
| `other_payable` | 其他应付款 | `expense_finance_fee` | 财务费用-手续费 |
| `equity_capital` | 实收资本 | `fx_gain_loss` | 汇兑损益（系统） |
| `current_year_profit` | 本年利润（系统） | `interest` | 利息收支 |
| `retained_earnings` | 利润分配（系统） | `rounding` | 尾差（系统） |
| `trading` | 货币兑换（系统） | `non_operating_expense` | 营业外支出 |
| `opening_balance` | 期初余额调整（系统） | `income_tax` | 所得税费用 |
| `suspense` | 待核对款项（系统） | | |

报表分类由 `classification` + `role` 决定，不依赖编码或名称。`funds` 角色的科目即现金流量表中的“现金”。

#### 5.2 默认科目表

默认科目表、收支分类与命名规则见 **14 号文档 §3–§4**（《小企业会计准则》编码）。要点：
- 资金统一记入 `1012.01 资金账户`（多币种，不区分微信、支付宝、银行卡与平台余额）；
- 直接用于提供 API 服务的支出计入 `5401 主营业务成本` 下的上游额度、账号、AI 服务订阅、服务器与网络；
- 系统科目：`1999 待核对款项`、`3103 本年利润`、`3104 利润分配`、`3901 货币兑换`、`3902 期初余额调整`、`5603.02 汇兑损益`、`5603.09 尾差`。

### dimension_types
`id dmt_, book_id, code, name, is_hierarchical, is_active`；UNIQUE(book_id, code)。默认只有 `channel`（渠道，值见 14 号文档 §6）；需要时可增加其他维度。

### dimension_values
`id dmv_, book_id, type_id, code, name, parent_id, counterparty_id（可选关联）, is_active, metadata jsonb`；UNIQUE(type_id, code)。

## 6. 往来方

### counterparties
| 列 | 说明 |
|---|---|
| id `cpt_`, book_id, name | UNIQUE(book_id, name) |
| category | 往来方分类：`upstream_site` / `ai_vendor` / `cloud_vendor` / `marketplace` / `payment_provider` / `marketing_vendor` / `business_service` / `customer` / `other`（见 14 号文档 §7） |
| roles | text[]：`customer` / `supplier`（同一往来方可兼有） |
| domains | text[]：站点域名（用于识别与规则） |
| default_transaction_type_id | 默认交易类型 |
| default_dimensions | jsonb `{type_code: value_id}` |
| notes, metadata, is_active | |

### counterparty_aliases
`id cal_, book_id, counterparty_id, pattern, match_type ∈ {exact, contains, regex, domain}, priority`；用于把来源记录中的对方文本解析为往来方。

### counterparty_accounts
`id cpa_, book_id, counterparty_id, label（如“账号A”）, identifier（登录名，敏感字段，MCP 默认脱敏）, is_active, metadata`。用于区分同一站点的多个账号，匹配兑换日志。

## 7. 交易类型、模板与手续费

### transaction_types
`id tty_, book_id, code, name, category ∈ {income, expense, transfer, adjustment, other}, description, is_system, is_active`；UNIQUE(book_id, code)。内置类型见 05 号文档。

### fee_rules
| 列 | 说明 |
|---|---|
| id `fee_`, book_id, code, version | UNIQUE(book_id, code, version)；同代码再次提交 = 新版本，上一版本自动设 `valid_to` |
| name, status | `active` / `retired` |
| rate | numeric(12,8)，0 ≤ rate < 1 |
| fixed_minor, min_minor, max_minor | bigint；最小单位；CHECK min ≤ max |
| commodity | 固定额与上下限的币种（设置上述任一项时必填）；设置后只匹配该币种交易 |
| transaction_types, channel_ids, counterparty_ids | text[]，空 = 不限 |
| priority | smallint；同时命中时优先级高者胜，其次范围更具体者；仍并列报 `FEE_RULE_AMBIGUOUS` |
| valid_from, valid_to | 按交易业务日期生效 |
| is_estimate | 命中后交易标记 `is_estimate` |
| note, created_by, created_at | |

CHECK：rate 与 fixed_minor 至少一项。扣法（从毛额扣除 / 另付）由交易类型决定，规则不存储。业务类型由代码定义（05 号文档 §2），不设 posting_templates 表。

## 8. 交易（业务层）

### transactions
| 列 | 类型 | 说明 |
|---|---|---|
| id | text | `txn_` |
| book_id | text | |
| number | text | `T{YYYY}-{6 位序号}`，记账时分配、之后不变，UNIQUE(book_id, number) |
| transaction_type_id | text | |
| template_id | text | 保留，恒为空 |
| status | text | `posted`（已入账）/ `reversed`（已删除） |
| effective_date | date | 业务日期 |
| occurred_at | timestamptz | 原始发生时间 |
| occurred_offset_minutes | smallint | 原始时区偏移（保留证据原貌） |
| date_precision | text | `timestamp` / `day` / `month` |
| description | text | |
| counterparty_id / counterparty_account_id | text | |
| inputs | jsonb | 业务类型：解析后的输入（ID 与最小单位）；手工类型：`lines`、`allow_conversion`；均含 `journal_code` |
| computed | jsonb | 最近一次构建的结果：业务金额（gross / fee / net / face / total…）、`headline`（列表金额）、`fee_rule`、`fee_expected`、警告、汇率、`entry_number` |
| default_dimensions | jsonb | `{channel: value_id}`；表达式索引 (book_id, default_dimensions->>'channel') 支持按渠道检索 |
| external_ref | text | 外部唯一引用；部分唯一 UNIQUE(book_id, external_ref) WHERE external_ref IS NOT NULL |
| order_no | text | 订单号，索引 |
| is_estimate | boolean | 含兜底估算（如手续费按默认费率） |
| provenance | jsonb | 字段来源与锁定：`{field: {by, ref, at, locked}}` |
| created_channel | text | `ui` / `api` / `mcp` / `import` / `system` / `migration` |
| created_by_user_id / created_token_id / mcp_client | | |
| created_change_set_id | text | |
| posted_entry_id | text | 当前分录（修改后指向重记的新分录；删除后仍指向被冲销的那张，恢复时据此重记） |
| posted_at / posted_by | | 当前分录的入账时间与操作者 |
| reversed_at / reverse_reason | | 删除时间与原因（可空） |
| notes | text | |
| metadata | jsonb | 自由元数据（不影响分录；控制字段与自由元数据分离） |

索引：(book_id, effective_date)、(book_id, status)、(book_id, counterparty_id, effective_date)、(book_id, default_dimensions->>'channel')、部分唯一 (book_id, external_ref)。

### transaction_sources
`transaction_id, source_record_id, role ∈ {primary, evidence, settlement, counterpart}, allocated_amount bigint NULL, created_at, created_by`；PK(transaction_id, source_record_id)。一个来源记录可分配给多笔交易（1:N），多条来源记录可支撑一笔交易（N:1）。

### transaction_links
`id tln_, book_id, from_transaction_id, to_transaction_id, kind ∈ {refund_of, related}, note, created_at`；UNIQUE(from, to, kind)，CHECK from ≠ to。退款记账时写 `refund_of`；交易详情双向展示。

## 9. 总账（会计层）

### ledger_heads（每账套一行）
`book_id PK, last_seq bigint, last_entry_hash bytea, updated_at`。写分录时 `FOR UPDATE` 锁定。审计链头见 §15 `audit_heads`。

### sequences
`book_id, scope, period, next_value`；PK(book_id, scope, period)。`scope` 为凭证字（如 `记`）或 `TXN`；`period` 为 `YYYYMM`（凭证）或 `YYYY`（交易号）。

### journal_entries
| 列 | 类型 | 说明 |
|---|---|---|
| id | text | `jen_` |
| book_id | text | |
| seq | bigint | 账套内连续递增，UNIQUE(book_id, seq)；用于增量同步与哈希链 |
| transaction_id | text | NOT NULL |
| kind | text | `posting` / `reversal` / `repost_reversal` / `repost` / `adjustment` |
| journal_code | text | 凭证字 |
| number | text | `{凭证字}-{YYYYMM}-{4 位序号}`，UNIQUE(book_id, number) |
| effective_date | date | |
| recorded_at | timestamptz | 触发器强制 `now()`，不可由客户端指定 |
| template_id | text | 生成时使用的模板版本 |
| fee_rule_ids | text[] | 生成时使用的手续费规则版本 |
| engine_version | text | 记账引擎版本 |
| description | text | |
| reverses_entry_id | text | 删除冲销 / 修改冲销所针对的分录 |
| reversed_by_entry_id | text | **唯一可更新列**，只能从 NULL 设置一次 |
| attachment_count | smallint | 附件张数（凭证习惯） |
| created_by_user_id / created_token_id / channel / change_set_id | | |
| prev_hash / hash | bytea | 哈希链，见 05 号文档 §9 |

### journal_lines
| 列 | 类型 | 说明 |
|---|---|---|
| id | text | `jln_` |
| book_id, entry_id | text | |
| line_no | smallint | UNIQUE(entry_id, line_no) |
| account_id | text | |
| commodity | text | |
| amount | bigint | 原币，借正贷负 |
| base_amount | bigint | 本位币，入账时冻结；商品为本位币时必须等于 amount |
| fx_rate | numeric(28,12) | 商品 → 本位币；本位币行为 NULL |
| fx_rate_id | text | 引用 fx_rates（使用汇率表时） |
| fx_source | text | `table` / `actual` / `price_rule` / `manual` / `derived` |
| quantity / quantity_unit | numeric(28,8) / text | 统计数量（如额度单位数），不参与平衡 |
| counterparty_id / counterparty_account_id | text | |
| memo | text | |
| line_role | text | 模板行角色（`gross`、`fee`、`net`、`cost`、`in`、`out`、`trading`、`fx_realization`、`rounding`…），用于分析与约束 |
| effective_date | date | 冗余，便于索引 |
| account_seq | bigint | 该科目 × 商品的记录序号 |
| balance_after / base_balance_after | bigint | 记录顺序下的入账后余额 |

分录行写入后完全不可修改。CHECK：`amount <> 0 OR base_amount <> 0`。
索引：(book_id, account_id, effective_date)、(book_id, effective_date)、(entry_id)、(book_id, counterparty_id, effective_date)、(account_id, commodity, account_seq)。

### journal_line_dimensions
`line_id, dimension_type_id, dimension_value_id, book_id`；PK(line_id, dimension_type_id)；索引 (dimension_value_id)。

### account_balances
`book_id, account_id, commodity, balance, base_balance, debit_total, credit_total, base_debit_total, base_credit_total, line_count, last_seq, updated_at`；PK(account_id, commodity)。写分录时加锁更新；`balance_rule = normal_side_only` 在此校验。

### daily_balances
`book_id, account_id, commodity, date, debit, credit, base_debit, base_credit, line_count`；PK(account_id, commodity, date)。**只存当日发生额**（不存期初 / 期末），写分录时在同一事务中累加；某日余额 = 截至该日全部发生额之和。回溯写入只影响当天一行，不需要级联更新后续日期。

## 10. 期间与锁账（已去掉）

`fiscal_periods`、`lock_settings`、`lock_exceptions`、`period_checkpoints` 已由迁移 0011 删除；凭证号按业务日期所在月编号（`sequences`）。

## 11. 导入

### sources
| 列 | 说明 |
|---|---|
| id `src_`, book_id, code, name | |
| kind | `wallet_bill` / `bank_statement` / `payment_processor` / `card_shop_orders` / `upstream_usage_log` / `generic_tabular` / `manual_list` |
| parser_code / parser_version_pinned | 解析器及可选固定版本 |
| config | jsonb：列映射、时区、过滤、店铺 / 站点标识 |
| account_id | 该来源代表的资金科目（订单列表类可空） |
| counterparty_id / default_transaction_type_id | |
| dedup_strategy | jsonb：`{"mode": "external_id"|"fingerprint"|"columns", "columns": [...]}` |
| authoritative | boolean：权威来源（同一权威来源的两条记录不能互相匹配为同一笔） |
| watermark | jsonb：`{last_occurred_at, last_external_id, count_at_last_ts}` |
| is_active | |

### import_batches
`id imb_, book_id, source_id, file_id, parser_code, parser_version, status ∈ {uploaded, parsing, parsed, failed, committed, partially_committed, reverted}, period_from, period_to, record_count, stats jsonb, safety_checks jsonb, errors jsonb, created_by, token_id, channel, commit_change_set_id, revert_change_set_id, committed_at, reverted_at`。

### source_records
| 列 | 说明 |
|---|---|
| id `srec_`, book_id, source_id, batch_id, row_no | |
| external_id | 来源唯一号；部分唯一 UNIQUE(book_id, source_id, external_id) WHERE external_id IS NOT NULL |
| fingerprint | char(64)，稳定指纹（见 06 号文档）；UNIQUE(book_id, source_id, fingerprint) |
| occurred_at, occurred_offset_minutes, effective_date | |
| direction | `in` / `out` / `neutral` |
| amount, commodity | 正数金额 |
| fee_amount | 来源给出的手续费（如有） |
| balance_after | 来源给出的余额（如有，用于生成断言） |
| counterparty_text, description, order_no, reference, status_text | |
| extracted | jsonb：解析出的结构化字段（面值、站点域名、账号标识、商品名…） |
| raw | jsonb：原始行 |
| status | `new`（缺字段，待处理） / `classified`（已分类，可提交） / `matched` / `booked` / `ignored` / `duplicate` |
| status_reason | |
| counterparty_id | 解析出的往来方 |
| proposed | jsonb：规则产出的拟分类结果（交易类型、维度、科目参数）及来源 |
| duplicate_of_id | |
| provenance | jsonb |

索引：(book_id, status)、(book_id, order_no)、(book_id, effective_date)、(book_id, source_id, occurred_at)。

## 12. 规则与匹配

### rules
`id rul_, book_id, name, stage ∈ {normalize, classify, enrich}, priority integer, specificity integer（保存时计算）, conditions jsonb, actions jsonb, stop_processing boolean, applies_to jsonb, enabled boolean, hit_count bigint, last_hit_at, created_by, version`。

### rule_runs
`id rrn_, book_id, rule_id, rule_version, target_type, target_id, mode ∈ {auto, apply, test}, changes jsonb, change_set_id, created_at`。

### match_suggestions
`id msg_, book_id, run_id, kind ∈ {duplicate, record_txn, record_record, line_line}, left_type, left_ids text[], right_type, right_ids text[], score numeric(5,4), components jsonb, method, status ∈ {pending, accepted, auto_accepted, rejected, expired, superseded}, decided_by, decided_at, decision_note, created_at`。

### match_exclusions
`id mex_, book_id, kind, a_type, a_id, b_type, b_id, reason, created_by, created_at`；UNIQUE(book_id, kind, a_id, b_id)（a_id < b_id 规范化）。

### pairing_rules
`id prl_, book_id, code, name, definition jsonb（左右来源、分组键、时间窗、罚分、数量展开、自动接受阈值、接受动作，见 06 号文档 §7.2）, enabled, version`；UNIQUE(book_id, code)。

## 13. 对账与未清项（已去掉）

`balance_assertions`、`reconciliations`、`line_matches` 已由迁移 0011 删除。

## 14. 报表与检查

- `report_runs(id rpt_, book_id, report_code, params jsonb, as_known_at, fingerprint char(64), row_count, result jsonb NULL, created_by, created_at)`；
- `check_runs(id chk_, book_id, trigger ∈ {scheduled, manual, post_migration}, started_at, finished_at, status, summary jsonb)`；
- `check_results(id, run_id, check_code, severity ∈ {error, warning, info}, status ∈ {pass, fail, skip}, count, details jsonb)`。

## 15. 审计、变更集、幂等

### audit_heads
`scope text PK（账套 ID，或 'global' 表示登录、建用户等非账套事件）, last_seq bigint, last_hash bytea, updated_at`。写审计事件时 `FOR UPDATE` 锁定，保证每条链的 seq 连续。

### audit_events
| 列 | 说明 |
|---|---|
| id `aud_`, scope, book_id, seq | UNIQUE(scope, seq)；scope 为所属哈希链 |
| occurred_at | |
| actor_type | `user` / `token` / `system` / `migration` |
| user_id, token_id, mcp_client | |
| channel | `ui` / `api` / `mcp` / `import` / `worker` / `cli` / `migration` |
| action | 如 `transaction.create`、`transaction.update`、`transaction.delete`、`rule.update`、`auth.login_failed` |
| entity_type, entity_id | |
| request_id, idempotency_key, change_set_id | |
| before, after, diff | jsonb（敏感字段脱敏） |
| ip, user_agent | |
| prev_hash, hash | 审计哈希链 |

### change_sets
`id chs_, book_id, operation, summary, actor 字段, channel, mcp_client, entity_counts jsonb, status ∈ {applied, reverted, partially_reverted}, reverts_change_set_id, reverted_by_change_set_id, created_at`。

### idempotency_keys
`book_id, actor_key, key varchar(128), operation, request_hash, status ∈ {in_progress, completed}, response_status, response_body jsonb, created_at, expires_at（默认 30 天）`；PK(book_id, actor_key, key)。

### mcp_calls
`id mcp_, book_id, token_id, user_id, client_name, client_version, session_id, tool, args_redacted jsonb, args_hash, ok boolean, result_code, duration_ms, change_set_id, request_id, created_at`。

## 16. 附件、标签、任务、Webhook、迁移

- `files(id fil_, book_id, sha256, size_bytes, mime_type, original_name, storage_key, uploaded_by, token_id, created_at)`，UNIQUE(book_id, sha256)；
- `attachments(id att_, book_id, file_id, entity_type, entity_id, role ∈ {receipt, invoice, statement, screenshot, order_export, contract, other}, note, created_by, created_at, detached_at)`；
- `tags(id tag_, book_id, name)`（账套内唯一，≤ 30 字符），`transaction_tags(transaction_id, tag_id, created_by)`：标签只标注交易、不影响分录，随时可改（M6 实现；未做颜色与非交易实体标签）；
- `jobs`、`job_schedules`（见 03 号文档 §6；`job_schedules` 的 UNIQUE(kind, book_id) 使用 NULLS NOT DISTINCT）；`worker_heartbeats(worker_id PK, hostname, version, started_at, beat_at)`；
- `outbox_events(id obx_, book_id, event_type, entity_type, entity_id, payload, change_set_id, created_at, published_at)`；
- `webhook_endpoints(id whe_, book_id, url, secret_enc, event_types text[], is_active, created_by)`；`webhook_deliveries(id whd_, endpoint_id, event_id, attempt, status, response_code, response_snippet, next_retry_at, created_at)`；
- `legacy_map(legacy_table, legacy_id, entity_type, entity_id, book_id, note)`，PK(legacy_table, legacy_id, entity_type)；`legacy_archive(id, legacy_table, legacy_id, payload jsonb)`。

## 17. 数据库层不变量（`db/triggers.sql`）

| 编号 | 触发器 / 约束 | 规则 |
|---|---|---|
| DB-01 | `journal_balance_check`（CONSTRAINT TRIGGER，DEFERRABLE INITIALLY DEFERRED，AFTER INSERT ON journal_lines） | 提交时校验所属分录：每个商品 Σamount = 0，且 Σbase_amount = 0；行数 ≥ 2 |
| DB-02 | `journal_entries_immutable`（BEFORE UPDATE/DELETE） | 拒绝删除；更新只允许 `reversed_by_entry_id` 从 NULL 变为非 NULL |
| DB-03 | `journal_lines_immutable`（BEFORE UPDATE/DELETE） | 拒绝任何修改与删除（迁移 0011 起） |
| DB-04 | `journal_entries_insert`（BEFORE INSERT） | `NEW.recorded_at := now()`（锁账检查已随 0011 去掉） |
| DB-06 | `journal_lines_account_check`（BEFORE INSERT） | 科目属同一账套、非分组、启用、商品允许、日期在开户 / 销户区间内 |
| DB-07 | `journal_lines_base_commodity`（BEFORE INSERT） | 商品为本位币时 `base_amount = amount` 且 `fx_rate IS NULL` |
| DB-09 | `audit_events_immutable` | 拒绝 UPDATE / DELETE |
| DB-10 | `accounts_code_prefix`（BEFORE INSERT/UPDATE） | 子科目编码以父编码为前缀；分类与父科目一致；维护 `level` |
| DB-11 | `accounts_in_use_guard` | 已有分录的科目不可改分类、商品限制只能放宽、不可删除 |
| DB-12 | 各 EXCLUDE 约束 | 模板版本、手续费规则版本、价格规则的有效区间不重叠 |
| DB-13 | `journal_lines_base_only`（CHECK） | `amount = 0` 的“仅本位币金额行”只允许尾差、汇兑损益等系统行角色，且商品不得为本位币 |

数据库账号：`bk_owner`（DDL，仅迁移使用）与 `bk_app`（应用）。对 `bk_app`：`REVOKE DELETE, TRUNCATE ON journal_entries, journal_lines, audit_events`；`journal_entries` 仅授予列级 `UPDATE (reversed_by_entry_id)`；`journal_lines` 不授予 UPDATE。
