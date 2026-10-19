# adamcharnock/django-hordak

- 分类：03 复式记账库（Django）
- 语言 / 许可证 / 最近提交：Python / MIT / 2026-04
- 审查范围：`hordak/models/core.py`、`hordak/migrations/*`（数据库触发器）、`hordak/utilities/{currency,money,account_codes,statement_import}.py`

## 定位

Django 的复式记账模型层，强调“数据库层面保证正确性”。

## 数据模型

- **Account（MPTT 树）**：uuid、name、`code` 与触发器维护的 `full_code`（父子编码拼接）、`type`：资产 AS / 负债 LI / 收入 IN / 费用 EX / 权益 EQ / **货币交易 TR（Trading）**、`currencies`（允许的币种列表）、`is_bank_account`（银行账户只能单币种）；
- **Transaction**：uuid、timestamp、date、description；
- **Leg（分录腿）**：transaction、account、`debit`/`credit`（Money，带币种）、description；**同一交易所有腿之和必须为 0，且必须同一币种**；
- **StatementImport / StatementLine**：银行流水导入批次与流水行，流水行可关联到一笔交易（`is_reconciled`），并可一键 `create_transaction(to_account)` 生成对应交易。

## 记账逻辑与算法

- **数据库约束触发器**：`DEFERRABLE INITIALLY DEFERRED` 的约束触发器在事务提交时检查每笔交易的腿之和为 0；另有零金额检查、账户类型检查、叶子账户检查等触发器。
- **余额方向**：`sign()` 基于会计等式 `0 = 负债 + 权益 + 收入 − 费用 − 资产`，资产与费用为 −1，其余 +1。
- **多币种（交易账户法）**：换汇通过 Trading 账户完成——来源币种转入交易账户，目标币种从交易账户转出；交易账户的多币种余额“归一化”后即为**未实现汇兑损益**。内部始终以原币存储与计算，换算只用于展示（文档明确指出换算有损：¥176.51→$1.54→¥176.20）。
- `Balance` 对象表示多币种余额（每币种一个 Money），支持加减。
- 查询：`with_account_balance_before/after` 窗口函数给出每条腿前后余额。

## 导入与对账

- 流水导入（CSV 映射）+ 流水行与交易一对一核对；未核对流水可快速生成交易。

## 可借鉴

- [HK1] 延迟约束触发器在提交时校验交易平衡（允许事务中逐腿插入）。
- [HK2] **货币交易账户（Trading account）法处理换汇**，每笔交易单币种平衡，汇兑损益可从交易账户余额推出。
- [HK3] 账户允许币种列表；银行类账户单币种。
- [HK4] 账户编码树 + 自动维护完整编码。
- [HK5] 流水导入批次 → 流水行 → 关联交易（核对状态）→ 由流水生成交易。
- [HK6] 窗口函数计算每条分录前后余额（无需存储冗余列也能查询）。

## 不采用 / 风险

- “每笔交易单币种”会让一笔跨币种业务拆成多笔，需在上层把它们组合展示（我们可以允许一笔交易多币种但要求“每币种分别平衡”，通过交易账户实现）。

## 对新系统的启示

1. 多币种平衡规则：同一交易内**每个币种各自借贷平衡**，跨币种通过“货币兑换”过渡科目（Trading）衔接，汇兑差额进损益；
2. Postgres 延迟约束触发器做最终平衡校验；
3. 流水（statement line）作为一级实体，与交易建立核对关系。
