# 05 记账引擎：业务类型、手续费、多币种、修改与删除

## 1. 总体流程

```
交易输入 (type + 头字段 + inputs | lines)
   │
   ├─ 1 解析输入：按类型的严格输入模型校验（未知字段拒绝）；科目接受编码 / 名称 / ID，渠道接受代码 / ID，
   │            往来方接受名称 / ID（找不到时返回候选），原交易接受编号 / ID
   ├─ 2 补默认值：科目按角色取账套默认科目；退款从原交易继承渠道、科目与往来方
   ├─ 3 构建行：业务类型由代码定义的构建器生成行（domain/business.py）；手工类型直接使用输入行
   ├─ 4 手续费：按交易类型、渠道、往来方、日期、币种选出唯一规则并计算；有实际值时以实际值为准并比对
   ├─ 5 折算本位币：逐行按汇率折算并舍入；结汇缺参考汇率时按本笔实际兑换汇率折算并警告
   ├─ 6 补齐：跨商品 → 货币兑换腿与汇兑损益；本位币尾差 → 尾差行（容差内）
   ├─ 7 校验：平衡、科目、商品、日期、维度、余额规则、外部单号重复、退款不超过原交易
   └─ 8 输出 Plan（行、业务计算值、警告、所用手续费规则、是否估算）
          └─ 入账：编号 → 哈希链 → 写分录（记录 fee_rule_ids）→ 更新余额 → 审计
             （dry_run：整个过程在事务内执行后回滚，返回与真实写入相同的结果）
```

步骤 3、4、6 是领域层纯函数（`domain/business.py`、`domain/fees.py`、`domain/ledger.py`），输入为不可变快照，便于测试与重放。

## 2. 业务类型由代码定义

不设 JSON 模板引擎。6 种业务类型的分录结构固定、清楚，直接用代码实现并配套单元与属性测试；会随时间变化的只有**手续费规则**，做成可版本化的数据（§5）。这样输入模型、分录规则与错误提示都在一处，外部 AI 可通过 `GET /books/{id}/transaction-types` 取得每种类型的输入 JSON Schema、默认科目和示例请求。

| 要求 | 实现 |
|---|---|
| 输入校验 | 每种类型一个严格的 pydantic 模型；金额只接受字符串小数；错误逐字段返回 `errors[].path`（如 `inputs.channel`），并附 `next_action` 指向类型目录 |
| 存储 | `transactions.inputs` 存解析后的值（科目 / 渠道 / 原交易为 ID，金额为 `{minor, commodity}`）；`default_dimensions.channel` 存渠道，便于检索 |
| 摘要 | 未填写时按 14 号文档 §9.2 自动生成并随编辑更新；用户填写后保留（`provenance.description`），清空即恢复自动 |
| 部分修改 | 修改交易时 `inputs` 只需给出要改的键，值为 `null` 表示删除 |
| 退款 | `original` 指向原交易：继承渠道、科目、往来方；记账时建立 `refund_of` 关联；累计退款不得超过原交易金额（超出返回 `refundable`） |
| 结汇缺汇率 | 换入本位币且当日无参考汇率时，外币行按本笔实际兑换汇率折算，警告 `FX_IMPLIED_RATE`，不产生汇兑损益 |

## 3. 表达式语言

- 解析：Python `ast.parse(mode="eval")`，只允许节点：常量、名称、属性访问（仅限白名单对象）、一元 / 二元算术（`+ - * /`）、比较、`and / or / not`、条件表达式 `a if c else b`、白名单函数调用。禁止下标、推导式、lambda、赋值、`**`。
- 长度 ≤ 2000 字符，节点数 ≤ 500。
- 类型：`Decimal`、`Money`、`date`、`str`、`bool`、`None`。数值字面量按 `Decimal` 解析（`0.03` 精确）。
- `Money` 运算：同商品加减；乘除只能与 `Decimal`；不同商品相加报错 `COMMODITY_MISMATCH`。
- 白名单函数：

| 函数 | 说明 |
|---|---|
| `round(x, scale=None, mode=None)` | 按商品精度或指定精度舍入 |
| `pct(x, rate)` | `x × rate`，不舍入 |
| `min / max / abs` | |
| `coalesce(a, b, …)` | 第一个非空值 |
| `zero(x)` | 与 x 同商品的 0 |
| `money(text, commodity)` | 构造金额 |
| `convert(x, commodity, rate=None)` | 显式换算（rate 缺省时按汇率策略取值） |
| `units(x)` | 金额的 Decimal 数值 |
| `days_between(d1, d2)`、`date_of(dt)` | 日期 |
| `concat(...)`、`lower`、`upper`、`regex_extract(text, pattern, group)` | 字符串（正则有长度与超时保护） |
| `dim_name(v)`、`cp_name(v)` | 引用对象名称 |

该求值器用于导入规则引擎的条件与动作（M4）；记账不依赖表达式。

## 4. 内置交易类型

交易类型的代码、名称、说明与默认摘要模板以 **14 号文档 §5、§9** 为准。本节给出输入与分录结构；完整输入字段以 `GET transaction-types` 返回的 JSON Schema 为准。

| 代码 | 名称 | 场景 | 主要输入 | 分录 |
|---|---|---|---|---|
| `sale` | 销售收入 | S1、S3 | gross、fee?（实际手续费）、channel、settle_account?、revenue_account? | 借 资金账户（净额）/ 借 手续费 / 贷 API 额度销售（毛额） |
| `sale_refund` | 销售退款 | S8 | original?（原销售）、amount、fee_refunded?、channel? | 借 收入 / 贷 手续费（退回部分）/ 贷 资金账户 |
| `credit_purchase` | 额度采购 | S4、S5 | 头字段 counterparty（站点，必填）；face?、total?（至少一项）、credit_quantity?、channel、counterparty_account?、pay_account?、cost_account? | 借 上游额度（面值，带额度数量）/ 借 手续费 / 贷 资金账户（实付） |
| `expense` | 费用支出 | S6 | category（支出类科目）、amount、fee?、channel?、pay_account?；头字段 counterparty? | 借 分类科目 / 借 手续费 / 贷 资金账户 |
| `purchase_refund` | 采购退款 | S8 | original? 或 category、amount、pay_account? | 借 资金账户 / 贷 原成本或费用科目 |
| `transfer` | 资金划转 | S2、S7 | from_account、to_account、amount_out、amount_in?、fee? | 借 转入 / 贷 转出；跨商品（结汇、换汇）自动生成兑换腿与汇兑损益；转出、转入可以是同一资金账户的不同币种 |
| `opening_balance` | 期初余额 | 建账 | lines[] | 对方为 期初余额调整 |
| `manual_journal` | 手工凭证 | 调整 | lines[]（科目、方向、金额、维度） | 按输入；科目须允许手工 |

上游额度一律**付款即计入成本**：兑换记录只作为证据与匹配对象，不生成分录。

### 4.1 计算示例

**例 1：销售收入（渠道从毛额扣 3%）**

输入：gross = ¥100.00，channel = 链动。手续费规则：rate 3%（销售类型的手续费从毛额中扣除）。

| 行 | 科目 | 借 | 贷 |
|---|---|---|---|
| 1 net | 1012.01 资金账户 | 97.00 | |
| 2 fee | 5603.01 手续费（渠道 = 链动） | 3.00 | |
| 3 gross | 5001.01 API 额度销售（渠道 = 链动） | | 100.00 |

**例 2：外币销售（实际手续费、尾差）**

输入：gross = £20.00，fee = £0.85（实际值），channel = Stripe。当日参考汇率 GBP→CNY = 9.5127。

| 行 | 科目 | 商品金额 | 本位币 |
|---|---|---|---|
| 1 net | 1012.01 资金账户 | 借 £19.15 | 借 182.17（182.168） |
| 2 fee | 5603.01 手续费 | 借 £0.85 | 借 8.09（8.086） |
| 3 gross | 5001.01 API 额度销售 | 贷 £20.00 | 贷 190.25（190.254） |
| 4 rounding | 5603.09 尾差 | £0.00 | 贷 0.01 |

本位币借方 190.26、贷方 190.25，差额 0.01 ≤ 容差（3 行 × 1 分），生成一条**商品金额为 0、仅本位币金额**的尾差行；超出容差报错 `NOT_BALANCED`。

**例 3：额度采购（手续费在面值上加收）**

输入：face = ¥50.00，credit_quantity = 50 UCR，channel = 链动，counterparty = relay-b.example。手续费规则：rate 3%（采购类型的手续费在面值上另付）。

| 行 | 科目 | 借 | 贷 | 统计数量 |
|---|---|---|---|---|
| 1 cost | 5401.01 上游额度（往来方 = relay-b.example） | 50.00 | | 50 UCR |
| 2 fee | 5603.01 手续费（渠道 = 链动） | 1.50 | | |
| 3 pay | 1012.01 资金账户 | | 51.50 | |

**例 4：只知实付总额（手续费已含在内）**

输入：total = ¥51.50，规则 3% → face = round(51.50 / 1.03) = 50.00，fee = 51.50 − 50.00 = 1.50。若同时输入 face 与 total，以实际差额为准；与规则计算值偏差超过容差时给出警告 `FEE_DEVIATION`。

**例 5：赠送额度**

输入：total = ¥100.00，credit_quantity = 103 UCR（含赠送 3）。分录：借 上游额度 100.00（数量 103 UCR）/ 贷 资金账户 100.00。单位成本 = 0.9709，报表可直接得出。纯赠送且无付款的额度不生成分录，来源记录标记 `ignored`（原因 `gift`），在额度采购分析中单列。

**例 6：结汇（同一资金账户内 GBP → CNY）**

输入：from_account = to_account = 1012.01 资金账户，amount_out = £20.00，amount_in = ¥188.50。当日参考汇率 9.5000。

| 行 | 科目 | 商品金额 | 本位币 | 行角色 |
|---|---|---|---|---|
| 1 | 1012.01 资金账户 | 借 ¥188.50 | 借 188.50 | in |
| 2 | 1012.01 资金账户 | 贷 £20.00 | 贷 190.00 | out |
| 3 | 3901 货币兑换 | 借 £20.00 | 借 190.00 | trading |
| 4 | 3901 货币兑换 | 贷 ¥188.50 | 贷 188.50 | trading |
| 5 | 5603.02 汇兑损益 | £0.00 | 借 1.50 | fx_realization |
| 6 | 3901 货币兑换 | £0.00 | 贷 1.50 | fx_realization |

校验：GBP Σ = −20 + 20 = 0；CNY Σ = 188.50 − 188.50 = 0；本位币 Σ = 188.50 − 190 + 190 − 188.50 + 1.50 − 1.50 = 0。货币兑换科目本位币余额归零，汇兑损失 1.50 已实现。

## 5. 手续费规则

规则只回答“收多少”；“怎么扣”由交易类型决定：`sale` 从毛额中扣除；`credit_purchase` 在面值上另付（只知实付时反推面值）；`expense` 在金额上另付；`transfer` 从转出金额中扣（同币种且给了转入金额时手续费 = 转出 − 转入）；`sale_refund` 为渠道退回的手续费（冲减手续费）。任何类型录入了实际手续费都以实际为准，与规则计算值偏差过大时给出 `FEE_DEVIATION` 警告。

### 5.1 规则字段（`fee_rules`）

| 字段 | 说明 |
|---|---|
| `code` + `version` | 同一代码再次提交即新版本：新版本 `valid_from` 须晚于上一版，上一版自动设 `valid_to = valid_from − 1` |
| `rate` | 比例，0 ≤ rate < 1，如 `0.03` |
| `fixed_minor` | 每笔固定额（最小单位） |
| `min_minor` / `max_minor` | 每笔下限 / 上限 |
| `commodity` | 固定额与上下限的币种；设置后只匹配该币种的交易 |
| `transaction_types` / `channel_ids` / `counterparty_ids` | 适用范围。交易类型可选 sale、credit_purchase、expense、transfer、sale_refund；**交易类型为空的规则只用于 sale 与 credit_purchase**（其他类型须明确列出，避免已有规则突然作用到支出或划转）；渠道、往来方为空表示不限。站点按渠道的费率（如 relay-b.example 经链动 3%、经云猫 0%）就是同时限定往来方与渠道的规则，往来方详情会列出 |
| `priority` | 优先级 |
| `is_estimate` | 按此规则算出的手续费标记为估算，交易 `is_estimate = true`，待实际金额核对 |
| `status` | `active` / `retired`（停用不删除，历史分录仍可追溯到规则 ID） |

### 5.2 选择

1. 候选：`status = active`，`valid_from ≤ 业务日期 ≤ valid_to`，交易类型、渠道、往来方、币种都在范围内。
2. 排序：`priority` 降序 → 范围具体程度（非空范围项个数）降序。
3. 前两名优先级与具体程度相同 → `FEE_RULE_AMBIGUOUS`，绝不猜测。
4. 无候选：手续费为 0（有实际值时用实际值）。
5. `GET fee-rules:evaluate` 用同一逻辑返回命中的规则与金额，供录入前试算。

### 5.3 计算

f = round(B × rate) + fixed，再按下限 / 上限截取。覆盖按比例（3%）、按笔（¥1）与组合（2.9% + $0.30）。只知总额 T 时：B = round((T − fixed) / (1 + rate))，f = T − B（再截取上下限，B 随之调整），保证 B + f = T。

### 5.4 实际值与估算

- 有实际值（`fee`，或采购同时给出 `face` 与 `total`）：采用实际值，同时按规则算出 `fee_expected`；偏差超过 max(1 分, 0.5% × B) 时警告 `FEE_DEVIATION`。
- 无实际值：按规则计算；规则 `is_estimate = true` 时交易标记为估算，可在概览的“待处理”中看到数量，获得实际金额后修改该交易，或修正规则后按新规则重算。
- 所用规则写入 `transactions.computed.fee_rule` 与分录 `fee_rule_ids`（参与哈希）。

## 6. 拆分与尾差

- **拆分**：把金额 A 按比例 p₁…pₖ（Σ = 1）或“固定 + 剩余”分配：先算各份原始值，向下取整到最小单位，剩余的单位按小数部分从大到小依次 +1（并列按声明顺序）。保证 Σ 份额 = A。
- **本位币折算**：`base = round(amount × rate, base_scale, book.rounding_mode)`，逐行计算。
- **尾差行**：Σbase ≠ 0 且 |差额| ≤ `rounding_tolerance_per_line × 行数` → 追加一行：科目 `@rounding`，商品取本笔第一个外币商品，`amount = 0`，`base_amount = −差额`，`line_role = rounding`；超出容差 → `NOT_BALANCED`。

## 7. 多币种与汇率

### 7.1 汇率取值顺序

1. 交易输入中的实际汇率（`fx_source = actual`），或由原币与本位币实际金额推得；
2. 商品价格规则（`purpose = conversion`，如额度单位，`fx_source = price_rule`）；
3. 汇率表：账套配置的来源与类型，业务日期当日；
4. 向前回溯至多 `fx_lookback_days` 天（结果警告 `FX_RATE_STALE`，注明使用日期）；
5. 经中间币种（USD、EUR）推导（`fx_source = derived`，警告）；
6. 仍无 → 错误 `FX_RATE_MISSING`（不静默使用 1 或最近任意值）。

### 7.2 跨商品交易

若分录行涉及多个商品，引擎对每个商品的净额自动生成货币兑换腿（`@trading` 科目），使每个商品 Σamount = 0；本位币差额即兑换损益，按账套设置：
- `realize_immediately`（默认）：同一分录内追加两条仅本位币金额的行，把差额从货币兑换科目转入 `@fx_gain_loss`；
- `defer`：留在货币兑换科目，期末重估时处理。

### 7.3 期末重估与年末结转（已去掉）

2026-10-19 起不再提供（见 17 号文档）：经营统计以交易时的本位币金额为准，外币余额按原币展示。

## 8. 校验与错误码

| 错误码 | 条件 | HTTP |
|---|---|---|
| `INPUT_INVALID` | 输入不符合该类型的输入模型或业务规则（如退款超额） | 422 |
| `COMMODITY_MISMATCH` | 不同商品直接运算 | 422 |
| `FEE_RULE_AMBIGUOUS` | 见 §5.1 | 422 |
| `FX_RATE_MISSING` | 见 §7.1 | 422 |
| `NOT_BALANCED` | 商品或本位币不平衡且超出容差 | 422 |
| `ACCOUNT_NOT_POSTABLE` | 分组、停用、日期越界、商品不允许、不允许手工 | 422 |
| `DIMENSION_REQUIRED` / `DIMENSION_FORBIDDEN` | 科目维度规则 | 422 |
| `BALANCE_RULE_VIOLATION` | 余额出现反向（科目设为仅正常方向） | 422 |
| `DUPLICATE_SUSPECTED` | external_ref 已存在，或指纹 / 模糊匹配命中（可用 `on_duplicate=allow` 越过模糊命中，不能越过 external_ref） | 409 |
| `INVALID_STATE` | 状态不允许该操作（如修改已删除的交易，`next_action` 提示先恢复） | 409 |
| `VERSION_CONFLICT` | 期望版本不符 | 409 |

警告（不阻止）：`FEE_DEVIATION`、`FX_RATE_STALE`、`FX_RATE_DERIVED`、`ESTIMATED_FEE`、`ROUNDING_APPLIED`、`DATE_PRECISION_LOW`、`SIMILAR_TRANSACTION`。

## 9. 编号与哈希链

### 9.1 编号
- 交易号 `T{YYYY}-{000001}`：记账时分配，之后的修改、删除、恢复都不改变；
- 凭证号 `{凭证字}-{YYYYMM}-{0001}`：每张分录（记账、修改冲销与重记、删除冲销、恢复）各分配一个，月份取业务日期所在月；`sequences` 行锁保证连续；失败回滚不留号；检查项 `sequence_gaps` 仍会检测。

### 9.2 分录哈希链
- 规范化内容：`{book_id, seq, id, number, transaction_id, kind, journal_code, effective_date, recorded_at(UTC, 微秒), reverses_entry_id, template_id（保留，恒为空）, fee_rule_ids, lines:[{line_no, account_id, commodity, amount, base_amount, fx_rate(规范化十进制字符串), quantity, quantity_unit, counterparty_id, counterparty_account_id, dimensions(按类型排序的[type, value]), memo, line_role}]}`，键排序、无空白、UTF-8；
- `hash = SHA-256(prev_hash ‖ canonical_bytes)`；创世 `prev_hash = SHA-256("bookkeeper-genesis:" + book_id)`；
- 唯一可变的列 `reversed_by_entry_id` 不参与哈希（分录行完全不可修改）；
- 校验：按 seq 顺序重算，报告第一个不一致的 seq；每日任务执行，失败触发告警与检查失败；
- 每日摘要（最后 seq + hash）写入审计事件并随备份导出，便于离线比对。

审计事件同样形成哈希链（`audit_events.prev_hash/hash`），规范化内容为除 `hash` 外的全部列。

## 10. 交易生命周期

只有两种状态：`posted`（已入账）与 `reversed`（已删除）。交易号始终不变，分录只追加。

```
            create                 delete
 (new) ─────────────▶ posted ─────────────▶ reversed
                       │  ▲                    │
          edit / repost│  └────── restore ─────┘
                       ▼
                     posted（冲销当前分录 + 重记新分录）
```

| 操作 | 前置状态 | 账本中发生什么 |
|---|---|---|
| 记账（create） | — | `posting` 分录 |
| 修改（edit） | posted | 摘要、备注、标签、订单号、外部单号、元数据原地修改，不动账本；日期、往来方、业务输入、分录行、凭证字变化时重建，与当前分录不同才写 `repost_reversal` + `repost`（新分录记在新日期）；`posted_entry_id` 指向新分录 |
| 删除（delete） | posted | `reversal` 分录（逐行反向，日期 = 原分录日期），原分录 `reversed_by_entry_id` 赋值；原因可选 |
| 恢复（restore） | reversed | 以删除前分录的行写一张新的 `posting` 分录（原样复制，不按新规则重算） |
| 按新规则重算（repost） | posted | 见 §11 |
| 撤销变更集（undo） | — | 新记的 → 删除；删除的 → 恢复；修改或重算的 → 头字段、输入、标签改回，分录变了则按当时的分录原样重记 |

修改时 `inputs` 只需给出变化的键（值为 `null` 表示删除该键），手工凭证的 `lines` 整体替换；交易类型不能修改。`expected_version` 可选，给出且不符时返回 `VERSION_CONFLICT`。

## 11. 按新规则重算（手续费规则或汇率修正后）

1. **范围**：`POST transactions:repost`，按交易 ID / 编号、类型（`sale`、`credit_purchase` 等带手续费的类型）、渠道、日期区间选取有效交易，单次最多 2000 笔。
2. **重算**：用当前规则与汇率重新构建；与当前有效分录逐行比较（科目、商品、金额、本位币、行角色、维度、往来方、数量），相同则跳过。实际手续费录入的交易不会因规则变化而改变。
3. **执行**：只有一种方式——在原业务日期写一张 `repost_reversal`（冲回当前有效分录）和一张 `repost`（新行），交易的 `posted_entry_id` 指向新分录，`computed` 更新，记审计（含新旧手续费）。
4. **试算**：加 `?dry_run=true` 返回同样的结果（逐笔旧 / 新手续费与差额、合计）但不落库。

## 12. 期间与锁账（已去掉）

2026-10-19 起没有期间结账、锁账日期、锁账例外与余额检查点，任何业务日期都可写入（见 17 号文档）。凭证号仍按业务日期所在月编号。

## 13. 解释链（explain）

每次构建产出解释链，供 API `GET /transactions/{id}/explain` 与 MCP `explain_posting` 使用：

```jsonc
{
  "type": "sale",
  "inputs": { "gross": "100.00 CNY", "channel": "链动" },
  "fee": { "rule": "liandong@2", "method": "percentage", "rate": "0.03", "base": "¥100.00", "fee": "¥3.00",
           "actual": null, "candidates": [ { "rule": "liandong@1", "matched": false, "reason": "已于 2026-09-30 失效" } ] },
  "fx": [],
  "lines": [ { "line_no": 1, "role": "net", "account": "1012.01 资金账户", "amount": "¥97.00" } ],
  "adjustments": [],
  "checks": [ "balanced", "accounts_postable", "no_duplicate" ],
  "warnings": []
}
```
