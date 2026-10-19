# andrewdwallo/erpsaas

- 分类：04 中小企业会计平台（Laravel + Filament）
- 语言 / 许可证 / 最近提交：PHP / MIT / 2026-03
- 审查范围：`app/Models/Accounting/*`、`app/Enums/Accounting/*`、`app/Observers/TransactionObserver.php`、`app/Casts/{MoneyCast,RateCast}.php`、`app/Services/*`

## 定位

权责发生制复式会计平台：科目表、交易（存入/取出/日记）、发票/账单、预算、调整项（折扣/税）、Plaid 银行同步。

## 数据模型

- **Account**：`category`（资产/负债/权益/收入/费用）、`type`（流动资产、非流动资产、**备抵资产/负债/权益/收入/费用**、经营/非经营收入与费用、**未分类收入 / 未分类费用**）、`subtype`；
- **Transaction**：type（deposit/withdrawal/journal）、`account_id`（损益类科目）+ `bank_account_id`（资金账户）、contact、payment_method、`is_payment`、reference、amount、**`pending`**（在途）、**`reviewed`（是否已人工复核）**、posted_at、created_by/updated_by、meta、plaid_transaction_id；
- **JournalEntry**：交易下的借/贷行（account、type、amount）；
- 金额通过 MoneyCast 以整数最小单位存储，汇率 RateCast 定点整数。

## 记账逻辑与算法

- TransactionObserver：保存交易时自动生成/更新对应的两条日记账行；若关联发票/账单则重算其已付金额与状态；删除时同步清理。
- 银行同步导入的交易默认记入“未分类收入/费用”并标记未复核，进入复核队列。

## 可借鉴

- [ES1] **未分类收入/未分类费用科目** + `reviewed` 标记：导入即入账但待复核，复核时改分类 —— 不阻塞流水入账，又保留待办。
- [ES2] 备抵科目在类型层面完整覆盖。
- [ES3] 交易保存时自动生成分录（简单录入 → 标准分录）。
- [ES4] 金额与汇率都用整数定点存储。

## 不采用 / 风险

- 交易与分录强耦合、可直接改删（无冲正语义）。

## 对新系统的启示

- 设置“待分类”过渡科目，导入数据可先入账再复核（复核即改类，生成调整/冲正）；
- 交易带 `review_status`（unreviewed / reviewed），提供复核队列 API。
