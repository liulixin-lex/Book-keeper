# apache/ofbiz-framework（applications/accounting + datamodel）

- 分类：05 ERP 会计模块
- 语言 / 许可证 / 最近提交：Java（实体引擎 + 服务引擎 + XML 定义）/ Apache-2.0 / 2026-10-18
- 审查范围（稀疏检出）：`applications/datamodel/entitydef/accounting-entitymodel.xml`（AcctgTrans、AcctgTransEntry、GlAccount、GlAccountTypeDefault、GlReconciliation…）、`applications/accounting/{servicedef,src,minilang}`

## 定位

Apache 的企业级电商/ERP 框架，会计以“通用数据模型（Universal Data Model）”风格建模，所有业务事件通过服务（ECA 事件触发）生成会计交易。

## 数据模型

- **AcctgTrans（会计交易头）**：类型（AcctgTransType：发票、付款、库存、折旧、手工…）、`transactionDate`、`isPosted` + `postedDate`、**`scheduledPostingDate`（计划过账日）**、日记账、**`glFiscalTypeId`（实际 ACTUAL / 预算 BUDGET / 预测 FORECAST / 计划 PLAN…，同一账本存不同口径）**、`voucherRef/voucherDate`（外部凭证号）、关联对象（party、invoice、payment、finAccountTrans、shipment、receipt、fixedAsset、inventoryItem、workEffort）、**`theirAcctgTransId`（对方系统中的交易号）**、创建/修改人与时间；
- **AcctgTransEntry（分录行）**：`glAccountId` + **`glAccountTypeId`**、`organizationPartyId`、`amount` + `currencyUomId`（本位币）、**`origAmount` + `origCurrencyUomId`（原币）**、`debitCreditFlag`、party/theirParty、product、`dueDate`、`groupId`、tax、**`reconcileStatusId`**、`isSummary`；
- **GlAccount**：编码、名称、类型（GlAccountType）、**类别（GlAccountClass：借方性质/贷方性质层级）**、资源类型（货币/时间…）、**XBRL 分类**、父科目、外部 ID；
- **GlAccountTypeDefault**：**“科目类型 → 实际科目”的组织级默认映射**（如 ACCOUNTS_PAYABLE → 210000），业务逻辑只引用科目类型，具体科目可按组织配置；还有 PaymentGlAccountTypeMap、InvoiceItemTypeGlAccount 等映射表；
- **GlReconciliation**：科目、期初余额、核对后余额、核对日期、状态；GlReconciliationEntry（分录行 + 核对金额，可部分）。

## 记账逻辑与算法

- 业务服务（创建发票、收款……）通过 ECA 触发会计服务，根据映射表解析科目，生成 AcctgTrans + Entries，校验借贷平衡后过账；
- 定期期间（CustomTimePeriod）与期末结账服务；预算口径与实际口径并存，可直接出预算对比。

## 可借鉴

- [OF1] **科目类型间接层**：业务规则引用“科目类型/用途”，由映射表解析为具体科目——更换科目表不改代码。
- [OF2] 财务口径类型（实际/预算/预测）共用账本结构。
- [OF3] 分录行原币 + 本位币；外部凭证号与对方交易号字段。
- [OF4] 计划过账日（未来自动过账）。
- [OF5] 核对记录（期初/核对后余额 + 分录级核对金额）。
- [OF6] XBRL 分类映射（标准化报表编码）。

## 不采用 / 风险

- 实体引擎 + XML 配置的开发模式过重；功能面过宽。

## 对新系统的启示

- 交易模板中科目通过“科目用途（role/purpose）”间接引用，映射表可配置（如 `UPSTREAM_COST`、`CHANNEL_FEE`、`STRIPE_CLEARING`）；
- 预算作为独立口径（fiscal_type=budget）存储，复用报表；
- 字段 `external_ref`（外部凭证号/订单号）与 `counterparty_ref`（对方交易号）分开。
