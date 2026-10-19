# TNT-Likely/BeeCount-Cloud

- 分类：06 个人记账（BeeCount 自托管同步服务 + Web + MCP）
- 语言 / 许可证 / 最近提交：Python（FastAPI + SQLAlchemy + Alembic，SQLite/Postgres）+ React / **BSL** / 2026-10-18
- 审查范围：`src/{models,sync_applier,projection,snapshot_*,ledger_access,security,deps}.py`、`src/mcp/{server,auth,tools/read_tools,tools/write_tools}.py`、`src/routers/mcp_calls.py`

## 定位

为 BeeCount 移动端提供实时同步（WebSocket）与 Web 控制台，并内置 MCP 服务让 LLM 查询与记账。技术栈（FastAPI/SQLAlchemy/Alembic）与本项目旧系统接近，参考价值高。

## 数据与同步模型

- **变更日志 + 投影**：客户端提交实体级变更（带 `base_change_id`），服务端 `sync_applier` 应用到读模型投影（projection），冲突按**确定性最后写入胜（LWW）+ 设备号打破平局**；快照构建/缓存用于新设备全量同步；
- 实体：账本、交易（sync_id）、账户、分类、标签、预算、附件；多账本访问控制（ledger_access）。

## MCP 设计

- 读工具：`list_ledgers`、`get_active_ledger`、`list_transactions`、`get_transaction`、`list_categories`、`list_accounts`、`list_tags`、`list_budgets`、`get_ledger_stats`、`get_analytics_summary`、`search`；
- 写工具：`create_transaction(s)`（批量）、`update_transaction`、`delete_transaction`、`create_category`、`update_budget`、`upload_attachment`、**`parse_and_create_from_text`（把用户原话转给内置 AI 解析成草稿再创建）**；
- **MCP 写入自动打默认标签（如“MCP”）**，便于事后筛选 AI 写入的数据；
- **多账本时不猜测**：未指定账本则返回候选列表让 Agent 选择；名称（账户/分类/标签）存在性校验，不存在则报错而非静默新建；
- 写工具内部通过“自调用”REST 写接口实现，复用同一套校验与同步逻辑（MCP 不绕过业务层）；
- **MCP 调用日志表**（mcp_call_logs：用户、工具名、参数摘要、结果状态、耗时、时间），并提供查询接口（需 scope）；
- 令牌带 scope，依赖注入 `require_any_scopes(...)` 校验。

## 可借鉴

- [BCC1] MCP 写入自动加来源标签/字段，AI 写入可筛选、可批量撤回。
- [BCC2] 歧义（多账本、重名）时返回候选而不是猜。
- [BCC3] MCP 工具复用 REST 业务层（同一校验、同一审计）。
- [BCC4] MCP 调用日志 + 查询接口。
- [BCC5] 变更日志 + 投影 + 快照的同步架构（若未来需要多端实时）。

## 不采用 / 风险

- BSL；“AI 原话直接解析并创建”在会计场景风险较高，应改为“解析 → dry-run 预览 → 确认提交”。

## 对新系统的启示

1. 所有 MCP/API 写入自动记录 `source=mcp`、`client_id`、`batch_id`，并可按批次冲正；
2. 工具层薄、业务层厚：MCP → 应用服务（与 REST 共用）；
3. `mcp_call_logs` 表 + 管理端查询。
