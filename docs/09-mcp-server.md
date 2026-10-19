# 09 MCP 服务设计（外部 AI 接入）

## 0. 当前实现（2026-10-19，精简后）

| 项目 | 实现 |
|---|---|
| 传输 | `POST /mcp`（Streamable HTTP，官方 Python SDK 低层 Server，无状态 + JSON 响应）；同时支持握手协议（2024-11-05 … 2025-11-25）与无状态协议 2026-07-28；`GET /mcp` 返回 405 |
| 认证 | `Authorization: Bearer bk_pat_…`，令牌须 `mcp_enabled = true`；令牌决定账套与权限；缺失 / 无效返回 401（带 `WWW-Authenticate`） |
| OAuth 2.1（`BK_OAUTH_ENABLED`） | 供 claude.ai、Claude 桌面 / 手机、ChatGPT 等只能用 OAuth 的远程连接器：401 的 `WWW-Authenticate` 带 `resource_metadata` → `/.well-known/oauth-protected-resource/mcp`（RFC 9728）→ `/.well-known/oauth-authorization-server`（RFC 8414）→ 动态注册 `/oauth/register`（RFC 7591，回调须 https 或本机回环，每 IP 每小时 20 次）→ `/oauth/authorize`（PKCE S256 必须）→ 登录与授权页 `/oauth/login`（选择账套与权限档位：用户只读 / 用户读写 / 管理员只读 / 管理员读写，不超过用户角色可创建的档位（默认用户读写））→ 回调带 `code`、`state`、`iss`（RFC 9207）→ `/oauth/token` 换取普通 API 令牌（`mcp_enabled`，30 天）与刷新令牌（180 天，每次使用轮换，旧刷新令牌重放则整条授权链吊销）→ `/oauth/revoke`（RFC 7009）。客户端密钥、授权码、刷新令牌均只存哈希 |
| 工具可见性 | 令牌 scope 覆盖工具所需 scope 才列出；`BK_MCP_WRITE_ENABLED=false` 时只列只读工具 |
| 工具（35 个） | 只读 17：`get_context`、`search_accounts`、`search_counterparties`、`get_reference`、`search_transactions`、`get_transaction`、`get_balances`、`run_report`、`query_ledger`、`explain_posting`、`evaluate_fee`、`run_checks`、`get_audit_trail`、`list_pending_work`、`export_ledger`、`search_source_records`、`get_import_batch`；交易 6：`create_transaction`、`create_transactions`、`update_transaction`、`delete_transaction`、`restore_transaction`、`repost_transactions`；导入与规则 9：`manage_import_source`、`import_records`、`classify_records`、`resolve_match`、`commit_import`、`revert_import`、`apply_rules`、`manage_rule`、`manage_pairing_rule`；配置 2：`upsert_reference`、`manage_fee_rule`；撤销 1：`undo_change_set`。完整参数见 16 号文档 |
| 写入选项 | 所有写工具支持 `dry_run`（执行后回滚，返回与真实写入相同的结果）与 `idempotency_key`（同键同参返回首次结果并标记 `idempotent_replayed`，同键异参 `IDEMPOTENCY_MISMATCH`） |
| 写入即生效 | 没有两段式预览（2026-10-19 去掉）；写错用 `undo_change_set` 或 `restore_transaction` 撤回，账本保留全部历史 |
| 信封 | `structuredContent` 与等价的 JSON 文本内容；`ok, code, message, data, warnings, next_action, meta{request_id, book_id, change_set_id, dry_run}`；错误另含 `retryable, errors[], candidates, details`，`isError = true` |
| 撤销 | `undo_change_set`：新记的删除、删除的恢复、修改与重算改回、导入撤销、手续费规则改动还原；其他事件列入 `manual` |
| 限流与日志 | 按令牌每分钟请求数（令牌配置，默认 120）与写入 30 次 / 分钟，数据库计数（多进程共享），超限 429 + `Retry-After`；每次调用写 `mcp_calls`（180 天），REST `GET mcp-calls` 查询 |
| 资源 | `ledger://context`、`accounts`、`transaction-types`、`fee-rules`、`channels`、`reports`、`work`、`guides/{posting,edits,fees,review}`；模板 `ledger://transactions/{ref}`、`ledger://accounts/{code}` |
| 提示词 | `record_transactions`、`monthly_review`、`fix_fee_rule`、`investigate_difference` |
| 测试 | 原始 JSON-RPC 用例覆盖可见性、试算、幂等、修改 / 删除 / 恢复、撤销、资源与提示词、限流与日志；官方 SDK 客户端分别以握手协议与 2026-07-28 协议完成往返 |

接入示例（Claude Code）：`claude mcp add --transport http bookkeeper https://bill.example.com/mcp --header "Authorization: Bearer $BK_TOKEN"`。

以下 §1–§10 为设计说明；与 §0 不一致处以 §0 与 16 号文档为准。

## 1. 目标与原则

让外部 AI（Claude、ChatGPT、本地 Agent 等）以**受控、可追溯、可撤回**的方式读取与编辑账本。

| 原则 | 落实 |
|---|---|
| 与 REST 同源 | 工具只调用应用层服务，校验、审计、错误码与 REST 完全一致 |
| 默认只读 | 令牌默认用户只读档位；全局 `BK_MCP_WRITE_ENABLED=false` 时不列出任何写工具 |
| 最小权限 | 有效权限 = 令牌 scope ∩ 用户角色；未授权的工具**不出现在工具列表中**，调用时再次校验 |
| 领域任务工具 | 按记账任务设计（记账、修改、删除与恢复、导入、分类、匹配、规则、统计），不做 REST 1:1 映射，不提供“执行任意操作”类工具 |
| 先试算再写入 | 所有写工具支持 `dry_run`；写入立即生效，可撤回 |
| 不猜测 | 名称解析有歧义时返回候选，要求 AI 向用户确认 |
| 可识别、可撤回 | AI 写入自动标记渠道 `mcp` 与客户端名称；每次写入返回 `change_set_id`，可整体撤销 |
| 结果可解释 | 返回解释链、警告、`next_action`；金额同时给整数与展示值 |
| 有据可查 | 每次调用写 `mcp_calls`，写入另有审计事件 |

## 2. 传输与接入

| 方式 | 地址 / 命令 | 认证 | 适用 |
|---|---|---|---|
| Streamable HTTP（主） | `https://bill.example.com/mcp` | `Authorization: Bearer bk_pat_…` | Claude Code、Cursor、自建 Agent |
| Streamable HTTP + OAuth 2.1（P2） | 同上 | 授权码 + PKCE，动态客户端注册，受保护资源元数据 | claude.ai / ChatGPT 等远程连接器 |
| stdio 代理（P2） | `bookkeeper-mcp --url https://bill.example.com --token-env BK_TOKEN` | 令牌来自环境变量 | 只支持 stdio 的客户端 |

示例（Claude Code）：

```bash
claude mcp add --transport http bookkeeper https://bill.example.com/mcp \
  --header "Authorization: Bearer $BK_TOKEN"
```

服务端实现：官方 Python SDK 的 FastMCP，以 ASGI 子应用挂载到主应用 `/mcp`；启用结构化输出（`outputSchema` + `structuredContent`，同时提供简短文本摘要）；nginx 对 `/mcp` 关闭响应缓冲以支持流式响应。

## 3. 服务端说明（instructions）

以代码为准（`mcp_api/content.py` 的 `INSTRUCTIONS`）。要点：先 `get_context`；金额用字符串小数写入、以 minor 读取；记账优先用业务类型，不确定先 `get_reference` 与 `dry_run`；不猜测往来方与科目；写入立即生效，`update_transaction` 可改任何字段，`delete_transaction` / `restore_transaction` 删除与恢复；出错读 `code` 与 `next_action`；写错用 `undo_change_set` 整次撤销；报表行的 `drilldown` 可直接用于 `search_transactions`。

## 4. 响应信封

```jsonc
{
  "ok": true,
  "code": "OK",                       // 或 DRY_RUN / 错误码
  "message": "已记账 T2026-000123 relay-b.example · 额度采购 · 面值 ¥50",
  "data": { },                        // 工具专属结构（见各工具输出 schema）
  "warnings": [ { "code": "FEE_DEVIATION", "message": "实际手续费 1.60 与规则计算 1.50 偏差 0.10", "path": "fees.channel_fee" } ],
  "next_action": null,
  "meta": { "request_id": "req_…", "book_id": "bk_…", "change_set_id": "chs_…" }
}
```

- 金额输出：`{"minor": 5150, "commodity": "CNY", "display": "¥51.50"}`；
- 列表默认 20 条、最多 100 条；`detail = summary`（默认）/ `full`；超出体积时 `truncated = true` 并给 `next_cursor`；
- 错误同样用信封：`ok = false`、`code`、`message`、`retryable`、`next_action`、`candidates`（歧义时）、`errors[]`（字段路径）；MCP 层面 `isError = true`。

## 5. 工具目录

图例：**R** 只读（readOnlyHint=true）；**W** 写（destructiveHint=false）；**H** 影响面大的写（destructiveHint=true：删除、按新规则重算、完成 / 撤销导入、撤销变更集）。所有工具 `openWorldHint=false`；输入 schema 一律 `additionalProperties: false`。参数以 16 号文档为准，下表只列用途。

### 5.1 上下文与基础数据（R）

| 工具 | 用途 |
|---|---|
| `get_context` | 账套、本位币、时区、今天、调用者 scope、待办统计、录入约定 |
| `search_accounts` | 科目（编码、名称、角色、可记账、余额） |
| `search_counterparties` | 往来方、别名、域名解析与候选 |
| `get_reference` | 交易类型（含输入 JSON Schema 与示例）、手续费规则、渠道、币种、汇率、标签、报表目录 |

### 5.2 查询与分析（R）

| 工具 | 用途 |
|---|---|
| `search_transactions` | 按文本、类型、日期、往来方、渠道、科目、币种、金额、估算、标签筛选；`status=reversed` 查已删除的 |
| `get_transaction` | 交易全貌：输入、计算值、全部分录（含修改与删除的冲销 / 重记）、来源、关联；`explain=true` 附解释链 |
| `get_balances` | 截至某日的科目余额（原币与本位币） |
| `run_report` | 概览、利润表、经营日报、销售分析、手续费分析、额度采购分析、试算平衡表 |
| `query_ledger` | 按任意维度汇总，每行带 `drilldown` |
| `explain_posting` | 已有交易或假设输入如何生成分录（手续费规则命中原因） |
| `evaluate_fee` | 手续费试算 |
| `run_checks`、`get_audit_trail`、`list_pending_work`、`export_ledger` | 健康检查、审计与变更集、待处理事项、导出存档 |
| `search_source_records`、`get_import_batch` | 导入记录与批次；每条记录带 `match`（已关联或可能重复的交易）与 `fee_rule`（手续费按实际 / 按哪条规则 / 无规则按 0） |

### 5.3 交易（W / H）

| 工具 | 类型 | 说明 |
|---|---|---|
| `create_transaction` / `create_transactions` | W | 记账（立即入账）；批量 ≤ 200 条，`atomic` 控制全有或逐条 |
| `update_transaction` | W | 修改任何字段，`inputs` 只给变化的键；影响账面时冲销重记，编号不变；`expected_version` 可选 |
| `delete_transaction` | H | 删除（冲销当前分录）；原因可选 |
| `restore_transaction` | W | 恢复已删除的交易 |
| `repost_transactions` | H | 手续费规则或汇率修正后按新规则重算；务必先 `dry_run` |
| `undo_change_set` | H | 撤销某次写入的全部结果 |

### 5.4 导入与规则（W / H）

| 工具 | 类型 | 说明 |
|---|---|---|
| `manage_import_source` | W | 新建 / 修改导入来源（解析配置、按方向的默认值、未分类策略） |
| `import_records` | W | 结构化记录或 base64 文件 → 待完成批次（去重、规则分类、匹配已记过的交易与配对；尚未入账）。截图请自己读成 `records` 提交；`ai_extract` 来源的文件只走网页 / REST 上传 |
| `classify_records` | W | 补全或忽略来源记录（人工设置的字段锁定） |
| `resolve_match` | W | 接受 / 拒绝匹配建议，或手工关联到已有交易；拒绝已自动关联的会解除关联并删除凭证关联，拒绝一条“可能已记过”会让该记录回到可入账 |
| `commit_import` / `revert_import` | H | 完成导入（已分类的入账）/ 撤销导入（删除其入账的交易） |
| `apply_rules`、`manage_rule`、`manage_pairing_rule` | W | 执行与维护分类规则、配对规则 |

### 5.5 配置（W）

| 工具 | 说明 |
|---|---|
| `upsert_reference` | 往来方、别名、子账户、渠道、币种、汇率 |
| `manage_fee_rule` | 手续费规则新版本 / 停用；返回 `repost_transactions` 的建议参数 |

### 5.6 工具与 REST 的对应

每个写工具在代码中声明对应的 REST `operationId`（如 `create_transaction → transactions_create`），供漂移测试使用；读工具可组合多个服务调用，不要求一一对应。

## 6. 档位（令牌决定可见工具）

`tools/list` 只列出当前令牌档位能用的工具（规范允许按授权变化，顺序固定）；调用不可用的工具一律返回 `FORBIDDEN_SCOPE`，结果里 `status: 403`，并附 `available` 列表。档位定义见 08 号 §3.3。

| 档位 | 可见工具 |
|---|---|
| 用户只读 `user_read` | 只读 18 个（含 `list_files`、`read_file`；不含 `get_audit_trail`、`get_admin_info`） |
| 用户读写 `user_write` | 只读 18 个 + 交易 6 个 + 导入（不含 `manage_rule`、`manage_pairing_rule`、`save_rule_from_record`）+ `upsert_reference` + `undo_change_set` + 工作区 `write_file`、`patch_file` |
| 管理员只读 `admin_read` | 只读 18 个 + `get_audit_trail` + `get_admin_info`（成员、令牌、规则、配对规则、手续费规则、AI 提供商与任务分配、账套设置；不含任何密钥），没有写工具 |
| 管理员读写 `admin_write` | 全部 41 个 |

文件工具（`list_files`、`read_file`、`write_file`、`patch_file`）与站内 AI 助手共用，见 19 号 §3.3：原件只读并带 SHA-256，派生内容写进工作区。

AI 提供商与密钥没有 MCP 写工具，管理员读写也改不了；`get_reference kind=fee_rules` 需要管理员只读，算某笔手续费用 `evaluate_fee`（任何档位）。

## 7. 资源与提示词

### 7.1 资源

`resources/list` 只列出当前档位能读的资源。

| URI | 内容 | 需要 |
|---|---|---|
| `ledger://context` | 同 `get_context`（含 `tool_groups`） | ledger:read |
| `ledger://accounts` | 科目表 | ledger:read |
| `ledger://transaction-types` | 交易类型、输入结构与示例 | ledger:read |
| `ledger://fee-rules` | 手续费规则 | admin:read |
| `ledger://channels` | 渠道 | ledger:read |
| `ledger://reports` | 报表目录 | ledger:read |
| `ledger://work` | 待处理事项 | ledger:read |
| `ledger://handbook` | 识别规则手册（当前版本与门槛）：读截图与账单的通用规则 | ledger:read |
| `ledger://playbooks` | 全部可用场景的步骤（与提示词同源，给不支持提示词的客户端） | ledger:read |
| `ledger://rules` | 规则快照：分类规则、配对规则、手续费规则、忽略规则、渠道与别名 | admin:read |
| `ledger://guides/{topic}` | 操作指南：`posting`、`edits`、`fees`、`review` | — |

资源模板：`ledger://transactions/{ref}`、`ledger://accounts/{code}`。

### 7.2 提示词 = 场景（与站内 AI 助手同源）

提示词由账套的场景数据生成（内置 `ai/playbooks.json`，账套可在 设置 → AI 规则 → 场景 修改或新增；19 号 §5）。每个场景写明适用条件、步骤、工具顺序、需要的作用域（按工具自动算出）与完成标准；`prompts/list` 只列出当前档位能完整执行的场景，`prompts/get` 把参数填进步骤。

| 名称 | 场景 | 参数 | 档位 |
|---|---|---|---|
| `import_screenshots` | 导入截图并入账 | `files?` | 用户读写起 |
| `monthly_review` | 月度经营分析 | `month` | 用户只读起 |
| `check_site_topups` | 核对某站点充值 | `site`、`period?` | 用户只读起 |
| `fix_and_save_rule` | 修正分类并存为规则 | `batch?` | 管理员读写 |
| `add_upstream_site` | 新增上游站点与手续费规则 | `site`、`channel?`、`rate?` | 管理员读写 |
| `undo_ai_run` | 撤销某次 AI 操作 | `hint?` | 管理员读写 |
| `record_transactions` | 用自然语言记账 | `description` | 用户读写起 |
| `fix_fee_rule` | 修正手续费规则 | `rule`、`rate`、`valid_from` | 管理员读写 |
| `investigate_difference` | 查找差异 | `target`、`expected` | 用户只读起 |

### 7.3 工具分组、示例与下一步

每个工具属于一个组（开始、查询与报表、记账、导入、规则与基础资料、文件、管理），写在 `tools/list` 的 `_meta["bookkeeper/group"]`；`get_context` 的 `tool_groups` 按组列出当前档位能用的工具与用途，客户端可只看相关的一组（渐进披露）。每个工具的说明末尾附一个可直接使用的调用示例与“下一步”（`mcp_api/hints.py`；测试逐个用工具的 schema 校验示例）。站内 AI 助手拿到的是同样的说明。

## 8. 安全控制

| 控制 | 说明 |
|---|---|
| 令牌 | 只存哈希；绑定单一账套与用户；`mcp_enabled` 必须为 true；可设过期、IP 白名单；吊销立即生效 |
| 写入总开关 | `BK_MCP_WRITE_ENABLED`；关闭时只列出 R 类工具 |
| 试算 | 所有写工具 `dry_run=true` 时执行后回滚，返回与真实写入相同的结果 |
| 幂等 | 写工具可传 `idempotency_key`；同键同参返回首次结果 |
| 并发 | 修改类工具可传 `expected_version`，不符时 `VERSION_CONFLICT` |
| 名称解析 | 支持用编码、名称、别名指代科目 / 往来方；唯一命中才使用，否则返回 `AMBIGUOUS_REFERENCE` 与候选 |
| 字段脱敏 | 往来方子账户标识、兑换码摘要以外的敏感值、令牌、密钥、Webhook 密钥一律不返回，`meta.redacted_fields` 列出被脱敏字段 |
| 原始文件 | 默认不通过 MCP 返回文件内容（需 `files:read` 且显式请求，单次 ≤ 1 MB 文本） |
| 限流 | 按令牌 120 次 / 分钟；写入类 30 次 / 分钟；超限返回 `RATE_LIMITED` 与重试时间；服务端从不自动重试写入 |
| 来源标记 | MCP 写入的交易 `created_channel = mcp`、`mcp_client = <客户端名称/版本>`；字段来源记为 `mcp:<token_id>`；可在 API 中筛选 `created_channel:mcp` |
| 撤回 | 每次写入返回 `change_set_id`；`undo_change_set` 撤销（新记的删除、删除的恢复、修改改回、导入撤销）；账本只追加，撤销本身也可再撤销 |
| 日志 | `mcp_calls` 记录令牌、客户端、工具、脱敏参数与摘要、结果码、耗时、变更集；保留 180 天 |

## 9. 典型流程

**A. 用自然语言记一笔采购**
`get_context` → `search_counterparties {query: "relay-b"}`（唯一命中 relay-b.example）→ `get_reference {kind: "transaction_type", code: "credit_purchase"}` → `create_transaction {…, dry_run: true}`（上游额度 50.00、手续费 1.50、资金账户 −51.50）→ 去掉 `dry_run` 记账，回执“已记账 T2026-…”。

**B. 导入账单**
`import_records` → 安全校验、重复、匹配、规则分类、未识别数量 → `search_source_records {status: "new"}` → 与用户确认后 `classify_records` → `commit_import` → `list_pending_work` 汇报剩余。

**C. 手续费率追溯修正**
`manage_fee_rule`（新版本，自 2026-10-01 起）→ `repost_transactions {types: ["sale"], dry_run: true}`（逐笔旧 / 新手续费与差额）→ 用户确认后执行。

**D. 改错与撤回**
金额录错：`update_transaction {ref, inputs: {gross: …}}`（同一编号，冲销重记）；重复录入：`delete_transaction`；AI 整次写错：`get_audit_trail {channel: "mcp"}` 找到变更集 → `undo_change_set`。

## 10. 测试与评估

| 类别 | 内容 |
|---|---|
| 工具清单快照 | 工具列表、输入 / 输出 schema 快照纳入版本库，变更需评审 |
| schema 严格性 | 未知参数、错误类型、浮点金额均被拒绝 |
| 权限矩阵 | 四档 × 每个工具：`tools/list` 恰好列出可用工具，其余调用返回 `FORBIDDEN_SCOPE`（403）；写入总开关关闭时写工具不可见（`test_permission_matrix.py`） |
| 功能测试 | 用 SDK 客户端对每个工具跑成功 / 失败路径，校验信封、警告、`next_action` |
| 漂移测试 | 写工具与对应 REST `operationId` 的参数字段、错误码、结果一致 |
| 撤回 | 各类变更集撤销后账本恢复（报表指纹回到撤销前的值，审计保留全过程） |
| 场景回放 | 以脚本化的工具调用序列重现 §9 流程，断言最终账本状态（不依赖任何大模型） |
| 人工评估（开发期可选） | 用外部 AI 客户端按清单执行典型任务，记录工具误用与说明不足之处，改进工具描述；不进入产品 |
