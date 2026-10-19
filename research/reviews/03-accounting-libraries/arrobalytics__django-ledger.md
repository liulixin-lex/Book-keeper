# arrobalytics/django-ledger

- 分类：03 复式会计与财务分析引擎（Django）
- 语言 / 许可证 / 最近提交：Python / GPL-3.0 / 2026-10-09
- 审查范围：`django_ledger/models/{entity,chart_of_accounts,accounts,ledger,journal_entry,transactions,closing_entry,data_import,bill,invoice}.py`、`django_ledger/io/roles.py`

## 定位

完整的会计引擎：实体（公司）→ 科目表 → 账簿（Ledger）→ 凭证（Journal Entry）→ 分录（Transaction），带发票/账单/采购单、银行导入、财务报表与比率分析。

## 数据模型

- **EntityModel**：会计主体（含会计年度起始月、是否权责发生制）；**EntityUnit**：主体下的单元/部门维度；
- **ChartOfAccounts → Account**：编码、名称、**role（细粒度角色，如 `asset_ca_cash` 现金、`asset_ca_receivables` 应收、`liability_cl_acc_payable` 应付、`income_operational`、`expense_op`、`cogs_regular`…）**、余额方向、锁定/启用；角色分组驱动报表归类；
- **LedgerModel**：一组凭证的容器（如一张发票对应一个账簿），`posted` / `locked` / `hidden`；
- **JournalEntryModel**：timestamp、description、entity_unit、**activity（经营/投资/筹资，可由分录涉及的科目角色自动推断）**、origin（来源）、`posted`、`locked`、`is_closing_entry`；
- **TransactionModel**：account、tx_type（debit/credit）、amount、description；
- **ClosingEntry**：结账日各科目（及单元、活动类型）余额快照；报表可从最近结账快照起算以提速；
- **ImportJob → StagedTransaction**：银行流水暂存行（fit_id 去重、金额、拆分、活动类型、目标科目、单元、供应商/客户、`matched_transaction`），确认后生成或匹配到正式交易。

## 记账逻辑与算法

- 凭证 `verify()`：借贷平衡、分录合法性、活动类型推断；`post()` / `lock()` 分级状态（账簿级与凭证级）；已锁定不可修改；
- 财务报表：资产负债表、利润表、**现金流量表（间接法，按角色分组计算各项调整）**，以及比率（流动比率、利润率等）；
- 结账快照：按日期/月份/会计年度生成，报表读取“最近快照 + 之后增量”，带缓存键。

## 可借鉴

- [DL1] **科目角色（role）分类体系**：报表项目由角色决定，而不是靠科目名称/编码约定 —— 用户可自由命名科目，报表仍正确归类。
- [DL2] 凭证活动类型（经营/投资/筹资）自动推断 → 自动生成现金流量表。
- [DL3] 账簿/凭证两级 posted + locked 状态。
- [DL4] 结账余额快照加速报表。
- [DL5] 银行流水暂存表（staged）→ 匹配已有交易或生成新交易；fit_id 去重；支持拆分。
- [DL6] 主体单元（部门/项目）作为分录维度。

## 不采用 / 风险

- GPL-3.0；金额 decimal(15,2) 不区分币种（单币种设计）；
- 发票/采购单等进销存功能超出当前需求。

## 对新系统的启示

1. 科目增加 `role`（报表角色），报表引擎按角色映射资产负债表、利润表、现金流量表项目；
2. 现金流量表按“现金类科目的对方科目角色”自动分类经营/投资/筹资；
3. 导入暂存层（staging）是必需的，所有外部数据先进暂存，再匹配/生成交易；
4. 期末余额快照（closing snapshot）用于报表与锁账。
