# blnkfinance/blnk

- 分类：02 账本引擎 / 金融核心
- 语言 / 许可证 / 最近提交：Go + PostgreSQL + Redis 队列 / Apache-2.0 / 2026-10-05
- 审查范围：`model/{transaction,balance,reconciliation_model}.go`、`reconciliation.go`、`lineage*.go`、`transaction_{dryrun,inflight,refunds,bulk}.go`、`api/`

## 定位

面向金融产品的开源账本：余额（balance）+ 交易（transaction），自带在途交易（inflight）、多源/多目标拆分、对账引擎、资金来源追踪（lineage）、余额监控和 Webhook。

## 数据模型

- **Ledger → Balance**（某身份某币种的余额账户）→ **Transaction**（`source`→`destination`，或 `sources[]/destinations[]` 拆分）。
- 金额：`precise_amount *big.Int`（最小单位整数）+ `precision`（如 100）；同时保留 `amount float64` 兼容字段（这是缺点）。
- Balance 拆成 `balance / credit_balance / debit_balance`，以及 inflight 与 queued 三套，带 `version` 乐观锁。
- **Identity**：交易对手/客户身份，支持敏感字段令牌化。
- Transaction 有 `reference`（唯一外部号）、`parent_transaction`（拆分/退款的父交易）、`effective_date`（生效日期，可回填）、`scheduled_for`（定时）、`hash`（内容哈希）、`meta_data`。

## 记账逻辑与算法

- **拆分分配（Distribution）**：每个目标可写百分比（`10%`）、固定金额（`100`）或 `left`（剩余全部）；先扣固定额，再按百分比，最后剩余，用 decimal 计算并处理尾差——正好对应“毛收入 = 净到账 + 手续费(3%)”这种拆分。
- **Inflight（在途）**：先挂 inflight 余额，再 commit（可部分）或 void，支持到期自动作废。
- **Dry-run**：交易和批量交易都有预演接口，返回将产生的余额变化而不落库——外部 AI 写入前非常有用。
- **退款**：基于原交易生成反向交易，支持批量与选项（部分退款）。
- **批量**：`atomic` 标志决定整批成功/失败。
- **透支**：默认不允许，`allow_overdraft` / `overdraft_limit` 显式放开。
- 高并发下用队列 + 合并（coalescing）+ 余额版本号保证一致。

## 追溯与审计

- **资金溯源（Fund Lineage）**：开启 `track_fund_lineage` 的余额会为每个资金提供方维护“影子余额”，出账时按 FIFO / LIFO / 按比例分配到来源，能回答“这笔支出花的是哪一笔入金”。对“上游额度是从哪个渠道买的、对应哪张订单”有直接参考价值。
- 交易哈希、父子交易关联、元数据。

## 导入、分类与对账

- **对账引擎**：上传外部流水（CSV/JSON）或即时对账；策略 `one_to_one` / `one_to_many` / `many_to_one`（如一笔银行入账对应多笔内部交易）；**匹配规则**由多个条件组成（字段 amount/date/description/reference/currency，操作符 equals/contains/regex，`allowable_drift` 容差：金额百分比、日期秒数）；规则之间是“任一规则全部条件满足即匹配”。
- 支持 dry-run 对账、断点续跑（记录最后处理的外部交易 ID）、匹配后回写元数据、统计匹配/未匹配数量。
- 缺点：匹配是贪心的，没有“全局最优”分配（多候选时取第一个满足的）。

## API 与扩展

- REST：ledgers/balances/transactions/identities/reconciliation/matching-rules/hooks/api-keys/search（Typesense 搜索索引）。
- API Key 带权限范围；Webhook 推送交易事件；余额监控（字段+操作符+阈值触发回调）。

## 可借鉴

- [B1] 百分比/固定/剩余三种拆分 + 尾差处理 —— 手续费、分账规则的通用表达。
- [B2] 交易与批量交易的 dry-run 预演 —— 外部 AI/MCP 写入前预检。
- [B3] 对账规则 = 多条件 + 容差（金额 %、时间秒）+ 1:1 / 1:N / N:1 策略 + 断点续跑 + dry-run。
- [B4] 资金溯源（FIFO/LIFO/按比例）—— 追踪上游额度与购买订单、渠道的对应关系。
- [B5] 在途余额（inflight）与部分提交。
- [B6] 余额监控阈值 + Webhook —— 例如上游站余额低于阈值告警。
- [B7] parent_transaction 关联拆分/退款；effective_date 回填。

## 不采用 / 风险

- 金额同时存 float64 —— 新系统只用整数/Decimal 字符串。
- 贪心匹配，多候选时不保证最优；需要像“全局最小时间差”的分配算法（我们已在实际对账中用过）。
- Redis 队列 + Typesense 搜索对小系统偏重。

## 对新系统的启示

1. 过账模板支持“百分比/固定/剩余”分配规则，统一计算手续费并记录尾差。
2. 所有写接口提供 `dry_run=true`，返回将生成的分录、余额变化与校验结果。
3. 对账模块：外部流水导入 → 规则（多条件+容差）→ 候选 → 全局最优分配（如匈牙利算法/最小时间差）→ 人工确认 → 生成核销关系；支持 1:1、1:N、N:1。
4. 可选的“来源追踪”：上游站余额按购买批次（订单）FIFO 消耗，便于成本与渠道归属。
5. 余额阈值告警（上游站余额、钱包余额）。
