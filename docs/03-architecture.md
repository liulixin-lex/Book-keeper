# 03 架构与技术选型

> **2026-10-19**：草稿、过账、复核、两段式预览、期间结账与锁账、期末重估、对账与核销等已去掉，本文相关内容仅作设计记录；现状见 [17 精简账本](17-lean-ledger.md)。

## 1. 技术选型

| 层 | 选择 | 理由 |
|---|---|---|
| 语言 | Python 3.14 | 当前稳定版；`Decimal` 精确运算；MCP 官方 SDK 成熟 |
| Web 框架 | FastAPI + Pydantic v2 | 类型驱动校验与 OpenAPI 3.1 自动生成；依赖注入便于鉴权与事务管理 |
| ORM / SQL | SQLAlchemy 2.0（同步会话）+ psycopg 3 | 显式事务边界，测试简单；复杂报表直接用 Core 写 SQL |
| 数据库 | **PostgreSQL 18**（`postgres:18-alpine`，镜像 tag 固定） | 需要延迟约束触发器、CHECK、部分唯一索引、`SELECT … FOR UPDATE SKIP LOCKED`、JSONB、`NUMERIC`、窗口函数；多客户端（UI、API、MCP、worker）并发写入 |
| 迁移 | Alembic | 版本化 schema；每个迁移有升级测试 |
| MCP | 官方 `mcp` Python SDK（FastMCP），Streamable HTTP 挂载在同一应用的 `/mcp`；另提供 stdio 入口 | 与 REST 共用进程与服务层 |
| 后台任务 | 自研数据库任务队列（`jobs` 表 + SKIP LOCKED）+ 独立 worker 进程 | 不引入 Redis / Celery；任务与业务写入同库同事务（outbox） |
| 表达式 | 自研白名单 AST 求值器（基于 Python `ast` 解析，仅允许算术、比较、布尔、白名单函数，全部 `Decimal`） | 模板、手续费、规则共用；不执行任意代码 |
| 密码 | argon2-cffi（argon2id） | 当前推荐算法 |
| 包管理 | uv + `uv.lock`（锁定 Linux x86_64 平台） | 可复现构建 |
| 质量 | ruff（lint + format）、mypy（`domain/` 严格模式）、pytest、hypothesis、schemathesis | 见 12 号文档 |
| 部署 | Docker Compose：`db`、`api`、`worker`；宿主机 nginx 反向代理与 TLS | 单机即可满足规模 |

**为什么不用 SQLite**：SQLite 不支持延迟约束触发器与行级锁，多进程并发写入只能串行化整个库；本系统要求数据库层兜底借贷平衡、不可变与锁账，并有多个写入客户端。数据量虽小，但正确性约束是首要需求。

## 2. 分层

```
┌────────────────────────────────────────────────────────────┐
│ 接口层  REST (FastAPI routers)   MCP (FastMCP tools)   CLI │
│         ─ 鉴权、作用域、幂等、请求 ID、信封、错误映射 ─     │
├────────────────────────────────────────────────────────────┤
│ 应用层  services/*：用例编排、事务边界、审计、变更集、outbox│
├────────────────────────────────────────────────────────────┤
│ 领域层  domain/*：纯函数，无 I/O                            │
│   money · rounding · fx · expressions · filter_dsl         │
│   posting_engine · fee_engine · rule_engine · matching     │
│   checks · report_calculators                               │
├────────────────────────────────────────────────────────────┤
│ 基础设施 repositories/* · db（模型、会话、迁移）· files     │
│          · jobs · fx_providers · importers/* · webhooks     │
└────────────────────────────────────────────────────────────┘
```

规则：
1. 领域层不依赖 SQLAlchemy、FastAPI、MCP；输入输出是不可变数据类（`@dataclass(frozen=True)`）。
2. REST 与 MCP **只调用应用层服务**，不得直接访问仓储或模型；两者共用同一套校验、审计与错误码。
3. 每个应用层用例在一个数据库事务内完成，审计事件、变更集、outbox 事件与业务写入同事务提交。
4. 报表计算只有一个实现（应用层 `reports` 服务 + 领域层计算器），REST、MCP、导出都调用它。

## 3. 模块划分

| 模块 | 职责 | 主要表 |
|---|---|---|
| `identity` | 用户、会话、账套成员、角色 | users, sessions, book_members |
| `tokens` | API 令牌、作用域、OAuth 客户端与授权 | api_tokens, oauth_clients, oauth_grants |
| `books` | 账套与设置 | books |
| `commodities` | 商品、价格规则、汇率与汇率获取 | commodities, commodity_price_rules, fx_rates |
| `accounts` | 科目表、模板导入、科目约束 | accounts |
| `dimensions` | 维度类型与值 | dimension_types, dimension_values |
| `counterparties` | 往来方、别名、子账户 | counterparties, counterparty_aliases, counterparty_accounts |
| `templates` | 交易类型、过账模板版本 | transaction_types, posting_templates |
| `fees` | 手续费规则与版本 | fee_rules |
| `transactions` | 交易草稿、过账、冲正、更正、重过账 | transactions, transaction_sources, transaction_links |
| `ledger` | 分录、分录行、编号、哈希链、余额、快照 | ledger_heads, journal_entries, journal_lines, journal_line_dimensions, account_balances, daily_balances, sequences |
| `periods` | 期间、锁账、例外、检查点 | fiscal_periods, lock_settings, lock_exceptions, period_checkpoints |
| `imports` | 来源、批次、来源记录、解析器注册 | sources, import_batches, source_records |
| `rules` | 规则与执行记录 | rules, rule_runs |
| `matching` | 去重、匹配建议、排除对、记录配对规则 | match_suggestions, match_exclusions, pairing_rules |
| `reconciliation` | 余额断言、对账会话、未清项核销 | balance_assertions, reconciliations, line_matches |
| `reports` | 报表、查询、导出、报表快照 | report_runs |
| `checks` | 健康检查 | check_runs, check_results |
| `audit` | 审计事件、变更集、实体历史 | audit_events, change_sets |
| `files` | 附件存储与挂接 | files, attachments |
| `tags` | 标签 | tags, entity_tags |
| `previews` | 预览与提交 | previews |
| `idempotency` | 幂等键 | idempotency_keys |
| `jobs` | 任务队列、定时任务 | jobs, job_schedules |
| `webhooks` | outbox、订阅、投递 | outbox_events, webhook_endpoints, webhook_deliveries |
| `mcp` | MCP 工具、资源、提示词、调用日志 | mcp_calls |
| `legacy` | 旧系统迁移 | legacy_map, legacy_archive |

## 4. 请求处理流程

### 4.1 REST 写请求

```
请求 → 认证（会话 / Bearer 令牌）→ 解析账套（路径 /books/{book_id}）
     → 作用域检查（路由声明的 scope ∩ 令牌 scope ∩ 用户角色）
     → 幂等检查（Idempotency-Key + 请求哈希：命中且一致 → 返回缓存响应；不一致 → 409）
     → 开启数据库事务
         → 应用层用例：加载 → 领域计算 → 校验 → 写入
         → 审计事件 + 变更集 + outbox 事件
         → 保存幂等响应
     → 提交 → 返回（带 request_id、change_set_id）
```

dry-run 走同一路径，但在领域计算与校验后返回结果并回滚事务，不保存幂等记录。

### 4.2 MCP 工具调用

```
MCP 请求 → 令牌认证（Bearer 或 OAuth 访问令牌）→ 工具是否在令牌预设内
        → 参数严格校验（JSON Schema，additionalProperties: false）
        → 名称解析（科目、往来方等可用名称，歧义返回候选）
        → anyio.to_thread 调用应用层服务（与 REST 完全相同）
        → 信封封装（ok / code / data / warnings / next_action / meta）
        → 记录 mcp_calls
```

### 4.3 过账（核心路径）

```
transactions.post(txn_id, expected_version)
  1. SELECT … FOR UPDATE 锁定交易行（版本校验）
  2. 领域层 posting_engine.build(txn, template_version, fee_rules, fx, accounts, …) → PostingResult
  3. 校验（期间、锁账、科目、余额约束需读取 account_balances FOR UPDATE，按科目 ID 排序加锁防死锁）
  4. 锁定账套哈希链头行（ledger_heads FOR UPDATE）→ 分配 seq、凭证号（sequences FOR UPDATE）
  5. 写 journal_entries、journal_lines、journal_line_dimensions（延迟触发器在提交时验证平衡）
  6. 更新 account_balances（余额、累计借贷、版本）、写 balance_after
  7. 累加 daily_balances 当日发生额（只存发生额，回溯写入无需级联重算）
  8. 交易状态 → posted；审计、变更集、outbox
  9. COMMIT（延迟约束检查：平衡、不可变）
```

同一账套的过账在第 4 步串行化（哈希链头锁），保证编号与哈希链连续；规模下吞吐足够（> 100 笔/秒）。

## 5. 并发与一致性

| 机制 | 用途 |
|---|---|
| 乐观并发 `version` 列 | 草稿交易、基础数据、规则、来源记录；更新须提交期望版本，不符返回 409 `VERSION_CONFLICT` 并附当前版本 |
| 行锁（FOR UPDATE，固定顺序） | 过账时的余额行、哈希链头、编号序列 |
| 延迟约束触发器 | 分录平衡、不可变、硬锁 |
| 幂等键 | 所有 POST / PATCH / DELETE 写接口 |
| 事务隔离级别 | READ COMMITTED + 显式行锁；报表使用 REPEATABLE READ 只读事务以获得一致快照 |

## 6. 后台任务

`jobs` 表：`id, kind, payload, status(queued|running|succeeded|failed|cancelled), priority, run_after, attempts, max_attempts, locked_by, locked_at, heartbeat_at, last_error, result, created_by, change_set_id`。

worker 循环：`SELECT … WHERE status='queued' AND run_after<=now() ORDER BY priority, run_after FOR UPDATE SKIP LOCKED LIMIT 1` → 执行 → 写结果。失败按指数退避重试；心跳超时的任务回收。

| 任务 | 触发 |
|---|---|
| `import.parse` / `import.commit` | 上传 / 提交（大文件异步） |
| `rules.apply` | 对历史执行规则 |
| `transactions.repost` | 重过账 |
| `checks.run` 中的 `daily_balances` 检查 | 每日（复核发生额表与分录行一致） |
| `fx.fetch` | 每日 16:30 UTC（ECB 发布后），可配置 |
| `checks.run` | 每日、结账前、手动 |
| `ledger.verify_chain` | 每日 |
| `backup.run` | 每日 03:00（账套时区）、高风险操作前 |
| `webhooks.deliver` | outbox 事件 |
| `previews.cleanup` / `idempotency.cleanup` | 每小时 |

## 7. 文件存储

- 存储目录 `DATA_DIR/files/<sha256 前 2 位>/<sha256 第 3–4 位>/<sha256>`，内容寻址，同内容只存一份；
- `files` 表记录元数据，`attachments` 表多态挂接到交易、来源记录、批次、对账、断言等；
- 下载经接口鉴权，`Content-Disposition` 使用原始文件名；
- 上传大小上限可配置（默认 25 MB）；允许的 MIME 白名单（图片、PDF、CSV、XLSX、JSON、TXT、ZIP）。

## 8. 配置

全部通过环境变量（`BK_` 前缀），Pydantic Settings 校验：

| 变量 | 默认 | 说明 |
|---|---|---|
| `BK_DATABASE_URL` | — | 应用账号（无 DDL 权限） |
| `BK_MIGRATION_DATABASE_URL` | 同上 | 迁移账号（DDL） |
| `BK_DATA_DIR` | `./data`（镜像内 `/data`） | 附件（`files/`）、迁移报告、月度归档 |
| `BK_PUBLIC_URL` | `http://localhost:8000` | 外部访问地址；`https://` 时会话 Cookie 带 Secure |
| `BK_ENVIRONMENT` | `development` | `production` 时关闭 OpenAPI 文档页 |
| `BK_SESSION_IDLE_HOURS` / `BK_SESSION_ABSOLUTE_DAYS` | 12 / 7 | 会话空闲与绝对过期 |
| `BK_LOGIN_MAX_FAILURES` / `BK_LOGIN_LOCK_MINUTES` | 5 / 15 | 登录失败锁定 |
| `BK_TOKEN_DEFAULT_DAYS` | 90 | 令牌默认有效期 |
| `BK_UPLOAD_MAX_BYTES` | 25 MB | 上传上限 |
| `BK_IDEMPOTENCY_RETENTION_DAYS` | 30 | 幂等记录保留 |
| `BK_MCP_ENABLED` / `BK_MCP_WRITE_ENABLED` | true / false | MCP 开关、写工具全局开关 |
| `BK_OAUTH_ENABLED` / `BK_OAUTH_ACCESS_DAYS` / `BK_OAUTH_REFRESH_DAYS` | false / 30 / 180 | 远程 MCP 连接器的 OAuth 2.1 登录；访问令牌与刷新令牌有效期 |
| `BK_WORKER_POLL_SECONDS` / `BK_WORKER_HEARTBEAT_SECONDS` | 2 / 30 | worker 轮询与心跳 |
| `BK_LOG_LEVEL` / `BK_LOG_JSON` | INFO / true | 日志 |

备份脚本另读宿主机变量 `BK_BACKUP_DIR`、`BK_KEEP_DAILY/WEEKLY/MONTHLY`、`BK_DATA_VOLUME`（10 号文档 §3）。

## 9. 代码目录

```
v2/
├── pyproject.toml / uv.lock / Dockerfile / compose.yaml / compose.production.yaml
├── migrations/                     # Alembic
├── src/bookkeeper/
│   ├── main.py                     # 应用工厂：REST + /mcp 挂载
│   ├── config.py
│   ├── domain/                     # 纯函数核心（无 I/O）
│   │   ├── money.py  rounding.py  fx.py  expressions.py  filter_dsl.py
│   │   ├── posting/ (engine.py, template_model.py, validation.py, explain.py)
│   │   ├── fees.py  rules.py  matching/ (dedup.py, scoring.py, assignment.py)
│   │   ├── checks.py  reports/ (trial_balance.py, statements.py, …)
│   │   └── errors.py               # 领域错误码
│   ├── db/ (base.py, session.py, models/*.py, triggers.sql)
│   ├── repositories/*.py
│   ├── services/*.py               # 应用层用例
│   ├── api/ (deps.py, envelope.py, errors.py, routers/*.py)
│   ├── mcp/ (server.py, auth.py, envelope.py, tools/*.py, resources.py, prompts.py)
│   ├── importers/ (base.py, registry.py, wechat.py, alipay.py, stripe.py,
│   │               card_shop_orders.py, upstream_logs.py, generic_tabular.py)
│   ├── fx_providers/ (frankfurter.py, manual.py)
│   ├── jobs/ (queue.py, worker.py, schedules.py, tasks/*.py)
│   ├── files/ (storage.py)
│   ├── legacy/ (extract.py, transform.py, load.py, verify.py)
│   └── cli.py                      # 管理命令
└── tests/ (unit/, property/, integration/, api/, mcp/, importers/fixtures/, golden/, migration/)
```

## 10. 编码规范

1. 金额只用 `Money(amount_minor: int, commodity: str)` 与 `Decimal`；禁止 `float`（ruff 规则 + 单元测试扫描）。
2. 时间：数据库 `timestamptz`；业务日期 `date`，由“发生时间转换到账套时区”得出；禁止使用本地时区默认值。
3. ID：`<前缀>_<ULID>`，前缀见 04 号文档；对外只暴露带前缀 ID。
4. 所有错误使用领域错误码（`domain/errors.py`），接口层统一映射为 HTTP 状态与 MCP 信封。
5. 每个服务函数签名显式接收 `ctx: RequestContext`（账套、操作者、渠道、请求 ID、变更集、dry_run）。
6. 每个数据库表必须有 `book_id`（全局表除外：users、commodities、fx_rates、jobs）。
7. 新增写接口必须同时提供：dry-run、幂等、审计、MCP 暴露评估、测试。
