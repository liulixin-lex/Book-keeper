# ledgersmb/LedgerSMB

- 分类：04 Web 复式会计 / ERP（SQL-Ledger 分支演进）
- 语言 / 许可证 / 最近提交：Perl + PostgreSQL（大量逻辑在存储过程中）/ GPL-2.0 / 2026-10-18
- 审查范围：`sql/Pg-database.sql`（核心表）、`sql/modules/{Reconciliation,EndOfYear,Business_Unit,Transaction_Templates,Duplicates_Functions,trial_balance,Drafts}.sql`、`workflows/`

## 定位

老牌开源中小企业会计/ERP：总账、应收应付、库存、银行对账、年结，数据库函数承担大部分业务规则。

## 数据模型

- `transactions`（所有财务交易的公共头，提供跨 AR/AP/GL 的引用完整性与**跨连接的业务锁** `locked_by`）；
- `gl`（日记账头）、`acc_trans`（**分录行**：交易、科目、`amount`（正负表示借贷）、日期、`source`（来源单据号）、`cleared`（已勾对）、`cleared_on`、`reconciled_on`、`fx_transaction`（汇兑行标记）、memo、voucher）；
- **`account_checkpoint`**：某日各科目的余额（含借贷发生额）快照；**规则：不得在最新检查点日期之前过账，已关闭期间内不得残留未批准的凭证/草稿**——检查点同时是“结账”与“余额快照”；
- `batch` / `voucher`：一批凭证作为整体录入与过账（批次控制号）；
- `business_unit`（业务单元，按类别：部门、项目、作业、成本中心……；带起止日期、层级、可关联客户/供应商）——多维度核算；
- `cr_report` / `cr_report_line`：**银行对账报告**（科目、对账单期末余额 `their_total`、截止日、提交/审核状态；行：对方余额 vs 我方余额、错误码、是否勾对、忽略标记）。

## 记账逻辑与算法

- 对账流程：新建报告（科目 + 截止日 + 对账单余额）→ 自动把未勾对的分录行列入（`pending_transactions`）→ 逐行勾对 / 导入对账单行自动匹配（按支票号/金额/日期）→ 计算已勾对余额，与对账单余额比较 → 提交；已完成的报告受触发器保护不可修改；
- 年结（EndOfYear）：结转损益到留存收益并写检查点；
- 交易模板（Transaction_Templates）；重复检测函数（Duplicates_Functions）；草稿管理（Drafts）；试算平衡函数。

## 可借鉴

- [LS1] **余额检查点 = 结账日 + 各科目余额快照**，检查点之前禁止过账（一个实体同时解决“锁账”和“报表加速”）。
- [LS2] 分录行级的“已勾对 / 勾对日期 / 已对账日期”字段。
- [LS3] 对账报告：对账单余额 vs 我方已勾对余额，逐行状态，完成后不可改。
- [LS4] 业务单元多维度（类别 + 层级 + 生效期间）。
- [LS5] 批次（batch）把一组凭证作为一个单元录入与过账，带控制号。
- [LS6] 汇兑损益行显式标记（fx_transaction）。

## 不采用 / 风险

- 批次审批、凭证审批属于审批流程（用户要求去掉）；只保留“批次”作为分组与追溯单位。
- Perl 技术栈、单一 amount 正负号表示借贷（可读性差）。

## 对新系统的启示

1. `balance_checkpoints`（period_end, account, currency, balance, debit_total, credit_total）既用于锁账也用于报表加速；
2. 分录行增加对账状态字段（cleared_at、reconciliation_id）；
3. 导入批次（import_batch）作为一等实体：批次号、来源、文件哈希、生成的交易列表，可整体冲正；
4. 维度（dimension）支持类别、层级、生效期间。
