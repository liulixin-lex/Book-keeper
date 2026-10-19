# stripe/ai（Stripe Agent Toolkit + MCP + Skills）

- 分类：08 MCP / 外部 AI 接入
- 语言 / 许可证 / 最近提交：TypeScript / Python / MIT / 2026-10-18
- 审查范围：`tools/modelcontextprotocol/README.md`、`tools/typescript/src/shared/{toolkit-core,configuration,mcp-client}.ts`、`tools/typescript/src/{openai,langchain,ai-sdk}`、`skills/`、`benchmarks/`、`providers/{claude,codex,cursor,grok}`

## 定位

Stripe 的 AI 接入全家桶：托管的远程 MCP（mcp.stripe.com）、本地 MCP（npx）、各 Agent 框架适配器（OpenAI Agents、LangChain、Vercel AI SDK）、Agent Skills、编辑器/Agent 插件，以及评测基准。

## 设计要点

- **权限交给受限 API Key（RAK）**：MCP 能调用哪些工具由所用 Key 的权限决定，而不是在 MCP 里另做一套权限；
- **上下文（Context）**：可固定 Connected Account、Customer，所有请求都在该范围内执行（多租户/代客操作的范围绑定）；请求带 MCP 模式标记头，便于服务端识别来源；
- **单一工具源**：Toolkit 从远程 MCP 拉取工具定义，再转换成各框架格式（避免多处维护工具定义）；
- **远程 MCP + OAuth**（Gemini CLI 等通过 `/mcp auth` 走 OAuth）；本地模式用 API Key；
- **文档即工具**：`search_stripe_documentation` 工具 + “任何文档 URL 加 .md 得到 LLM 可读版本”；
- **Agent Skills**：最佳实践技能（stripe-best-practices、stripe-docs…）随仓库同步；
- **基准测试（benchmarks）**：为 Agent 设计可复现的任务环境 + 评分器（发票、订阅等场景），衡量 Agent 使用工具的正确率。

## 可借鉴

- [ST-1] MCP 权限 = 调用凭证（API Key/OAuth token）的权限，单一权限模型。
- [ST-2] 连接级上下文绑定（固定账簿/主体），所有调用自动限定范围。
- [ST-3] 工具定义单一来源，自动导出到多种 Agent 框架。
- [ST-4] 文档检索工具 + LLM 可读文档（.md）。
- [ST-5] Agent 任务基准与评分器。
- [ST-6] 请求头标记来源（MCP/toolkit），服务端可审计。

## 不采用 / 风险

- 支付操作类工具与本项目无关。

## 对新系统的启示

1. MCP 不另设权限：复用 API Token 的 scope；
2. MCP 请求在审计中标记 `channel=mcp` 与 `client_name`；
3. 提供 `docs.search` 工具与 `/docs/*.md`（记账规则、交易类型说明）供 AI 自查；
4. 建立“记账 Agent 基准”：给定样例账单 → 期望分录/报表，回归评估 MCP 工具设计与提示词。
