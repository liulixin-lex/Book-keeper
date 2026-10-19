# norman-finance/norman-mcp-server

- 分类：08 MCP（商用记账 SaaS 官方 MCP，领域化工具最完整）
- 语言 / 许可证 / 最近提交：Python (FastMCP) / MIT / 2026-10-16（活跃）
- 审查范围：`norman_mcp/{server,bookkeeping_context}.py`、`tools/{transactions,rules,missing_documents,workflows}.py`、`events/`、`skills/*/SKILL.md`

## 定位

德国/波兰小企业记账服务 Norman 的官方 MCP：交易、分类、发票、票据、规则、税务、工资、DATEV 导出、流程。支持 stdio / SSE / streamable-http，OAuth 登录；有白标模式（`tool_filter` 只暴露部分工具）。

## 设计要点

- **领域化工具**（不是 1:1 API）：`search_transactions`、`categorize_transaction`、`change_transaction_verification`（核验状态）、`link_transaction`（付款 ↔ 发票，支持部分金额）、`missing_document_transactions`（缺票据的交易）、`upload_bulk_attachments`、`link_attachment_transaction`……
- **工具注解齐全**：读工具 readOnly + idempotent；删除工具 destructive，描述中写明“删除前须用户确认，优先停用”；
- **规则预演**：`preview_rule` 用条件对近期交易做 dry-run，返回样例匹配，引导用户确认后再 `create_rule`；规则按优先级执行，首个命中生效，附带命中次数统计；
- **拆分校验**：拆分明细合计与总额不一致（超过每行容差）直接报错，并提示“重新阅读单据修正完整拆分”——错误信息里写明下一步；
- **公司上下文资源**：把公司国家、记账币种、科目表、税号、行业等生成一段上下文文本，并按国家附加记账提示（如“业务日期与付款日期不同”“保留原始单据币种”）；
- **业务错误语义**：如 `automation_limit_reached` 明确告诉模型“不是临时错误，不要重试”，并给出替代方案；
- **Skills（工作流剧本）**：monthly-reconciliation 等 16 个 SKILL.md，把“月结”拆成 交易复核 → 核验 → 发票核销 → 票据检查 → 税务预览 → 汇总，并标出需要用户确认的步骤；
- events / webhooks：事件存储与推送；observability：调用追踪。

## 可借鉴

- [NM-1] 领域任务级工具，命名用业务动词（categorize / verify / link / find_missing_documents）。
- [NM-2] 规则 dry-run 预览 + 首个命中 + 命中统计。
- [NM-3] 错误分类：不可重试的业务错误明确说明，并给出下一步。
- [NM-4] 账套上下文 Resource（本位币、科目表、业务约定）供模型首先读取。
- [NM-5] 工作流剧本（Skills / Prompts）：月结、对账、补票据，标出需人工确认的节点。
- [NM-6] `tool_filter`：同一代码按部署暴露不同工具子集（预设）。
- [NM-7] 交易“核验（verified）”状态作为月结前置条件；缺票据交易清单。

## 不采用 / 风险

- 依赖商业 SaaS 后端；税务功能限于德国/波兰。

## 对新系统的启示

1. MCP 工具按任务分组：查询类、录入类（草稿 / 过账）、导入与分类、核销对账、期间与报表、管理；
2. `ledger://context` 资源：本位币、科目表摘要、交易类型与模板清单、手续费规则、当前开放期间、必填维度；
3. Prompts：`month_end_close`、`reconcile_account`、`import_statement`、`fix_unbalanced`；
4. 错误码附 `retryable` 与 `next_action`；
5. 交易 `review_status`（unreviewed / reviewed）与缺凭证清单作为期间关闭检查项。
