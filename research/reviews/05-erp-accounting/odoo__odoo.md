# odoo/odoo（addons/account、analytic、account_payment、base_import）

- 分类：05 ERP 会计模块
- 语言 / 许可证 / 最近提交：Python / LGPL-3.0（社区版）/ 2026-10-18
- 审查范围（稀疏检出）：`addons/account/models/{account_move,account_move_line,account_account,account_journal,account_partial_reconcile,account_full_reconcile,account_reconcile_model,account_lock_exception,company,sequence_mixin,account_cash_rounding,res_currency}.py`、`addons/analytic`

## 定位

最成熟的开源 ERP 会计实现之一：凭证（account.move）+ 凭证行（account.move.line）承载一切，核销（reconcile）、锁账、序列、分析分摊设计非常精细。

## 数据模型

- **account.move（凭证）**：日记账（journal）、日期、编号（sequence_mixin：按日记账+年/月前缀连续，检查断号）、状态 draft/posted/cancel、来源（invoice_origin、ref）、冲销关系（reversed_entry_id）、**不可变哈希**（`inalterable_hash` + `secure_sequence_number`，日记账开启“哈希保护已过账凭证”后启用，关闭需满足条件）；
- **account.move.line**：科目、往来方、`balance`（本位币，借正贷负）、`debit/credit`（由 balance 派生）、**`amount_currency` + `currency_id`（原币）**、`amount_residual / amount_residual_currency`（未核销余额）、`matching_number`（核销号，部分核销以 P 开头）、**`analytic_distribution`（JSON：分析账户 → 百分比，可一行按比例分摊到多个分析维度）**、累计余额、税信息；
- **核销**：`account.partial.reconcile`（借方行、贷方行、本位币金额、两侧原币金额、max_date、**汇兑差异凭证 exchange_move_id**）→ 全部结清时生成 `account.full.reconcile`；
- **锁账日期（company）**：全局（会计年度）锁账、税务锁账、销售锁账、采购锁账、**硬锁账（不可回退）**；锁定期内的新凭证**自动顺延到下一个可用日期**（按日记账序列）而不是直接拒绝；
- **锁账例外（account.lock_exception）**：针对某个用户（或所有人）、某类锁账日期、截止时间、原因的临时例外，自动失效并留痕；
- **核对模型（account.reconcile.model）**：触发方式（手动/自动）、适用日记账、金额条件（小于/大于/介于）、标签条件（包含/不包含/正则）、往来方映射、**付款容差（金额或百分比）**、匹配顺序（新→旧/旧→新）、类型（匹配已有行 / 生成核销分录的模型，分录行金额可为固定/百分比/从标签正则提取）；
- `account.cash.rounding`（现金舍入规则）、`res.currency.rate`（按日汇率，多公司）。

## 记账逻辑与算法

- 凭证行 balance 为唯一真相，借贷由其派生；同一凭证 Σbalance = 0（本位币），原币金额各自记录；
- 部分核销：按 max_date 与币种计算两侧金额，原币已结清但本位币有差额时自动生成**汇兑损益凭证**；
- 序列：草稿不占号，过账分配；检测并报告断号；
- 锁账检查在过账与修改时进行，硬锁不可撤销；
- 分析分摊：一条费用行可按 60%/40% 分配到两个项目/渠道，分析报表按分摊后的金额统计。

## 可借鉴

- [OD1] balance（本位币带符号）为准，借贷派生；原币 amount_currency 并存。
- [OD2] **部分核销表**（两侧行、两种币种金额）+ 结清后的完全核销 + 自动汇兑差异凭证。
- [OD3] 行级未核销余额（residual）随核销实时维护。
- [OD4] 多类锁账日期 + **硬锁** + **临时锁账例外（用户、期限、原因）**。
- [OD5] 锁账期内的录入自动顺延到可用日期（可配置为拒绝或顺延）。
- [OD6] 核对模型：金额区间、标签正则、往来方映射、容差（金额/百分比）、自动/手动、生成分录模板（金额可从文本正则提取）。
- [OD7] 分析分摊 JSON（按百分比分配到多个维度值）。
- [OD8] 已过账凭证哈希链 + 无断号安全序号。
- [OD9] 序列断号检测。

## 不采用 / 风险

- 体量与 ORM 耦合；部分高级功能（会计报表、银行同步）在企业版。
- “自动顺延日期”在我们的场景下可能掩盖错误，默认应拒绝并提示。

## 对新系统的启示

1. 分录行：`amount_minor`（原币，带符号）+ `currency` + `base_amount_minor`（本位币，带符号）——两个币种分别平衡；
2. 核销（reconciliation）设计：partial_reconciliations（行 A、行 B、金额、原币金额）+ full_reconciliation；结清时自动生成汇兑差额分录；
3. 锁账：global / per-type 锁账日 + 硬锁 + 临时例外（期限、原因、操作人，自动过期）；
4. 分析分摊：分录行 `dimensions` 支持百分比分配；
5. 已过账交易进入哈希链；编号连续且可检测断号；
6. 核对规则模型参照 OD6。
