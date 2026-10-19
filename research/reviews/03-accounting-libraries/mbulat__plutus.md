# mbulat/plutus

- 分类：03 复式记账库（Rails Engine）
- 语言 / 许可证 / 最近提交：Ruby / MIT / 2025-03
- 审查范围：`README.markdown`、`app/models/plutus/{account,entry,amount,asset,...}.rb`

## 定位

标准会计教科书模型的 Rails 实现：科目 + 凭证 + 借方金额/贷方金额。

## 数据模型

- **Account（单表继承）**：Asset / Liability / Equity / Revenue / Expense，各自定义正常余额方向（借/贷）；**contra（备抵）账户**可反转正常方向（如“累计折旧”是备抵资产、“提款”是备抵权益）；
- **Entry**：description（必填）、date、**commercial_document（多态关联到业务单据，如发票、订单）**；
- **Amount**：DebitAmount / CreditAmount 子类，关联 entry 与 account；
- 可选多租户（tenancy）。

## 记账逻辑与算法

- 校验：至少一借一贷、借贷总额相等、描述必填；
- 余额：按科目类型的正常方向计算，可按日期区间；`Account.trial_balance` 应恒为 0（会计等式校验）。

## 可借鉴

- [PL1] 科目类型决定正常余额方向 + 备抵科目反转。
- [PL2] 凭证多态关联业务单据（commercial_document）。
- [PL3] 试算平衡为零作为全局不变量检查。

## 不采用 / 风险

- 金额为 decimal 但无币种概念；无期间、无冲销语义。

## 对新系统的启示

- 科目属性增加 `is_contra`；
- 交易关联“来源单据”采用 (类型, ID) 多态引用；
- 健康检查包含“全账试算平衡 = 0”。
