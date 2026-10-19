# ekmungai/python-accounting

- 分类：03 复式记账库（SQLAlchemy，面向 IFRS/GAAP 报表）
- 语言 / 许可证 / 最近提交：Python / MIT / 2026-10-16
- 审查范围：`README.md`、`config.toml`、`python_accounting/models/{account,transaction,ledger,assignment,reporting_period,balance,recyclable,tax}.py`、`transactions/*`、`reports/*`

## 定位

以“原始单据”为中心的会计库：每种业务单据（现销、客户发票、收款、供应商账单、付款、红字单据、往来抵消、手工凭证）有专门的交易类型和校验规则，自动生成总账，并输出符合 IFRS/GAAP 的报表。

## 数据模型

- **Entity**（主体，创建时自动生成报告期间）、**Currency**、**ReportingPeriod**（状态 OPEN → ADJUSTING → CLOSED）；
- **Account**：类型由配置定义（BANK、RECEIVABLE、PAYABLE、CONTROL、OPERATING_REVENUE、OPERATING_EXPENSE、DIRECT_EXPENSE、CURRENT_ASSET、CONTRA_ASSET、EQUITY、RECONCILIATION…），可归入 Category；
- **Transaction（单据）**：类型（带编号前缀，如 IN/RC/BL/PY/JN）、单据号（按主体唯一、自动生成）、主账户、明细行（LineItem：账户、金额、数量、税、是否已含税）、汇率、是否复合凭证；
- **Ledger（总账行）**：由单据过账生成，每行记录 post_account / folio_account（对方科目）、金额、税、**hash**；
- **Assignment（核销）**：把“可核销单据”（发票、账单）与“可分配单据”（收款、付款、红字单据）按金额关联，支持部分核销；
- **Balance**：期初余额（按往来对象、单据号）；
- **Recyclable / Recycled**：软删除进入回收站，可恢复，并保留操作记录。

## 记账逻辑与算法

- **单据类型校验**：例如现销的主账户必须是 BANK 类型、明细行只能是收入类科目；客户发票主账户必须是 RECEIVABLE……配置项 `purchasables`、`clearables`、`assignables` 定义哪些类型可用于哪些场景；
- 过账后单据不可改类型、不可改金额（`posted` 后保护）；
- **报告期间**：同一主体只能有一个 OPEN 期间；ADJUSTING 期间只允许调整凭证；CLOSED 禁止写入；
- **防篡改哈希链**：每条总账行的哈希 = H(日期, 类型, 金额, **上一行哈希**（首行用盐）, 主体, 交易, 币种, 科目, 对方科目, 明细, 税)；直接改数据库会让后续哈希断裂，库可检测；
- 报表：利润表、资产负债表、现金流量表、试算平衡、账龄表（区间可配置），**报表的分区与项目全部由配置按科目类型定义**。

## 可借鉴

- [PA1] 单据类型 → 允许的主科目类型 / 明细科目类型（配置化校验）。
- [PA2] 期间三态：开放 / 调整中 / 已关闭。
- [PA3] 总账行哈希链（含上一行哈希 + 盐）检测数据库层篡改。
- [PA4] 核销（Assignment）：收款/付款与发票/账单的部分核销与未清余额、账龄表。
- [PA5] 报表结构配置化（按科目类型分区）。
- [PA6] 回收站式软删除（可恢复且留痕）。
- [PA7] 单据号按类型前缀 + 主体内唯一自动编号。

## 不采用 / 风险

- 单据类型偏传统贸易企业（发票/账单）；我们需要自定义业务类型（上游充值、卡网收入、账号采购）。

## 对新系统的启示

1. 交易类型（业务模板）配置中声明允许的科目角色/类型组合；
2. 期间状态 OPEN/ADJUSTING/CLOSED；
3. 分录或事件表做 SHA-256 哈希链 + 定期校验；
4. 核销关系表支持部分核销；
5. 报表定义数据化（报表项 → 科目角色集合）。
