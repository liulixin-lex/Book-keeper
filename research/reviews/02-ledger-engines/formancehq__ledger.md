# formancehq/ledger（Formance Ledger v3）

- 分类：02 账本引擎 / API-first
- 语言 / 许可证 / 最近提交：Go / MIT（核心）+ 企业版 / 2026-10-16
- 审查范围：`docs/technical/architecture/{overview,data-model}.md`、`openapi.yml`（51 个路径）、`internal/domain/accounttype`、revert/idempotency 文档

## 定位

面向金融科技的“可编程核心账本”。v3 是单 Raft 组 + 确定性状态机 + Pebble 存储的分布式账本，所有写入走审计链，读侧是可重建的投影。

## 数据模型

- **Ledger**：逻辑隔离的账簿，独立的 log 序号与 transaction 序号，内部用 uint32 ID，外部用名字。
- **Transaction** = 若干 **Posting**（`source`、`destination`、`amount: BigInt`、`asset`）+ metadata + `timestamp`（业务/生效时间）+ `inserted_at`（入账时间）+ `reference`（外部唯一号）+ `reverted` 标记。
- **账户地址**是冒号分层字符串（如 `users:001:wallet`），账户无需预先创建；`@world` 是可无限透支的外部世界账户，表示资金进出系统边界。
- **资产**带精度后缀（`USD/2`、`CNY/2`），金额一律整数（任意精度）——没有浮点、没有小数。
- **Volumes**：每个 (account, asset) 维护 `input`（累计流入）和 `output`（累计流出），余额 = input − output。比只存余额多一维信息，可直接得出发生额。
- **Account types（科目类型）**：用地址模式（带变量捕获，如 `users:{id}:wallet`）定义科目表，可设置强制模式（拒绝不匹配的地址）。
- **Metadata**：账户、交易、账簿三级 KV 元数据，并有 metadata-schema 约束类型。

## 记账逻辑与算法

- 一笔交易的每个 posting 是“从 A 到 B 转 N 个某资产”，天然借贷平衡（每条 posting 自平衡），不需要额外的平衡校验。
- **Numscript** DSL 表达复杂资金流：按比例拆分（`send [USD/2 100] (source = @a destination = { 3% to @fees remaining to @merchant })`）、多来源按顺序扣减、透支上限（`allowing overdraft up to`）、变量与账户元数据读取。脚本在准入阶段预编译，声明读写集合，状态机确定性执行。脚本库带语义化版本与使用统计。
- **透支控制**：默认非 `@world` 账户不能为负，需显式允许透支或设定上限——是防止错账的硬约束。
- **Revert**：生成一笔反向交易，原交易打 `reverted` 标记；可选 `atEffectiveDate`（按原生效日期冲回）；重复冲正返回 409。不修改历史。
- **双时间轴**：`timestamp`（生效时间，可回填过去）与 `inserted_at`（系统写入时间）分离；查询支持 PIT（某时点状态）与按生效时间/写入时间两种口径——这正是“补录历史账单”场景需要的。
- **批量**：`/bulk` 支持多操作，可选原子性。

## 追溯与审计

- 审计链是权威历史：每个提案（成功或确定性失败）都有审计条目，带序号、提案 ID、订单、结果；有签名密钥和完整性检查器（重放审计链校验投影）。
- 失败也入审计（区分“业务失败”与“可重试的技术中断”）。
- 读侧索引/投影都可从审计链重建。

## 导入、分类与对账

不提供导入、分类和对账（这些是 Formance 的其他产品：Payments、Reconciliation、Flows）。

## API 与扩展

- REST（`/v3/{ledger}/transactions|accounts|volumes|metadata|logs|bulk|numscripts|prepared-queries|account-types|indexes`）+ gRPC，OpenAPI 文档详尽，每个接口写明 scope（`ledger:write`、`ledger:MetadataWrite`）。
- **系统级幂等**：`Idempotency-Key` 头覆盖所有写操作；保存键→结果序号 + 输入内容哈希，同键不同内容判冲突。
- 事件 sink（推送提交事件到外部）、prepared queries（命名的参数化查询）、二级索引管理。
- 一致性读与 `X-Consistency: stale` 读可选。

## 可借鉴

- [F1] 金额 = 整数 + 资产精度后缀，绝不用浮点 —— 杜绝舍入误差。
- [F2] Posting 化的交易（每条腿自平衡）+ `@world` 边界账户 —— 模型最简且天然平衡。
- [F3] Volumes（累计流入/流出）而不仅是余额 —— 发生额报表免扫全表。
- [F4] 生效时间与入账时间分离 + PIT 查询 —— 支持补录、追溯任意时点余额。
- [F5] Revert 生成反向交易、原交易只打标记、可选按原生效日冲回 —— 历史不可变。
- [F6] 系统级幂等键 + 输入哈希冲突检测，覆盖所有写操作。
- [F7] 用地址模式定义科目类型 + 强制模式 —— 科目表约束可配置。
- [F8] 透支默认禁止 —— 余额护栏。
- [F9] 每个接口声明权限 scope；审计记录失败的写入。
- [F10] 可版本化的交易模板（Numscript 库）—— 手续费拆分等规则可复用、可追溯版本。

## 不采用 / 风险

- Raft 集群、Pebble、确定性 FSM —— 对单机小团队账本是过度设计。
- 账户无需预建、任意字符串地址 —— 记账场景需要显式科目表，否则错字即生成新账户（v3 用 account types 强制模式补救，新系统应默认强制）。
- 没有会计期间、报表、科目性质（资产/负债/损益）概念，需要上层补齐。

## 对新系统的启示

1. 核心层采用“交易 + 多条分录（腿）”模型，金额整数化，资产/币种带精度。
2. 引入生效日期（accounting_date）与写入时间（recorded_at）双时间轴，所有报表可指定口径与时点。
3. 冲正一律生成反向交易；编辑 = 冲正 + 新交易（保留链路）。
4. 写接口统一幂等键 + 请求哈希；批量接口支持原子/非原子两种模式。
5. 手续费拆分等规则做成“可版本化的过账模板”，交易记录引用模板版本。
6. 审计链覆盖成功与失败的写入；读模型可从事件重建。
