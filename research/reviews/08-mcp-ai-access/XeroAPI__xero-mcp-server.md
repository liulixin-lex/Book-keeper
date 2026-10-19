# XeroAPI/xero-mcp-server（Xero 官方 MCP）

- 分类：08 MCP / 外部 AI 接入
- 语言 / 许可证 / 最近提交：TypeScript (MCP SDK + xero-node) / MIT / 2026-06
- 审查范围：`src/tools/{list,get,create,update,delete}/*`、`src/tools/tool-factory.ts`、`src/helpers/{create-xero-tool,get-deeplink}.ts`、`src/clients/xero-client.ts`、README

## 定位

Xero 官方 MCP 服务：把 Xero 会计 API 的常用对象以工具形式提供给 AI（会计对象 CRUD + 报表）。

## 工具设计

- **按动词分目录**：list（科目、联系人、发票、付款、银行交易、手工日记账、税率、跟踪类别、报价、试算平衡表、资产负债表、利润表、应收/应付账龄…）、get、create、update、delete，共约 50 个；
- 命名为 `动词-对象`（`create-manual-journal`、`list-trial-balance`）；参数用 zod 声明并逐字段 `describe`；
- **工具描述里写业务约束与前置步骤**：如 create-manual-journal 描述写明“先获取科目代码列表；至少两行；未指定时按基本科目类型配对；借贷必须平衡”，金额约定“借为正、贷为负”；
- 写入默认 **DRAFT（草稿）**状态，可显式指定 POSTED；支持 `url` 字段挂原始单据链接；
- 返回内容为人类可读文本 + **深链接（deep link）**直达 Xero 界面中的该对象，方便人工核对；
- 错误统一转换为文本返回（不抛出协议错误）。

## 认证

- 两种模式：Custom Connection（client_credentials + 按创建时间区分的 scope 集合，从“打包权限”迁移到“细粒度权限”）或直接提供 Bearer Token；
- scope 列表在代码中显式维护。

## 可借鉴

- [XR-1] 工具按 CRUD 动词组织，命名统一；报表类工具独立。
- [XR-2] 描述中写清前置调用（先查科目）与会计约束（借贷平衡、金额符号）。
- [XR-3] 写入默认草稿；返回深链接供人核对。
- [XR-4] 细粒度 scope。

## 不采用 / 风险

- 工具基本是 API 的一对一映射，缺少任务级工具与 dry-run；返回纯文本，不利于程序消费（新系统应返回结构化 JSON + 简短文本）。

## 对新系统的启示

- 工具命名 `verb_object`，按领域分组；描述 ≤ 2–3 句，写前置步骤与约束；
- 写工具返回 `{ok, data, links:{web_url}, warnings, next_actions}`；
- 用户已去掉审批：写入可直接过账，但支持 `dry_run`（预览）与“草稿”两种保守路径，由 Token 权限决定能否直接过账。
