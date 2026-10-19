# henfrydls/actual-budget-mcp

- 分类：08 MCP / 外部 AI 接入（Actual Budget）
- 语言 / 许可证 / 最近提交：TypeScript（@actual-app/api）/ MIT / 2026-10-18
- 审查范围：`README.md`（工具清单、Safety 章节）、`src/`

## 定位

把 Actual Budget 接到 Claude 等客户端：既有查询，也有“分析型”工具和安全写入。

## 工具设计（约 45 个）

- **分析型工具**而非只查询：`get_budget_summary`、`budget_vs_actual`、`spending_projection`（月末预测）、`category_trends`、`spending_by_category`、`monthly_summary`、`balance_history`、**`reconcile_account`（给出银行余额，解释差额来自哪里）**；
- 写工具：`create_transaction(s)`（**批量全有或全无**）、`create_split_transaction`、`update_transaction`、`recategorize_transaction`、`create_transfer`、**`reconcile_currency_residual`（清理外币汇率残差）**、规则/分类/收款方/账户 CRUD、`repair_sync`（修复同步状态）；
- **用名称而非 ID**（“Cartera” 而非 UUID），歧义时给出候选建议；支持自然语言日期（英/西：“last month”“hace 3 meses”）；
- 输出为对齐的表格与摘要，而非原始 JSON；错误信息说明“该怎么修”。

## 安全机制（重点）

1. **删除两步走**：第一次调用只返回预览（受影响的交易、预算、结转警告），不删除；第二次带 `confirm: true` 才执行；按名称定位的删除还要求 `confirm_name` 与目标名称完全一致（防止“Adicionales”误匹配到“Ingresos Adicionales”）；预览必须覆盖所有将被删除的行；不存在的 ID 直接拒绝而不是报“已删除”；
2. **创建前查重**：账户 + 日期 + 金额都相同的交易已存在时不创建，返回已有记录；
3. **只读模式**：`ACTUAL_READ_ONLY=1` 时写工具对模型完全不可见。

## 可借鉴

- [AB-1] 破坏性操作“先预览、再确认”，按名称定位时要求回显确切名称。
- [AB-2] 创建前查重并返回已存在记录。
- [AB-3] 只读模式隐藏写工具。
- [AB-4] 分析型工具（预测、趋势、预算对比、余额差额解释）。
- [AB-5] 名称解析 + 歧义候选；自然语言日期。

## 不采用 / 风险

- 表格化文本输出不利于程序消费（应同时返回结构化数据）。

## 对新系统的启示

- 冲正/删除类 MCP 工具一律两段式（`preview` → `confirm` + 回显关键字段）；
- `create_*` 默认查重（同来源外部 ID 或同账户+日期+金额+对手）；
- 提供 `explain_balance_gap(account, expected_balance, as_of)` 工具；
- Token 级只读模式：写工具不出现在 tools/list。
