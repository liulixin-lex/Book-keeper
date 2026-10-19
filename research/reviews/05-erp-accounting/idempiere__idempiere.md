# idempiere/idempiere（会计过账引擎）

- 分类：05 ERP 会计模块
- 语言 / 许可证 / 最近提交：Java (OSGi) / GPL-2.0 / 2026-10-14
- 审查范围（稀疏检出）：`org.idempiere.acct/src/org/idempiere/acct/doc/{Doc,DocLine,Fact,FactLine,DocManager,Doc_*}.java`、`org.adempiere.base/.../model/{MAcctSchema,MPeriodControl,MFactAcct}.java`

## 定位

Compiere/ADempiere 一脉的企业 ERP；其**单据过账引擎**是经典设计：业务单据与会计事实（Fact）分离，每种单据有自己的过账类，支持多套会计架构并行。

## 数据模型

- **C_AcctSchema（会计架构）**：本位币、成本方法、是否权责发生制、承诺会计类型、**暂挂平衡（suspense balancing）**、**币种平衡（currency balancing）**、科目段（organization、account、product、bpartner、project、activity、campaign、用户自定义段…）及哪些段需要平衡；一个公司可有**多套会计架构**（如本地准则 CNY + 集团报告 USD），同一单据按每套架构各过账一次；
- **Fact_Acct（会计事实行）**：架构、来源表 + 记录 ID + 行 ID、科目及各段值、原币借贷（AmtSource）与本位币借贷（AmtAcct）、币种、汇率日期、期间、过账类型（实际/预算/承诺/统计）；
- **Period Control**：按“期间 × 单据基础类型”控制开放/关闭（可只关闭某类单据）；
- **GL Distribution**：按规则把某科目的金额按百分比分配到多个段值。

## 记账逻辑与算法（过账流水线）

1. 拒绝不平衡（未开启暂挂平衡时）→ `STATUS_NotBalanced`；
2. 拒绝无法换算的币种 → `STATUS_NotConvertible`；
3. 拒绝已关闭期间 → `STATUS_PeriodClosed`；
4. `createFacts()`：各 Doc_* 子类按单据生成 Fact（可多个）；
5. 插件校验器（FactsValidationEngine）可否决；
6. 检查科目有效性 → `STATUS_InvalidAccount`；
7. `distribute()`：应用 GL 分配规则；
8. `balanceSource()`：原币不平时补平（暂挂科目）；
9. `balanceSegments()`：按需平衡的段（如组织间）生成往来分录；
10. `balanceAccounting()`：本位币因汇率舍入产生的差额记入**币种平衡科目**；
11. 写入 Fact_Acct；单据 `Posted` 状态记录结果码。
- **重过账（Repost）**：删除该单据在该架构下的 Fact_Acct（先写入历史表），重新执行流水线；后台会计处理器批量过账未过账单据。

## 可借鉴

- [ID1] **过账流水线 + 明确的状态码**（未平衡、不可换算、期间关闭、科目无效、错误、已过账）。
- [ID2] 业务单据与会计事实分离，单据可“未过账/过账失败”并给出原因，修复后重过账。
- [ID3] 原币平衡与本位币平衡分开处理：原币差额 → 暂挂科目，汇率舍入差额 → 币种平衡科目。
- [ID4] 多套会计架构并行（不同本位币/准则）。
- [ID5] 期间 × 单据类型的开关控制。
- [ID6] GL 分配（按百分比拆到多个维度值）。
- [ID7] 重过账前保存历史，可比较前后差异。

## 不采用 / 风险

- 体系庞大，科目“段组合（ValidCombination）”模型对小团队过度复杂；GPL。

## 对新系统的启示

1. 过账服务：输入（交易草稿/模板参数）→ 校验链（期间、科目、币种、平衡）→ 生成分录 → 舍入差额处理 → 写入；每一步失败返回**命名错误码**；
2. 支持“导入后过账失败”的状态与原因，修复后重过账；
3. 多币种：原币平衡与本位币平衡分别校验，舍入差额进专门科目；
4. 重过账留存前后差异（审计）。
