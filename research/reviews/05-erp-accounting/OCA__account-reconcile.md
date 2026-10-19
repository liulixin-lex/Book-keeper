# OCA/account-reconcile（Odoo 社区对账模块）

- 分类：05 ERP 会计模块（对账）
- 语言 / 许可证 / 最近提交：Python (Odoo 19) / AGPL-3.0 / 2026-10-16
- 审查范围：`account_reconcile_oca/models/{account_bank_statement_line,account_reconcile_abstract,account_reconcile_model,account_account_reconcile}.py`、`account_statement_base`、`account_in_payment`、`account_reconcile_analytic_tag`

## 定位

为 Odoo 社区版补齐企业版才有的银行对账界面与逻辑：银行流水行逐笔核对到发票/付款/科目，支持手工拆分、核对模型、外币、分析分摊。

## 数据模型与流程

- **暂挂科目（suspense account）机制**：银行流水导入即生成凭证，借/贷银行科目，对方先记入“暂挂科目”；核对时用真实对方行（应收应付行、费用科目行、核对模型生成的行）**替换暂挂行**，未分配部分仍留在暂挂科目——流水永远先入账，差额永远可见；
- 流水行上保存核对工作数据（`reconcile_data` JSON：拟核对的行、手工新增行、金额、往来方、分析分摊、外币金额、汇兑对冲行），可保存草稿后继续；
- 手工行：指定科目、往来方、金额（可部分）、币种与原币金额、是否生成汇兑差额对冲行、使用某个核对模型；
- **聚合（aggregate）**：按日期/对账单/无对流水分组，便于批量处理；
- `account_in_payment`：发票“付款中”状态（已有付款但未与银行流水核对）。

## 可借鉴

- [OCA1] **暂挂科目**：外部流水先入账到暂挂（待核对）科目，核对过程就是把暂挂余额逐步转到正确科目；暂挂余额 = 未处理金额。
- [OCA2] 核对工作区可保存草稿（JSON），支持多人/多次完成。
- [OCA3] 部分分配 + 剩余留暂挂；外币核对自动生成汇兑差额对冲行。
- [OCA4] “付款中”中间状态（已付款未对账）。

## 不采用 / 风险

- 强依赖 Odoo 框架；AGPL。

## 对新系统的启示

- 与 erpsaas 的“未分类科目”同理：建立“待核对/待分类”过渡科目族（按来源：卡网待匹配、Stripe 在途、上游额度待确认），导入流水先入账，再逐步核销转出；过渡科目余额就是待办量；
- 核对会话可暂存，完成时一次性生成分录。
