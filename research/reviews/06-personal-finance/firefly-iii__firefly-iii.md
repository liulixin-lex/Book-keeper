# firefly-iii/firefly-iii

- 分类：06 个人/家庭财务（复式）
- 语言 / 许可证 / 最近提交：PHP (Laravel) / AGPL-3.0 / 2026-10-18（2.5 万星，非常活跃）
- 审查范围：`app/Models/{TransactionGroup,TransactionJournal,Transaction,Account,AccountType,Rule*,Webhook*,AuditLogEntry,Recurrence*,CurrencyExchangeRate}.php`、`app/TransactionRules/{Engine,Actions,Expressions}`、`config/search.php`、`app/Api/V1`

## 定位

最流行的自托管个人财务系统：复式记账内核 + 规则引擎 + 预算/账单/存钱罐 + 完整 REST API + Webhook；配套独立的数据导入器。

## 数据模型

- **TransactionGroup（拆分交易组）→ TransactionJournal（日记账：类型、日期 + 时区、币种、描述、关联账单、完成标记、排序）→ Transaction（分录：每个日记账两行，源账户负、目标账户正）**；
- Transaction 字段：account、amount、**native_amount（主货币金额）**、**foreign_amount + foreign_currency（外币金额）**、native_foreign_amount、**reconciled（已核对）**、identifier；
- 日记账元数据：利息日、记账日（book_date）、处理日、到期日、付款日、发票日、外部 ID、内部参考号、外部 URL、**import_hash_v2（导入去重哈希）**；
- **账户类型**：资产（含默认/共享/储蓄/信用卡子类）、**费用账户（即收款方）**、**收入账户（即付款方）**、负债（债务/贷款/抵押）、现金、期初余额、**核对账户**——交易对手本身就是账户，“去哪家店花了多少”天然可统计；
- 标签、分类、预算、账单（Bill，带金额范围与周期，用于自动匹配）、对象分组、附件、位置、笔记；
- **Rule Group → Rule（strict：全部条件满足 / 非 strict：任一满足；stop_processing）→ RuleTrigger（约 150 个搜索操作符及别名：描述/备注/账户/金额/日期/标签/分类/预算/外部 ID/附件…，可否定）→ RuleAction（约 30 种：设分类/预算/标签、改描述/备注、设源/目标账户、转换交易类型、关联账单、更新存钱罐、设金额、删除…；**动作值支持表达式语言**）**；规则可在新建/更新时自动触发，也可对历史交易批量执行；
- **Webhook**：触发（交易/预算/预算限额的增改删、ANY）× 响应内容（交易、账户、无）× 投递（消息、尝试、响应记录）；
- **AuditLogEntry**：审计变更；Recurrence：定期交易。

## 记账逻辑与算法

- 一切资金流动都是 源账户 → 目标账户 的日记账；多分录拆分通过同组多个日记账表达；
- 多币种：交易币种 + 可选外币金额；“主货币”折算金额（native）随主货币设置维护，用于汇总；
- **核对（reconcile）**：对资产账户选择期间与对账单期末余额，勾选交易标记 reconciled，差额生成“核对”类型交易记入核对账户；
- 导入去重：根据交易内容计算 import_hash_v2，API 写入可设 `error_if_duplicate_hash=true` 让重复直接报错。

## API 与扩展

- REST API v1（OAuth2 / 个人访问令牌），覆盖全部实体；搜索语法与规则触发器共用一套操作符；Webhook 签名投递。

## 可借鉴

- [FF1] 交易对手作为账户（收款方=费用账户、付款方=收入账户）——对手统计免额外维度。
- [FF2] 拆分交易组（group → journals → postings）。
- [FF3] 多种业务日期（发生日、记账日、到期日、付款日、发票日）作为可选元数据。
- [FF4] **规则引擎**：规则组 + strict/非 strict + 三级 stop_processing + 丰富触发器 + 动作表达式 + 对历史批量执行。
- [FF5] **搜索语法与规则触发器同源**（同一套操作符），学习成本低。
- [FF6] 导入去重哈希 + API 参数“重复即报错”。
- [FF7] 核对产生“核对差额”交易并标记已核对。
- [FF8] Webhook：触发 × 响应 × 投递记录与重试。

## 不采用 / 风险

- 个人理财导向（预算、存钱罐）；双行分录限制了一张凭证多科目的表达（要靠拆分组）。
- AGPL-3.0：只参考设计。

## 对新系统的启示

1. 规则引擎设计：Rule（优先级、启用、strict、stop_processing、适用来源）→ Conditions（字段 × 操作符 × 值，支持否定）→ Actions（设交易类型/科目/维度/标签/备注、套用模板、跳过）；可“试运行”看命中结果，可对历史数据回溯执行（生成冲正+重记）；
2. 查询 DSL 与规则条件共用语法（API `q=` 参数）；
3. 写接口支持 `on_duplicate=error|skip|allow`；
4. Webhook 投递日志与重试。
