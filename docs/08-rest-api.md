# 08 REST API 规范

## 1. 基本约定

| 项 | 约定 |
|---|---|
| 基础路径 | `https://bill.example.com/api/v1`；账套资源 `/books/{book_id}/…` |
| 格式 | JSON（UTF-8），字段 snake_case；时间 ISO 8601 带偏移；日期 `YYYY-MM-DD` |
| ID | 带类型前缀的 ULID（`txn_01J…`）；路径中的人类编号用 `by-number/{number}` |
| 金额 | 对象 `{"amount_minor": 5150, "commodity": "CNY", "display": "51.50"}`；写入时也接受 `{"amount": "51.50", "commodity": "CNY"}`（字符串小数），**不接受数字类型的小数** |
| 成功响应 | `{"data": …, "meta": {…}, "warnings": [ … ], "links": {…}}` |
| 错误响应 | `application/problem+json`（RFC 9457），见 §7 |
| 文档 | `GET /api/v1/openapi.json`（OpenAPI 3.1，自动生成）；`operationId` 稳定，作为 MCP 漂移测试的锚点 |
| 版本 | 新增字段与接口不破坏兼容；破坏性变更只在 `/api/v2` 发布；废弃接口返回 `Deprecation` 与 `Sunset` 头 |

## 2. 认证

| 方式 | 用途 | 说明 |
|---|---|---|
| 会话 Cookie | 前端 | `POST /auth/login` 签发；HttpOnly、Secure、SameSite=Lax；写请求需 `X-CSRF-Token` |
| Bearer 个人访问令牌 | 脚本、外部系统、MCP | `Authorization: Bearer bk_pat_…`；绑定账套与用户；只存哈希 |
| OAuth 2.1 访问令牌 | 远程 MCP 客户端（P2） | 授权码 + PKCE（S256）；`/.well-known/oauth-authorization-server`、`/.well-known/oauth-protected-resource`；动态客户端注册 `POST /oauth/register`；令牌受众绑定 `resource = https://bill.example.com/mcp` |

令牌不得放在 URL 查询参数中。

## 3. 权限

### 3.1 作用域

| scope | 允许 |
|---|---|
| `ledger:read` | 读取全部业务数据（不含原始文件内容与密钥类配置） |
| `files:read` | 下载原始文件 |
| `ledger:write` | 记账、修改、删除、恢复交易；按新规则重算；撤销变更集；附件与标签 |
| `import:write` | 上传、解析、完成 / 撤销导入；分类、忽略来源记录；处理匹配建议 |
| `rules:write` | 管理与执行规则、配对规则 |
| `reference:write` | 往来方、别名、子账户、维度值、标签 |
| `config:write` | 科目、交易类型、手续费规则、商品、价格规则、手工汇率、来源 |
| `admin` | 成员、令牌、备份、账套设置 |
| `admin:read` | 只读查看管理信息：成员、令牌列表（不含密钥）、审计日志、MCP 调用记录、规则与手续费规则、AI 提供商与任务分配（不含密钥）、账套设置（2026-10-19 新增） |

2026-10-19 起 `ledger:draft` / `ledger:post` / `ledger:correct` 合并为 `ledger:write`，`periods:manage`、`reconcile:write` 取消（17 号文档）。

### 3.2 角色与作用域上限

| 角色 | 作用域上限 |
|---|---|
| viewer | ledger:read, files:read |
| accountant | viewer + ledger:write, import:write, rules:write, reference:write, admin:read |
| admin | accountant + config:write, admin |
| owner | admin + 账套转移 / 归档 |

网页登录会话的权限 = 角色上限。令牌（API、MCP、OAuth）与站内 AI 助手用下面的四个档位。

### 3.3 令牌权限：四个档位

2026-10-19 起令牌只有四个档位，不再逐项勾选作用域。档位到作用域的映射只写在 `domain/scopes.py` 的 `TIER_SCOPES`，REST、MCP 与站内 AI 助手共用。

| 档位 | 代码 | 能做什么 | 作用域 |
|---|---|---|---|
| 用户只读 | `user_read`（默认） | 查看账本、统计、导入批次与记录、自己用户上传的文件 | ledger:read, files:read |
| 用户读写 | `user_write` | 另可记账、修改、删除、恢复、导入、匹配决策、往来方 / 渠道等基础资料；所有写入可撤销 | + ledger:write, import:write, reference:write |
| 管理员只读 | `admin_read` | 另可查看管理信息（见 `admin:read`）；不能写 | user_read + admin:read |
| 管理员读写 | `admin_write` | 全部权限 | 全部 |

- **创建上限**：viewer 只能创建用户只读；accountant 可创建用户只读、用户读写；admin / owner 四档都能创建。`GET /books/{id}` 的 `token_tiers` 列出调用者可选的档位，`scopes` 是调用者在该账套的权限。用令牌创建、吊销、轮换令牌需要管理员读写档位。
- **角色降级**：令牌按“当前角色允许的、不超过原档位的最高一档”生效（如管理员读写 → 记账员角色下按用户读写）。列表里的 `effective_tier` 显示降级后的档位。
- **文件**：用户档位的令牌只能读自己用户上传的文件（含自己导出的文件）；管理员档位可读账套全部文件。
- **AI 提供商与密钥**：只能在网页端修改，任何档位的令牌（含 MCP）都返回 403；管理员只读可以查看（不含密钥）。
- **检查顺序**：每个账套接口所需的作用域登记在 `api/permissions.py` 的一张表里（16 号文档的“权限”列由它生成，以它为准），认证后、校验请求体之前检查，缺权限一律 403（不会先返回 422）；表里没有登记的账套接口直接拒绝。`tests/api/test_permission_matrix.py` 对四档 × 每个 REST 接口、每个 MCP 工具逐一断言（允许 / 403），并核对表与实际路由一致。
- **旧令牌**（迁移 0014）：reader → 用户只读，bookkeeper → 用户读写，admin → 管理员读写；自定义令牌映射到其作用域覆盖的最高一档（没有 ledger:read 的直接吊销），迁移时打印报告。

## 4. 写入语义

### 4.1 幂等
- 所有 `POST` / `PATCH` / `DELETE` 必须带 `Idempotency-Key`（1–128 字符，`[A-Za-z0-9_.:-]`），缺失返回 400 `IDEMPOTENCY_KEY_REQUIRED`（登录除外）；
- 作用域：账套 × 操作者；请求哈希 = SHA-256(方法 + 路径 + 规范化请求体)；保存 30 天；
- 同键同内容：返回首次响应，带头 `Idempotent-Replayed: true`；同键不同内容：409 `IDEMPOTENCY_MISMATCH`；首次请求仍在处理：409 `IDEMPOTENCY_IN_PROGRESS`（可重试）。

### 4.2 乐观并发
- 可变实体 `GET` 返回 `ETag: "v{version}"`；`PATCH` / 状态变更需 `If-Match` 或请求体 `expected_version`；
- 不一致 → 409 `VERSION_CONFLICT`，响应体附当前实体。

### 4.3 dry-run
所有写接口支持 `?dry_run=true`：执行完整计算与校验，返回将产生的结果（如分录行、余额影响、警告、解释链），不写入、不消耗幂等键。

### 4.4 直接生效与撤回
写入立即生效，不再有两段式预览（2026-10-19 去掉）。需要先看结果时用 `?dry_run=true`；写错了用回执中的 `meta.change_set_id` 调 `POST /books/{b}/change-sets/{id}:undo`，或对单笔交易 `:restore`。

### 4.5 批量
`POST /books/{b}/transactions:batch`，`atomic = true`（默认，全部成功或全部失败，错误含 `index` 与“第 N 条”）或 `false`（逐条保存点，返回每条的成功摘要或错误）；单批 ≤ 200 条。

### 4.6 重复处理
创建交易时 `on_duplicate = error`（默认）/ `skip`（返回已存在的交易）/ `allow`（仅允许越过模糊疑似重复，不能越过 `external_ref` 唯一约束）。

### 4.7 写入回执
每个写响应的 `meta` 含：`request_id`、`change_set_id`（撤销用）；交易类写入的 `data` 是交易全貌，含 `entries`（全部分录与凭证号）与 `warnings`。

## 5. 列表与查询

| 参数 | 说明 |
|---|---|
| `limit` | 1–200，默认 50 |
| `cursor` | 不透明游标；响应 `meta.next_cursor`、`meta.has_more` |
| `q` | 文本查询语法（见 06 号文档 §6.1） |
| `filter` | JSON 条件 AST（URL 编码），与 `q` 二选一 |
| `sort` | 如 `-effective_date,number` |
| `fields` | 稀疏字段 |
| `include` | 关联展开，如 `lines,sources,attachments,explain` |
| `updated_since` | 增量同步（可变实体） |
| `count` | `true` 时返回 `meta.total_count`（额外开销） |

分录增量：`GET /books/{b}/journal-entries?after_seq={n}&limit=200` 按 seq 升序返回不可变分录，客户端可据此镜像账本。

## 6. 接口目录

> 所有账套接口前缀 `/api/v1/books/{book_id}`。所有写接口都支持 `?dry_run=true`。
> 本节是设计目录，✅ 为已实现；**实际可用的接口与参数以 16 号文档（由代码生成）和 `/api/v1/openapi.json` 为准**，未标 ✅ 且不在 16 号文档中的为规划项。

### 6.1 身份、账套、令牌

| 方法 | 路径 | scope | 说明 |
|---|---|---|---|
| POST | `/api/v1/auth/login` · `/auth/logout` | — | 登录 / 登出 |
| GET | `/api/v1/auth/me` | — | 当前用户、账套、角色、scope |
| GET / POST | `/api/v1/books` | 超级管理员 | 账套列表 / 创建（选择科目表模板） |
| GET / PATCH | `/` | ledger:read / admin | 账套设置 |
| GET / PUT / DELETE | `/members/{user_id}` | admin | 成员与角色 |
| GET / POST | `/tokens` | admin（本人令牌：任意角色） | 令牌列表 / 创建（明文只返回一次） |
| POST | `/tokens/{id}:revoke` · `:rotate` | admin / 本人 | 吊销 / 轮换 |

### 6.2 基础数据与配置

| 方法 | 路径 | scope | 说明 |
|---|---|---|---|
| GET / POST / PATCH | `/commodities` · `/commodities/{code}` | read / config | ✅ 币种（各账套共用）：新增代码、名称、类别、小数位、符号；可停用（本位币除外）；已有金额后小数位不可改（数据库触发器保护） |
| GET / POST | `/commodity-price-rules` | read / config | 价格规则 |
| GET / POST | `/fx-rates` | read / config | 汇率查询（`base, quote, date`）/ 手工录入 |
| POST | `/fx-rates:fetch` | config | 立即从提供方获取 |
| GET / POST | `/accounts` | read / config | 科目树与列表 / 新建 |
| GET / PATCH | `/accounts/{id}` | read / config | 详情 / 修改（受使用中约束） |
| GET | `/accounts/{id}` | read | ✅ 详情含各币种余额；某科目的逐笔流水用 `GET /transactions?account=` |
| POST | `/accounts:apply-template` | config | 从内置科目表模板创建 |
| CRUD | `/dimension-types` · `/dimension-values` | read / config · reference | 维度 |
| CRUD | `/counterparties` · `/counterparties/{id}/aliases` · `/counterparties/{id}/accounts` | read / reference | 往来方；✅ `default_type`、`default_channel`：录入与导入省略交易类型 / 渠道时自动带出（显式输入优先，回执 `provenance.defaults` 标出）；详情含 `defaults` 与该往来方的手续费规则 |
| POST / PATCH | `/dimension-types/{code}/values` · `/dimension-values/{id}` | reference | ✅ 维度值（渠道等）含 `aliases`；凡引用渠道处可用代码、名称或别名，重名时报 `AMBIGUOUS_REFERENCE` |
| GET | `/counterparties:resolve?text=` | read | 文本解析为往来方（返回候选与匹配方式） |
| GET | `/transaction-types` | read | ✅ 交易类型目录：每种类型的输入方式、输入 JSON Schema、默认科目、示例请求（供前端生成表单、AI 构造参数） |
| GET / POST | `/fee-rules` | read / config | ✅ 手续费规则列表（`include_retired`）/ 新建或新版本（同 code 再提交，`valid_from` 须更晚） |
| POST | `/fee-rules/{code}:retire` | config | ✅ 停用该代码的全部版本 |
| GET | `/fee-rules:evaluate` | read | ✅ 试算：`type, amount, on, channel?, counterparty?, commodity?` → 命中规则与手续费 |

### 6.3 交易与总账

| 方法 | 路径 | scope | 说明 |
|---|---|---|---|
| GET | `/transactions` | read | ✅ 列表与搜索：`status`（`posted` 默认 / `reversed` 已删除）、`type`（多个用逗号分隔，如 `sale_refund,purchase_refund`）、`date_from, date_to, counterparty, channel, account（含下级）, commodity, amount_min, amount_max, is_estimate, linked_to, tag, q, created_channel`；游标分页 |
| POST | `/transactions` | write | ✅ 记账（立即入账）；业务类型填 `inputs`，手工凭证 / 期初填 `lines` |
| GET | `/transactions/{ref}` | read | ✅ 详情：输入、计算值、全部分录（含修改与删除留下的冲销 / 重记）、关联、来源、标签 |
| PATCH | `/transactions/{ref}` | write | ✅ 修改任何字段；`inputs` 可只给要改的键（null 删除）；影响账面时冲销重记，编号不变；`expected_version` 可选 |
| DELETE | `/transactions/{ref}` | write | ✅ 删除（冲销当前分录）；可选请求体 `{reason?, expected_version?}` |
| POST | `/transactions/{ref}:restore` | write | ✅ 恢复已删除的交易 |
| GET | `/transactions/{ref}/explain` | read | ✅ 解释链：可读输入、手续费规则候选及未命中原因、计算值、分录行、关联 |
| POST | `/transactions:batch` | write | ✅ 批量 ≤ 200 条；`atomic=true` 全部成功或全部回滚（错误带 `index`），`false` 逐条返回结果 |
| POST | `/transactions:repost` | write | ✅ 按新规则重算：`reason, ids?, types?, channels?, date_from?, date_to?, limit?`；先 `?dry_run=true` |
| GET | `/journal-entries` · `/journal-entries/{ref}` | read | ✅ 分录（`after_seq` 增量） |
| GET | `/balances` | read | ✅ 余额（`as_of`、`accounts`、`as_known_at`） |

### 6.4 期间（已去掉）

期间结账、锁账、锁账例外、期末重估与年末结转已于 2026-10-19 去掉（17 号文档）。

### 6.5 导入、来源记录、规则、匹配

导入流程：上传或提交记录 → 去重、按规则分类、匹配已有交易、跨来源配对（批次尚未入账）→ 补全未识别的记录 → 完成导入（已分类的直接入账）。已实现的接口见 §6.5.1；规划中的还有 `:test-parse`（试解析）、`/matching:run`（重跑匹配）、`/matching/metrics`（匹配质量）。

### 6.5.1 已实现（M4）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET / POST / PATCH | `/import-sources` · `/import-sources/{code}` | 导入来源（kind 另有 `redeem_page`、`ai_extract`，06 号 §0.1） |
| POST | `/import-sources:preview`（multipart：kind、config、file） | 用样例文件试一套来源设置：文件前 15 行、会读出的记录与行错误；不保存。未知 kind 返回 422 并列出可用的；`ai_extract` 不需要预览 |
| POST | `/import-batches`（JSON：source + records 或 file_id）· `/import-batches:upload`（multipart，`file` 可重复：`redeem_page` / `ai_extract` 多个文件合成一批） | 生成待完成批次（尚未入账）。`ai_extract`：立即返回 201、批次 `extracting`，由 worker 读取；同来源同一组文件已有批次时返回 200 与该批次；未配置 AI 503 `AI_UNAVAILABLE`，超出每日上限 429 `RATE_LIMITED`，不支持的文件类型 415 |
| GET | `/import-batches` · `/import-batches/{id}` | 批次列表（每批带 `open_records`：尚未入账的记录数，即待补全的和已补全、等完成导入的；已忽略、重复、已入账的不计）/ 摘要与记录 |
| POST | `/import-batches/{id}:commit` · `:revert` | 完成（入账）/ 撤销；识别失败的批次也可撤销（放弃） |
| POST | `/import-batches/{id}:retry` | 识别失败（`failed`）的批次用同样的文件再读一次 |
| POST | `/import-batches/{id}:decide-matches` | 一次回答批次里“可能已记过”的待确认：`{same: bool, record_ids?: [...]}`，不给 `record_ids` 即全部 |
| GET / PATCH | `/source-records` · `/source-records/{id}` | 查找 / 人工分类（锁定字段）；已完成导入的批次里留下的记录，补全后立即入账 |
| POST | `/source-records:ignore` · `/source-records/{id}:link` | 忽略 / 手工关联交易 |
| GET / POST | `/match-suggestions` · `/match-suggestions/{id}:accept` · `:reject` | 匹配建议；`batch_id` 只看某次导入的；已自动关联的也可 `:reject`（同时删除凭证关联） |
| GET / POST | `/rules` · `/rules/{code}:enable` · `:disable` · `/rules:test` · `/rules:apply` | 分类规则 |
| GET / POST | `/pairing-rules` | 配对规则 |

批次详情里的每条记录另带：`match`（已关联或待确认的那笔交易：编号、日期、摘要、金额，及方法 `same_day` / `daily_total` / `same_day_party` 与状态）与 `fee_rule`（`basis`：`actual` 按实际填写 / `rule` 按规则 / `none` 无规则按 0，`rule` 为规则名称、代码@版本、费率）。交易详情同样带 `fee_rule`。批次状态另有 `extracting`（识别中）与 `failed`（识别失败），摘要的 `extraction` 记录文件、读不清的行与合计核对。

### 6.6 对账与未清项（已去掉）

余额断言、对账会话与往来核销已于 2026-10-19 去掉（17 号文档）。

### 6.7 报表、查询、导出

| 方法 | 路径 | scope | 说明 |
|---|---|---|---|
| GET | `/reports` | read | ✅ 报表目录、参数与自定义汇总示例 |
| GET | `/reports/summary` · `/income-statement` · `/operations` · `/sales` · `/fees` · `/credit-purchases` | read | ✅ 经营报表（07 号文档 §3.1）；每行带 `drilldown` |
| GET | `/reports/query` | read | ✅ 自定义汇总：`group_by`（最多 4 个）、`measures`、各类过滤；列表参数可重复或逗号分隔 |
| GET | `/reports/trial-balance` | read | ✅ 试算平衡 |
| GET | `/exports/{csv\|xlsx\|beancount\|json}` | read | ✅ 导出（`date_from`、`date_to` 可选），流式生成后下载；MCP `export_ledger` 另存入文件库 |
| POST | `/reports/{code}/snapshots` · GET `/reports/verify` | read | 规划：保存快照 / 按指纹复算（当前以 `meta.fingerprint` 代替） |

### 6.8 检查、审计、变更集、待办

| 方法 | 路径 | scope | 说明 |
|---|---|---|---|
| POST | `/checks:run` | read | ✅ 运行检查 |
| GET | `/check-runs` · `/check-runs/{id}` | read | ✅ 结果 |
| GET | `/audit-events` | read | ✅ 审计查询（实体、操作者、渠道、变更集、时间） |
| GET | `/change-sets` · `/change-sets/{id}` | read | ✅ 变更集 |
| POST | `/change-sets/{id}:undo` | write | ✅ 撤销（新记的删除、删除的恢复、修改与重算改回、导入撤销、手续费规则改动还原；其余列为 manual）；请求体可选 `{reason?}` |
| GET | `/work-items` · `/work-items/summary` | read | ✅ 待处理：待补全的导入记录、待确认的匹配、未完成的导入、估算手续费、待核对款项、未通过的检查，每项附建议工具 |

### 6.8.1 AI 提供商（设置 → AI 模型）

| 方法 | 路径 | scope | 说明 |
|---|---|---|---|
| GET | `/ai/status` | 成员 | ✅ 识别、AI 助手是否可用 |
| GET | `/ai/providers` · `/ai/routes` · `/ai/usage?days=` | admin:read | ✅ 提供商（不含密钥，只有末 4 位）、任务分配、近期用量与费用估算 |
| POST · PATCH · DELETE | `/ai/providers` · `/ai/providers/{id}` | config:write，仅网页端 | ✅ 增删改；改 Base URL 必须同时填 `api_key` |
| POST | `/ai/providers/{id}:test` | config:write，仅网页端 | ✅ 测试连接：模型列表、一次极小请求、能力 |
| PUT | `/ai/routes` | config:write，仅网页端 | ✅ 识别 / AI 助手各自的提供商 + 模型与备用顺序 |

“仅网页端”：API 令牌（含 MCP）即使有 `config:write` 也返回 403。细节见 19 号文档。

| GET | `/ai/handbook` | ledger:read | ✅ 识别规则手册（当前版本或内置默认）、门槛、历史版本（通用规则，不含密钥与费率） |
| GET | `/ai/playbooks` | ledger:read | ✅ 场景（与 MCP 提示词同源），每个附 `tiers`：你可以用哪些档位让 AI 助手按它执行 |
| PUT · DELETE | `/ai/playbooks/{code}` | rules:write | ✅ 修改内置场景或新增（`expected_version`，工具必须存在，作用域自动算出）/ 恢复内置（自定义的删除） |
| PUT | `/ai/handbook` · POST `/ai/handbook:restore` | rules:write | ✅ 保存新版本（`expected_version`，0 = 替换内置默认）/ 恢复旧版本 |
| POST | `/source-records/{id}:save-rule` | rules:write | ✅ 存为规则：按这条记录的分类生成或更新规则，并重新分类同批记录 |

### 6.8.2 AI 助手

| 方法 | 路径 | scope | 说明 |
|---|---|---|---|
| GET | `/agent/runs` · `/agent/runs/{id}` | ledger:read | ✅ 最近的运行（自己的，管理员只读可看全部）；单个运行含步骤与变更集状态 |
| POST | `/agent/runs` | ledger:read，仅网页端 | ✅ 开始：`{instruction, tier?, file_ids?, playbook?}`；实际权限 = 你的权限 ∩ 档位；带文件只读取与暂存；超出每日次数 429，未配置 503 `AI_UNAVAILABLE` |
| POST | `/agent/runs/{id}:answer` · `:cancel` | ledger:read，仅网页端 | ✅ 回答提问 / 停止 |

一次运行的写入在同一个变更集里，用 `POST /change-sets/{id}:undo` 整次撤销。细节见 19 号 §3。

### 6.9 其他

| 方法 | 路径 | scope | 说明 |
|---|---|---|---|
| GET | `/tags` | read | ✅ 标签与使用次数；交易创建 / PATCH 的 `tags` 字段整体设置，`GET /transactions?tag=`、`/reports/query?tags=` 过滤 |
| CRUD | `/webhooks`；GET `/webhooks/{id}/deliveries`；POST `/webhooks/{id}:test` | admin | Webhook |
| GET | `/mcp-calls` | admin | ✅ MCP 调用日志 |
| GET | `/jobs/{id}` | read | 任务状态 |
| GET | `/meta/capabilities` | read | ✅ 已启用功能、调用者 scope、限额 |
| GET | `/meta/schemas/{name}` · `/meta/enums` | read | 实体 JSON Schema 与枚举（供前端与 AI） |
| POST / GET | `/admin/backups` | admin | 立即备份 / 备份列表 |
| GET | `/healthz` · `/readyz`（根路径，无需认证） | — | 存活 / 就绪 |

## 7. 错误

```json
{
  "type": "https://bill.example.com/errors/INVALID_STATE",
  "title": "当前状态不允许该操作",
  "status": 409,
  "code": "INVALID_STATE",
  "detail": "交易 T2026-000123 已删除，恢复后才能修改。",
  "retryable": false,
  "next_action": { "operation": "transactions_restore", "mcp_tool": "restore_transaction" },
  "errors": [],
  "candidates": null,
  "request_id": "req_01J…"
}
```

| 错误码 | HTTP | 可重试 | 说明 |
|---|---|---|---|
| `UNAUTHENTICATED` / `TOKEN_EXPIRED` / `TOKEN_REVOKED` | 401 | 否 | |
| `FORBIDDEN_SCOPE` | 403 | 否 | `detail` 指明缺少的 scope（或“只能在网页端修改”） |
| `NOT_FOUND` | 404 | 否 | |
| `VALIDATION_FAILED` | 422 | 否 | 请求结构错误，`errors[]` 给字段路径 |
| `AMBIGUOUS_REFERENCE` | 422 | 否 | 名称解析有多个候选，`candidates[]` |
| `IDEMPOTENCY_KEY_REQUIRED` | 400 | 否 | |
| `IDEMPOTENCY_MISMATCH` | 409 | 否 | |
| `IDEMPOTENCY_IN_PROGRESS` | 409 | 是 | |
| `VERSION_CONFLICT` | 409 | 否 | 附当前实体 |
| `INVALID_STATE` | 409 | 否 | |
| `IMPORT_CHECK_FAILED` | 422 | 否 | 安全校验未通过 |
| `PARSER_NOT_FOUND` / `UNSUPPORTED_MEDIA_TYPE` / `FILE_TOO_LARGE` | 422 / 415 / 413 | 否 | |
| `SNAPSHOT_STALE` | 503 | 是 | 余额快照重算中，`Retry-After` |
| `RATE_LIMITED` | 429 | 是 | `Retry-After` |
| `INTERNAL` | 500 | 是 | |
| 记账类错误 | 见 05 号文档 §8 | | |

## 8. Webhook（规划，未实现）

外部 AI 以 MCP / REST 主动读取（`list_pending_work`、`change-sets`），当前不需要推送；有外部系统订阅需求时按下述设计实现。

- 事件：`transaction.created|updated|deleted|restored`、`journal_entry.created`、`import_batch.committed|reverted`、`check.failed`、`change_set.reverted`；
- 载荷：`{"id": "obx_…", "type": "...", "created_at": "...", "book_id": "...", "data": {...}}`；
- 签名头：`X-BK-Signature: t=<unix>,v1=<hex(HMAC-SHA256(secret, t + "." + body))>`，接收方校验时间偏差 ≤ 5 分钟；
- 投递：outbox 同事务写入 → worker 投递；失败按 1 分钟、5 分钟、30 分钟、2 小时、6 小时、24 小时重试，共 6 次；投递日志可查询；
- 创建端点时发送 `ping` 事件，需返回 2xx 才启用。

## 9. 限流

按令牌固定窗口计数（PostgreSQL 共享）：请求数默认 120 次/分钟（令牌可配置），写入 30 次/分钟；超限返回 429 与 `Retry-After`。✅ 已实现（REST 与 MCP 共用）。

## 10. 契约保障

- ✅ OpenAPI 与 MCP 工具（名称、scope、输入 schema）快照纳入版本库（`v2/contracts/`），测试比对，接口变化必须同时提交快照与 16 号文档（`scripts/contracts.py` 生成）；删除字段、改类型、收紧校验视为破坏性变更，须升主版本；
- 规划：schemathesis 基于 OpenAPI 生成请求做模糊测试；
- 每个 MCP 写工具声明其对应的 `operationId`，测试校验两者参数与错误码一致（见 09 号文档 §10）。
