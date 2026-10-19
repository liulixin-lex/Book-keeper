# LerianStudio/midaz

- 分类：02 账本引擎 / 核心银行平台
- 语言 / 许可证 / 最近提交：Go（PostgreSQL + MongoDB + RabbitMQ + Valkey）/ Elastic License 2.0（源码可见，非 OSI 开源）/ 2026-10-18
- 审查范围：`llms.txt`、`pkg/mmodel/{operation-route,transaction-route,balance,balance_trail,account-type}.go`、`components/ledger/pkg/{fee,feeshared}`

## 定位

完整的核心银行平台：复式账本 + 实时交易校验/风控（Tracer）+ CRM + 手续费引擎。层级：组织 → 账簿 → 资产/组合/分部 → 账户 → 交易/操作 → 余额。

## 数据模型

- **Organization / Ledger / Asset / Portfolio / Segment / Account / AccountType**：资产（币种）在账簿级定义；组合（Portfolio）和分部（Segment）是账户的两个分析维度。
- **Transaction → Operation**：每条操作是一条借或贷，记录操作前/后的余额快照（balance trail，含版本号与 `recorded_at`，`recorded_at` 不能被客户端回填）。
- **Balance**：`available` / `on_hold` + 版本号；可配置透支额度与“双余额”。
- **Operation Route（操作路由）**：一类资金动作的模板，含账户选择规则（按别名/账户类型匹配）和 **AccountingEntries**——按动作类型（direct / hold / commit / cancel / revert / overdraft / block / unblock / crossLedger）分别指定借方、贷方的**会计科目编码（rubric）**。
- **Transaction Route（交易路由）**：把多个操作路由组合成一种业务交易类型；交易提交时按路由校验来源/目标账户是否合规。

## 记账逻辑与算法

- **业务账户与会计科目分离**：运营账户（客户钱包等）按业务建模，每次动作通过路由映射到会计科目的借贷，这样同一套运营数据可以产出标准会计分录（“双账本”思路）。
- **手续费引擎（Fee Package）**：每项费用有
  - `calculationModel`：`flatFee`（固定）、`percentual`（比例）、`maxBetweenTypes`（取固定与比例中较大者）；
  - `referenceAmount`：按原始金额或扣费后金额计算；
  - `priority`：多项费用的计算顺序；
  - `isDeductibleFrom`：从金额中扣除（净额到账）还是另外加收；
  - `creditAccount`：费用收入入哪个账户；`deferrable`：付款方余额不足时转为费用欠款；
  - 按分部/账户/金额区间筛选适用的费用包，并有“守恒”测试（拆分后总额不变）。
- **原子批量**：有序的全有或全无执行（直接与冻结两种），带限额、幂等与恢复语义。
- **跨账簿交易**：通过桥接路由，两侧分别记科目。

## 追溯与审计

- 每条操作保存前后余额 + 版本，可逐条回放；Tracer 有哈希链审计。
- 元数据（MongoDB）挂在所有实体上。

## 导入、分类与对账

无（专注账本与支付）。

## API 与扩展

- Huma 生成的 OpenAPI 3.1；路径级组织隔离；三个 RBAC 命名空间；CloudEvents 事件流；面向 AI Agent 的 `AGENTS.md` / `llms.txt` / `llms-full.txt` 文档体系。
- 错误码体系：编号化（0001+）+ 领域码，便于客户端与 AI 精确处理。

## 可借鉴

- [M1] **业务动作 → 会计科目映射路由**（按动作类型给出借贷科目）—— 让“记账员录的是业务、系统产出标准分录”。
- [M2] **手续费模型**：固定/比例/取大者 + 计算基数 + 优先级 + 内扣/外加 + 入账科目 —— 正好覆盖链动 3%（内含）、云猫 1.8%、Stripe 手续费、卡网加价等全部场景。
- [M3] 每条分录保存前后余额与版本（balance trail），`recorded_at` 不可回填。
- [M4] 组合/分部作为分析维度（对应我们的渠道、站点、项目）。
- [M5] 编号化错误码 + 面向 AI 的文档（llms.txt）。
- [M6] 拆分守恒测试（property/fuzz）。

## 不采用 / 风险

- Elastic License 2.0：只参考设计，不复制代码。
- 多数据库 + 消息队列的部署形态对小团队太重。
- 实体层级（组织/组合/分部）对单主体账本偏复杂，可简化为“维度标签”。

## 对新系统的启示

1. 引入“交易类型（业务模板）”：录入时只选业务类型（上游充值、账号购买、卡网收入……），由模板决定借贷科目与手续费规则。
2. 手续费规则独立建模（固定/比例/取大、内扣/外加、基数、优先级、生效期间、适用渠道/站点），交易记录保存“应用了哪条规则的哪个版本”。
3. 分录行保存账户余额快照（可选）以支持快速回放与审计核验。
4. 维度（渠道、站点/供应商、项目、成员）通用化为可配置的分析维度。
5. 错误码规范化，API 文档同时产出 `llms.txt`。
