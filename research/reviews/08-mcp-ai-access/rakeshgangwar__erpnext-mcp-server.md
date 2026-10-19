# rakeshgangwar/erpnext-mcp-server

- 分类：08 MCP（ERP 通用 CRUD 透传）
- 语言 / 许可证 / 最近提交：TypeScript (MCP SDK, axios) / MIT / 2026-04
- 审查范围：`src/index.ts`（单文件约 1000 行）、README

## 定位

把 Frappe/ERPNext REST API 1:1 映射成 MCP 工具：get_doctypes、get_doctype_fields、get_documents（过滤/字段/分页）、get_document、create/update/delete_document、**submit_document / cancel_document**（单据生命周期 docstatus 0→1→2）、run_report、call_method（任意白名单方法）。

## 设计要点

- **Resources**：`erpnext://DocTypes` 列出全部单据类型；**资源模板** `erpnext://{doctype}/{name}` 按类型与名称读取单据；
- 工具描述中写明生命周期约束（已提交单据只能取消，取消后需修订），引导模型按正确顺序操作；
- `verbose` 参数：默认只返回最小确认信息，需要时才返回完整单据（节省上下文）；
- `get_doctype_fields`：先取 schema 再写入。

## 可借鉴

- [EM-1] 资源模板 `scheme://{type}/{id}` 统一按 ID 读取实体。
- [EM-2] 默认精简返回 + `verbose` 开关，控制 token 消耗。
- [EM-3] 在工具描述中说明状态机约束（草稿 → 过账 → 冲正）。

## 不采用 / 风险（反面教材）

- `call_method`、`delete_document` 等能力过宽，没有只读模式、dry-run、确认或审计；1:1 API 映射让模型直接面对底层复杂度。

## 对新系统的启示

1. 提供资源模板：`ledger://transactions/{id}`、`ledger://accounts/{code}`、`ledger://imports/{batch_id}`、`ledger://reports/{name}?params`；
2. 列表/读取工具统一 `detail=summary|full`；
3. 不暴露通用“执行任意方法 / 删除”工具；删除只用于草稿，已过账只能冲正。
