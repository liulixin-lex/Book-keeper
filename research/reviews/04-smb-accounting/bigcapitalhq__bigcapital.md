# bigcapitalhq/bigcapital

- 分类：04 中小企业会计软件（QuickBooks/Xero 开源替代）
- 语言 / 许可证 / 最近提交：TypeScript（NestJS + Knex/Objection，多租户 MySQL）+ React / AGPL-3.0 / 2026-10-16
- 审查范围：`packages/server/src/modules/{Accounts,Ledger,ManualJournals,BankRules,BankingMatching,BankingCategorize,BankingTransactionsExclude,TransactionsLocking,AuditLogs,ExchangeRates,FinancialStatements,Import,Export,Branches}`

## 定位

完整的中小企业会计系统：销售/采购单据、费用、手工凭证、银行流水、库存、多币种、多分支，以及全套财务报表；每个租户一个数据库。

## 数据模型

- **科目类型表（常量）**：每种类型定义 `normal`（借/贷）、`rootType`（资产/负债/权益/收入/费用）、`parentType`、是否允许多币种、属于资产负债表还是利润表（`balanceSheet` / `incomeSheet`）——现金、银行、应收、存货、其他流动资产、固定资产、应付、信用卡、税务负债、收入、其他收入、销售成本、费用、其他费用……
- **Account**：编码、名称、类型、父科目、币种、是否预置（predefined）、启用状态；
- **Ledger / JournalEntry**：各类单据由各自的“GL 分录生成器”转为总账分录（account_transactions 表），带 reference_type/reference_id 回指来源单据、contact（往来方）、branch（分支）、币种与汇率；
- **银行流水**：uncategorized_cashflow_transactions（未分类流水）→ 分类为费用/收入/转账，或**匹配**到已有单据，或**排除**；
- **Bank Rules**：条件（字段 amount/description/payee × 比较符 contains/equals/not_contains/大于/小于… × AND/OR）+ 适用方向（存入/支出）+ 动作（指定分类：利息收入/其他收入/存款/费用/提款… 与目标科目）；命中规则的流水标记为“已识别（recognized）”。

## 记账逻辑与算法

- **匹配候选排序**：按“金额差绝对值”升序，其次“日期差”升序；可一笔流水匹配多张单据，金额合计校验（按借贷方向带符号求和、两位小数舍入）；可撤销匹配。
- **交易锁定（Transactions Locking）**：按模块（销售、采购、财务）或全部设置锁定日期；支持**部分解锁**（某日期区间临时允许修改）；各模块 Guard 在写入前检查。
- 多币种：单据记原币 + 汇率，总账记本位币；汇率服务。
- 报表：资产负债表、利润表、现金流量表、试算平衡、总账、序时账、往来余额、AR/AP 账龄、按参考号的交易、按往来方的交易……
- 审计日志模块（订阅领域事件写日志）；导入/导出（含样例数据与字段映射）。

## 可借鉴

- [BG1] 科目类型元数据（正常方向、根类型、报表归属、是否允许多币种）集中定义。
- [BG2] 银行流水三去向：分类（生成新交易）/ 匹配（已有交易）/ 排除；未处理流水队列。
- [BG3] 银行规则：多条件 AND/OR + 方向 + 自动分类动作，命中后标记“已识别”待确认。
- [BG4] 匹配候选按金额差、日期差排序，支持一对多与撤销。
- [BG5] 按模块锁账 + 部分解锁区间（临时开放修改窗口并留痕）。
- [BG6] 总账分录回指来源单据（reference_type/id），“按参考号查交易”报表。
- [BG7] 导入导出带样例数据与映射校验。

## 不采用 / 风险

- AGPL-3.0；
- 多租户每租户一个库对小团队过重；
- 匹配/汇总使用浮点并 `round(…, 2)` —— 新系统必须用整数/Decimal。

## 对新系统的启示

1. 外部流水（含兑换记录、卡网订单、Stripe 结算、微信/支付宝账单）统一进入“待处理流水”队列，三种去向：生成交易 / 匹配已有交易 / 排除（需原因）。
2. 规则引擎：条件树（AND/OR）+ 动作（交易类型、科目、供应商、维度、手续费规则），命中即“建议”，可批量确认。
3. 锁账支持“部分解锁窗口”（时间范围 + 原因 + 自动过期），全部留痕。
4. 科目类型元数据驱动报表与校验。
