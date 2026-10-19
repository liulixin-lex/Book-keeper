# etnperlong/firefly-iii-mcp

- 分类：08 MCP / 外部 AI 接入（Firefly III）
- 语言 / 许可证 / 最近提交：TypeScript（Turborepo：core / local / server / cloudflare-worker）/ MIT / 2025-06
- 审查范围：`README.md`、`packages/core/src/{tools,presets,server}.ts`、`packages/core/scripts/generate-tools.ts`

## 定位

为 Firefly III 生成 MCP 工具：**由 Firefly 的 OpenAPI 规范自动生成**全部工具（tools.ts 约 1.2 万行），并通过“预设/标签”过滤暴露哪些工具；支持本地 stdio、Express（Streamable HTTP + SSE）与 Cloudflare Workers 部署。

## 设计要点

- **OpenAPI → MCP 工具自动生成**（`toolgen` 脚本，openapi-schema-to-json-schema 转换参数），API 变化时重新生成；
- **按标签分组 + 预设**：28 个 API 标签（accounts、transactions、budgets、rules、search、insight…）；预设 `default / full / basic / budget / reporting / admin / automation`，或自定义标签列表——**减少 tools/list 的 token 消耗**；
- 凭证通过请求头传递（`X-Firefly-III-Url` + `Authorization: Bearer PAT`），不推荐放在查询参数（会被日志记录）。

## 可借鉴

- [FM-1] 从 OpenAPI 自动生成 MCP 工具，保证与 REST 一致。
- [FM-2] 工具按领域标签分组，提供“预设工具集”控制暴露范围与上下文体积。
- [FM-3] 凭证放请求头而非 URL。

## 不采用 / 风险

- 自动生成的工具是低层 API 映射，数量多且语义弱，Agent 易误用；需要叠加手写的任务级工具。

## 对新系统的启示

- 两层 MCP：①手写任务级工具（推荐默认集）；②可选的“API 直通工具集”（由 OpenAPI 生成，按标签预设开启）供高级客户端使用；
- Token 可配置“工具集预设”（read_basic / bookkeeping / reconciliation / admin）。
