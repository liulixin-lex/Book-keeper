# frappe/books

- 分类：04 中小企业会计软件（桌面，Electron + SQLite）
- 语言 / 许可证 / 最近提交：TypeScript + Vue / AGPL-3.0 / 2026-10（仓库已归档）
- 审查范围：`schemas/app/*.json`、`models/Transactional/{Transactional,LedgerPosting}.ts`、`fyo/`（框架）、`reports/`、`regional/`

## 定位

轻量桌面会计（发票、付款、日记账、库存、报表），以 **JSON Schema 驱动** 的通用文档框架（fyo）实现：所有业务对象由 schema 描述字段、关联、是否可提交，框架自动生成表、表单、列表与校验。

## 数据模型

- **Account**：`rootType`（资产/负债/权益/收入/费用）、`parentAccount`、`accountType`（银行、现金、应收、应付、存货、税、四舍五入…）、`isGroup`（是否为汇总科目）；
- **AccountingLedgerEntry（总账行）**：date、party、account、debit、credit、**referenceType + referenceName（动态链接回来源单据）**、**reverted、reverts（冲销行指向被冲行）**；
- 可提交文档（`isSubmittable`）：SalesInvoice、PurchaseInvoice、Payment、JournalEntry……状态：草稿 → 已提交 → 已取消；
- NumberSeries（编号序列，按前缀自增）、Currency 与 ExchangeRate、PricingRule、地区化（regional）模型。

## 记账逻辑与算法

- **生命周期钩子**：所有“提交时生成总账”的模型继承 Transactional：`afterSubmit` → `getPosting()` 生成 LedgerPosting → 校验借贷相等 → 写入；`afterCancel` → 生成**反向总账行**（reverted/reverts 相互标记），原文档变为已取消，不删除任何行。
- LedgerPosting 按科目合并同方向金额（每个科目每方向一行），`makeRoundOffEntry()` 把借贷尾差记到“四舍五入”科目。
- 金额使用 pesa（定点小数库）避免浮点误差。

## 可借鉴

- [FB1] Schema 驱动的数据模型与表单、列表、校验（新系统前端阶段可参考：后端暴露 JSON Schema，前端自动生成表单）。
- [FB2] 文档三态（草稿/已提交/已取消）与提交/取消钩子，取消时自动生成反向分录。
- [FB3] 总账行的动态引用（来源单据类型 + 编号）与冲销互指。
- [FB4] 尾差自动入“四舍五入”科目，且有明确阈值。
- [FB5] 编号序列独立管理（前缀 + 自增）。
- [FB6] 定点小数库处理金额。

## 不采用 / 风险

- AGPL-3.0；已归档不再维护；单用户桌面应用。

## 对新系统的启示

- 交易生命周期：draft → posted → reversed（取消即生成反向交易）；
- 尾差处理：明确的舍入科目与允许阈值（如单笔 ≤ 0.01 本位币）；
- 后端为每种交易类型输出 JSON Schema，供前端/AI 动态生成表单与参数。
