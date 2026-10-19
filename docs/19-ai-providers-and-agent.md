# 19 AI 提供商、权限档位与站内 AI 助手

> 2026-10-19 起。设计依据见 18 号文档。接口以 16 号文档（由代码生成）为准。

## 1. AI 提供商（设置 → AI 模型）

| 项 | 说明 |
|---|---|
| 提供商 | 每个账套可加多个：名称、类型（`anthropic` / `openai_compatible`）、Base URL、API 密钥、模型列表、默认模型、超时、是否启用、能力开关、价格（可选，美元 / 百万 token） |
| 类型 | `anthropic` 用官方 `anthropic` SDK（Messages API）；`openai_compatible` 用官方 `openai` SDK 的 Chat Completions，适用于 OpenAI、自己的中转站与其他厂商 |
| 能力开关 | 图片、PDF、结构化输出、工具调用、服务端回退。不支持的由适配层降级：不读 PDF → 先用文字层，没有文字层再取页面图片；没有结构化输出 → JSON 模式 + 按 schema 校验 + 一次修复重试；没开服务端回退 → 不发 beta 请求头 |
| 任务分配 | 识别、AI 助手各自选“提供商 + 模型”，可设最多 5 个备用：第一个连不上（鉴权失败、限流、连接问题）自动换下一个；文件本身读不了不换 |
| 默认 | 一个都没分配时，识别仍使用环境变量 `BK_AI_API_KEY`（或 `ANTHROPIC_API_KEY`）、`BK_AI_MODEL`、`BK_AI_EFFORT` |
| 测试连接 | 发一次极小请求（回复 OK），并列出提供商的模型；显示延迟与已开的能力 |
| 用量 | 每次调用按提供商、模型、任务记 token 与费用估算（设了价格才有）；设置页显示近 30 天 |

### 1.1 密钥

- 用服务器主密钥 `BK_MASTER_KEY`（≥ 32 个字符）派生的 AES-256-GCM 密钥加密保存；没有主密钥时不能保存密钥。
- 密文绑定“提供商 + Base URL”：**修改 Base URL 必须重新填写密钥**（接口会拒绝），已存的密钥即使被取出也解不开给新地址用。
- 接口永不返回明文，只显示末 4 位；审计只记“密钥已设置 / 已更换”，不记内容；日志不记请求体。
- 更换 `BK_MASTER_KEY` 后，已存的密钥都要重新填写（识别会提示“密钥无法解开”）。

### 1.2 谁能改

- 查看：需要管理只读（`admin:read`，管理员与记账员角色都有），不含密钥。
- 修改（增删改提供商、测试连接、任务分配）：需要 `config:write`，**且只能在网页端**（登录会话）。API 令牌与 MCP，即使是管理员读写档位，也不能改提供商和密钥。
- 所有修改记审计。

### 1.3 接口

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/books/{b}/ai/status` | 识别、AI 助手是否可用（任何成员可读，不含配置） |
| GET / POST | `/books/{b}/ai/providers` | 列表 / 新增 |
| PATCH / DELETE | `/books/{b}/ai/providers/{id}` | 修改（`expected_version`；改 Base URL 时必须带 `api_key`）/ 删除（同时从任务分配中移除） |
| POST | `/books/{b}/ai/providers/{id}:test` | 测试连接 |
| GET / PUT | `/books/{b}/ai/routes` | 任务分配：`{extract: [{provider_id, model}], agent: [...]}` |
| GET | `/books/{b}/ai/usage?days=30` | 用量与费用估算 |
