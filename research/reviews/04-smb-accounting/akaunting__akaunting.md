# akaunting/akaunting

- 分类：04 中小企业在线会计（Laravel）
- 语言 / 许可证 / 最近提交：PHP (Laravel) + Vue / **Business Source License**（源码可见，非 OSI 开源；早期为 GPL）/ 2026-10-08
- 审查范围：`app/Models/{Banking,Setting,Common,Document}`、`app/Reports`、`app/Events`、`app/Traits/Recurring`

## 定位

以“收入/支出/转账”交易为核心的在线记账软件，配合发票、账单、联系人、多币种，以及庞大的模块市场。复式记账（总账、科目表、凭证）是付费扩展模块，核心不是复式。

## 数据模型

- **Transaction**：`type`（income / expense / transfer 及 *-recurring 模板）、`number`、`account_id`（资金账户：银行/现金）、`paid_at`、`amount`（double）、`currency_code` + `currency_rate`、`document_id`（关联发票/账单）、`contact_id`、`category_id`、`payment_method`、`reference`、**`parent_id`（重复交易生成的子交易）**、**`split_id`（拆分交易）**、**`created_from`（来源：界面/API/导入/模块）**、`created_by`；
- **Reconciliation**：账户、期间开始/结束、对账单期末余额、本次核对的交易 ID 列表、是否完成；
- **Transfer**：两个账户之间转账，生成一收一支两笔交易；
- **Category**（收入/支出/项目/其他类型，可树状）、**Currency**（汇率、精度、符号位置、千分位）、**Tax**；
- **Recurring**：周期规则（频率、间隔、开始、次数/截止），定时生成子交易。

## 记账逻辑与算法

- 单式“收入/支出”记账 + 分类汇总报表（收入汇总、支出汇总、收支对比、损益、税汇总）；
- 对账：选择账户与期间，输入对账单期末余额，勾选交易使“期初 + 勾选合计 = 期末”，差额为 0 才能完成；
- 每个模型的增删改都触发 Creating/Created/Updating… 事件，模块通过监听扩展功能。

## 可借鉴

- [AK1] 交易记录 `created_from`（来源渠道）+ `created_by` —— 追溯写入方（界面/API/导入/AI）。
- [AK2] 对账会话：期间 + 对账单期末余额 + 勾选交易 + 差额为零才完成，并保存核对的交易清单。
- [AK3] 重复交易模板生成子交易（parent_id）；拆分交易（split_id）。
- [AK4] 币种表包含显示精度、符号、千分位等展示属性。
- [AK5] 全面的领域事件钩子 → 模块化扩展。

## 不采用 / 风险

- 核心非复式、金额 double；BSL 许可证。
- 用户已要求去掉订阅管理，“重复交易”只作为可选的录入模板，不做订阅合同管理。

## 对新系统的启示

- 所有交易记录 `source`（ui/api/mcp/import/system）、`actor`、`client_id`（哪个 API Token/AI 客户端）；
- 对账会话实体（账户、期间、外部期末余额、核对清单、差额、状态）；
- 领域事件总线（交易已过账、已冲正、导入完成……）供 Webhook 与扩展使用。
