# actualbudget/actual

- 分类：06 个人财务（本地优先预算）
- 语言 / 许可证 / 最近提交：TypeScript（React + Node，SQLite，本地优先 + 同步服务器）/ MIT / 2026-10-18（近 3 万星）
- 审查范围：`packages/loot-core/src/server/{rules,transactions,accounts/sync.ts,schedules,aql,undo.ts}`、`packages/crdt`、`packages/api`

## 定位

零基预算（envelope）个人财务应用：每台设备本地 SQLite，所有修改以 CRDT 消息同步；银行同步导入 + 强大的规则系统。

## 数据模型

- accounts / transactions（单式：账户 + 金额（整数分）+ 收付款方 + 分类 + 备注 + cleared/reconciled + imported_id + 父子拆分）/ payees / categories / rules / schedules；
- **同步**：每次字段级修改生成消息（表、行、列、值、HLC 混合逻辑时钟时间戳），服务器按时间戳合并，Merkle trie 校验差异——离线多端修改可确定性合并；
- 撤销/重做：基于消息的 undo 栈。

## 记账逻辑与算法

- **规则系统**：
  - 条件操作符 is / isNot / oneOf / notOneOf / **isapprox（金额约等）** / isbetween / gt/gte/lt/lte / contains / matches（正则）/ hasTags……；
  - 动作：设字段、追加/前置备注、**拆分（按固定额/百分比/剩余）**、Handlebars 模板与公式（如引用 balanceOf）；
  - **分阶段执行**：pre（清洗，如收付款方改名）→ normal → post；**同阶段内按“特异性分数”自动排序**（is=10 > oneOf=9 > isapprox/isbetween=5 > 比较=1 > contains/正则=0，全部是精确条件时额外加权）——越具体的规则越后执行以覆盖通用规则；
  - 用户手工修改收付款方/分类时可自动生成或更新规则（“学习”）。
- **银行同步导入匹配（matchTransactions）**：
  1. 先跑规则（导入数据先被规范化）；
  2. 用 `imported_id`（银行唯一号）精确匹配已有交易——最高可信度；
  3. 否则模糊匹配：**同账户、同金额、日期 ±7 天**的已有交易（手工录入的），按日期距离排序，同距离时优先选择尚无 imported_id 的候选（避免覆盖已导入记录）；
  4. 匹配成功则合并（保留用户的分类/备注，补齐 imported_id 与 cleared），否则新建；已核对（reconciled）的交易不被修改；
  5. 支持“预览”与“强制新增”。
- **计划交易（schedules）**：周期 + 金额（可“约等于”）+ 日期容差，自动匹配到实际交易并标记完成。
- 对账：输入银行余额，勾选 cleared，锁定为 reconciled。

## 可借鉴

- [AT1] 规则分阶段（pre/normal/post）+ 按特异性自动排序 —— 解决规则冲突与顺序依赖。
- [AT2] `isapprox`、`isbetween` 金额条件；拆分动作（固定/百分比/剩余）。
- [AT3] 导入匹配：外部唯一号精确匹配 → 金额+日期窗口模糊匹配 → 合并而不覆盖人工字段；已核对记录受保护。
- [AT4] 从人工修改中学习生成规则。
- [AT5] 计划交易的容差匹配（金额约等、日期窗口）。
- [AT6] 字段级变更消息 + HLC 时钟（如需离线/多端）。

## 不采用 / 风险

- 单式记账；本地优先 CRDT 对服务端账本不必要。

## 对新系统的启示

1. 规则引擎采纳“阶段 + 特异性排序 + 显式优先级覆盖”；
2. 导入去重/匹配三步：external_id → 模糊（金额、时间窗、对手）→ 新建；合并时人工字段优先；已锁定/已核对数据不可被导入覆盖；
3. 人工修正生成规则建议（不自动生效，需确认）。
