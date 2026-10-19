# frappe/erpnext（accounts 模块）

- 分类：05 ERP 会计模块
- 语言 / 许可证 / 最近提交：Python (Frappe) + JS / GPL-3.0 / 2026-10-18
- 审查范围：`erpnext/accounts/general_ledger.py`、`erpnext/accounts/doctype/{gl_entry,payment_ledger_entry,journal_entry,accounting_period,period_closing_voucher,account_closing_balance,accounting_dimension*,bank_transaction_rule,bank_reconciliation_tool,exchange_rate_revaluation,repost_accounting_ledger,ledger_health_monitor,bisect_accounting_statements,payment_reconciliation}`

## 定位

全球用户最多的开源 ERP 之一，会计模块成熟且细节完备：所有业务单据过账到统一的 GL Entry，附带应收应付专用的 Payment Ledger、多维度、多账簿、期间关闭、重估、重过账、账本健康监控。

## 数据模型

- **GL Entry（总账行）**——三层币种：
  - 公司本位币：`debit / credit`；
  - 科目币种：`account_currency`、`debit_in_account_currency / credit_in_account_currency`；
  - 交易币种：`transaction_currency`、`transaction_exchange_rate`、`debit/credit_in_transaction_currency`；
  - 另有报告币种（reporting currency）与其汇率；
  - 业务字段：`posting_date`（记账日）与 `transaction_date`（单据日）、`party_type + party`（往来方）、`cost_center`、`project`、`finance_book`（**多账簿**，如税务账与管理账）、`against`（对方科目）、`against_voucher_type/no`（核销到哪张单据）、`voucher_type/no/detail_no`（**来源单据及其明细行**）、`is_opening`、`is_advance`、`due_date`、`is_cancelled`、`voucher_subtype`、`remarks`。
- **Payment Ledger Entry**：只记应收/应付科目的未清金额流水（voucher ↔ against_voucher、金额、`delinked`），未清余额 = 按 against_voucher 汇总，核销/取消核销只改这里——与 GL 分离，避免为算未清扫描全部 GL。
- **Accounting Period**：起止日期 + `closed_documents`（**按单据类型分别关闭**，如只关闭销售发票）+ 豁免角色；
- **Period Closing Voucher**：年结凭证（损益结转到指定科目），处理状态（异步）；**Account Closing Balance**：结账日每个科目×成本中心×项目×账簿的期末余额快照；
- **Accounting Dimension + Dimension Filter**：自定义维度（如渠道、区域），可设“对资产负债类/损益类必填”，并按科目“允许/限制”维度取值；
- **Bank Transaction Rule**：交易类型、金额区间（min/max）、描述条件、分类为（银行分录/付款…）、目标科目、往来方、**优先级**；
- **Exchange Rate Revaluation**：期末对外币科目按新汇率重估，计算已/未入账损益，舍入损失容差；
- **Repost Accounting Ledger**：对指定单据重新生成 GL（规则/配置修正后），可选删除已取消的分录；异步任务 + 错误日志；
- **Ledger Health Monitor**：定期检查最近 N 天的“借贷不平”“GL 与 Payment Ledger 不一致”；
- **Bisect Accounting Statements**：在日期区间上二分查找，定位“资产负债表不平/损益与资产负债表差异”出现的区间（调试工具）；
- Journal Entry：多币种开关、凭证类型（含“汇兑损益”）、模板、自动重复、冲销（reversal_of）、清算日期（对账）。

## 记账逻辑与算法

- `make_gl_entries`：校验科目未停用、冻结日期（Accounts Frozen Till Date，指定角色可越过）、会计期间、维度必填；合并同科目同维度的行；
- **尾差处理**：按本位币精度四舍五入后计算借贷差；差额超过容差（日记账/付款 = 5×最小单位，其他单据 = 0.5）报错，未超过则自动生成“尾差科目”分录（Round Off，成本中心可配）；交易币种差额同样处理；
- 取消 = `make_reverse_gl_entries`：生成反向 GL 并标记 `is_cancelled`；
- 多币种：单据记交易币种与汇率，GL 同时落三层金额；期末重估生成汇兑损益凭证。

## 追溯与审计

- 每条 GL 指向来源单据与明细行；版本历史（Frappe Version doctype 记录字段级变更）；修订（amended_from，取消后修订生成新编号如 -1）。

## 导入、分类与对账

- 银行流水（Bank Transaction）+ 规则自动分类 + 银行对账工具（匹配付款/日记账/发票）+ Payment Reconciliation（发票与付款批量核销，支持部分分配）。

## 可借鉴

- [EN1] **三层币种金额**（本位币 / 科目币种 / 交易币种）+ 各自汇率，必要时加报告币种。
- [EN2] 来源单据 + 明细行号（voucher_type/no/detail_no）精确追溯。
- [EN3] 往来未清金额专用台账（Payment Ledger）与 GL 分离；核销/取消核销只动台账。
- [EN4] 按单据类型分别关闭期间；冻结日期 + 豁免角色。
- [EN5] 多账簿（finance_book）。
- [EN6] 维度 + 维度过滤（某些科目必须/禁止某维度取值）。
- [EN7] 尾差容差 + 自动尾差科目；超过容差报错。
- [EN8] 期末汇率重估凭证。
- [EN9] **重过账（Repost）**：配置/规则修正后对指定单据重新生成分录。
- [EN10] **账本健康监控**与**二分定位差异**工具。
- [EN11] 银行规则含金额区间与优先级。

## 不采用 / 风险

- 取消-修订产生“-1/-2”编号的模式会让单据号复杂化；新系统用冲正 + 新交易并互相引用。
- 体量巨大、强依赖 Frappe 框架；GPL-3.0 只参考。

## 对新系统的启示

1. 分录行金额：`amount_minor`（原币）+ `currency` + `base_amount_minor`（本位币）+ `fx_rate_id`；如需科目币种另存；
2. 交易保存来源凭证引用（类型、ID、行号/字段路径）；
3. 往来（供应商/渠道）未清台账：上游站“已付款未兑换额度”、卡网“已下单未到账”可建为往来未清；
4. 期间关闭支持按交易类型粒度；
5. 内置健康检查（借贷平衡、子账一致性、余额断言）与“差异二分定位”工具；
6. 重过账工具（与 pyluca 的重放思路结合）。
