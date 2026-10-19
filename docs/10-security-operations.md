# 10 安全、部署与运维

## 1. 安全

### 1.1 身份与会话
| 项 | 要求 |
|---|---|
| 密码 | argon2id（time_cost=3、memory_cost=64 MiB、parallelism=2，可配置）；最短 12 位；登录失败 5 次锁定 15 分钟（按账号与 IP） |
| 会话 | 随机 32 字节令牌，数据库只存 SHA-256；Cookie HttpOnly、Secure、SameSite=Lax；空闲 12 小时、绝对 7 天过期；修改密码后吊销其他会话 |
| CSRF | 会话写请求校验 `X-CSRF-Token`（同步令牌模式） |
| 二次验证（P2） | admin / owner 可启用 TOTP；密钥加密存储（实现时引入 `BK_SECRET_KEY` 作为主密钥） |
| 认证审计 | 登录成功 / 失败、令牌创建 / 吊销 / 使用异常（新 IP）写审计事件 |

### 1.2 API 令牌与 OAuth
- 令牌格式 `bk_pat_<base62 40 位>`，熵 ≥ 238 位；只存 SHA-256；创建时明文显示一次；
- 每个令牌：账套、用户、scope、预设、是否允许 MCP、两段式要求、过期时间（默认 90 天，可设永不过期但需 admin）、IP 白名单、限流；
- 令牌有效权限永远不超过其所属用户的当前角色（用户降级或停用后立即生效）；
- OAuth 2.1（P2）：仅授权码 + PKCE（S256）；授权页显示客户端名称、请求的预设与 scope，用户可降级为只读；访问令牌 1 小时、刷新令牌 30 天并轮换；令牌受众绑定 MCP 资源 URL；支持吊销端点。

### 1.3 传输与边界
- 全站 HTTPS（nginx + Let's Encrypt），HSTS；应用只监听 `127.0.0.1:8000`；数据库不对外暴露端口；
- CORS 默认关闭（前端同源）；如需跨域，显式白名单；
- 安全响应头：`Content-Security-Policy`（前端阶段细化）、`X-Content-Type-Options: nosniff`、`Referrer-Policy: same-origin`、`X-Frame-Options: DENY`；
- 上传：大小上限、MIME 白名单、以内容哈希命名存储，不使用用户提供的文件名作为路径；下载时 `Content-Disposition: attachment`。

### 1.4 数据保护
| 数据 | 措施 |
|---|---|
| 兑换码、卡密、完整账号标识 | 解析时即只保留 SHA-256 与末 4 位 |
| Webhook 密钥、TOTP 密钥 | 应用层加密（AES-GCM，主密钥 `BK_SECRET_KEY` 随该功能引入），不出现在 API 响应与日志中 |
| 审计前后值 | 敏感字段写入前脱敏 |
| 日志 | 不记录请求体中的金额以外的敏感字段、令牌、Cookie；MCP 参数记录脱敏版本与哈希 |
| 备份 | 备份文件权限 600；异地副本可选用 age 加密 |

### 1.5 数据库权限
迁移账号 `bk_owner`（DDL）与应用账号 `bk_app`（DML）分离；`bk_app` 对分录、分录行、审计表无 DELETE / TRUNCATE，仅有列级 UPDATE（见 04 号文档 §17）。应用启动时校验触发器与权限存在，缺失则拒绝启动。

### 1.6 依赖与供应链
- 依赖锁定（`uv.lock`），镜像基于固定 digest 的 `python:3.14-slim`；
- CI 运行 `pip-audit`（或 uv 等价）与镜像漏洞扫描；
- 不在运行时下载代码或插件；解析器、模板、规则都是数据或仓库内代码。

## 2. 部署

### 2.1 拓扑

```
Internet ──HTTPS──▶ nginx (宿主机, bill.example.com)
                      ├─ /api/  ──▶ 127.0.0.1:8000  api (uvicorn, FastAPI)
                      ├─ /mcp   ──▶ 127.0.0.1:8000  （proxy_buffering off；read_timeout 300s）
                      └─ /      ──▶ 前端静态文件（前端阶段）
docker compose:
  db      postgres:18-alpine   volume: pgdata        （仅内部网络）
  api     book-keeper:2.x      volume: data(/data)   ports: 127.0.0.1:8000
  worker  book-keeper:2.x      volume: data(/data)   （同镜像，命令不同）
```

### 2.2 Compose 要点

```yaml
services:
  db:
    image: postgres:18-alpine
    environment:
      POSTGRES_DB: bookkeeper
      POSTGRES_USER: bk_owner
      POSTGRES_PASSWORD_FILE: /run/secrets/pg_owner_password
    volumes: [pgdata:/var/lib/postgresql]   # 18 版镜像的数据目录为 /var/lib/postgresql/18/docker
    healthcheck: { test: ["CMD", "pg_isready", "-U", "bk_owner"], interval: 10s }
    restart: unless-stopped
  api:
    image: ghcr.io/liulixin-lex/book-keeper:2.0.0
    command: ["bookkeeper", "serve", "--host", "0.0.0.0", "--port", "8000"]
    env_file: .env
    volumes: [data:/data]
    ports: ["127.0.0.1:8000:8000"]
    depends_on: { db: { condition: service_healthy } }
    healthcheck: { test: ["CMD", "bookkeeper", "healthcheck"], interval: 15s }
    restart: unless-stopped
  worker:
    image: ghcr.io/liulixin-lex/book-keeper:2.0.0
    command: ["bookkeeper", "worker"]
    env_file: .env
    volumes: [data:/data]
    depends_on: { db: { condition: service_healthy } }
    restart: unless-stopped
volumes: { pgdata: {}, data: {} }
```

生产覆盖文件中端口列表使用 `!override`（Compose 会合并多个文件中的端口列表）。容器以非 root 用户运行，根文件系统只读（`/data` 与 `/tmp` 除外）。

### 2.3 发布流程
1. 构建镜像（带版本号与 git 提交）：服务器本地 `docker build`，或 CI 构建后推送镜像仓库（推送前需经用户同意）；
2. 服务器：`deploy/scripts/backup.sh` → 更新 `.env` 中 `BK_IMAGE` → `docker compose run --rm migrate`（迁移账号）→ `docker compose up -d api worker` → `/readyz` 与冒烟测试（登录、读取余额、MCP 列工具）；
3. 失败回滚：`BK_IMAGE` 切回上一镜像；若迁移已执行且不可逆，用发布前备份恢复。

首次部署与 v1 → v2 切换见 15 号文档。

### 2.4 OAuth 与客户端 IP

- `BK_OAUTH_ENABLED=true` 时开放 OAuth 2.1（09 号文档 §0）；生产自检要求 `BK_PUBLIC_URL` 为 https；nginx 另需转发 `/.well-known/oauth-*` 与 `/oauth/`（`deploy/nginx/bookkeeper.conf`）。
- 客户端 IP 用于限流与审计：api 容器只在宿主机回环地址发布端口，nginx 是唯一客户端，因此 uvicorn 信任其 `X-Forwarded-For`（`--forwarded-allow-ips *`）；nginx 以 `$remote_addr` 覆盖该头（不追加，防伪造）。若前面还有 CDN，先在 nginx 配置 real_ip。

## 3. 备份与恢复

| 项 | 策略 |
|---|---|
| 数据库 | `deploy/scripts/backup.sh`：每日 03:00（宿主机 cron）`pg_dump -Fc`；发布、正式迁移前手动执行一次 |
| 附件 | 内容寻址、只增不改；同一脚本对 `/data` 卷做 rsync 硬链接快照 |
| 保留 | 数据库：最近 14 份 + 最近 8 周每周 1 份 + 最近 12 个月每月 1 份；附件快照 14 份（变量 `BK_KEEP_DAILY/WEEKLY/MONTHLY`） |
| 校验 | 备份后 `pg_restore --list` 校验并写 SHA-256；`deploy/scripts/restore-check.sh` 每周恢复最新备份到临时库，运行 `trial_balance_zero`、`entries_balanced`、`hash_chain`，结束后删除临时库 |
| 异地 | 可选：rsync `backups/` 到另一台主机或对象存储（age 加密） |
| 可读归档 | worker 每月 1 日把上月 Beancount 文本与 CSV 写入 `/data/archive/`（随附件快照进入备份，不依赖本系统即可查看与校验） |
| 恢复 | 停 api / worker → `pg_restore --clean` 到 bookkeeper 库（或恢复到新库后切换连接）→ 恢复 `/data` 快照 → `bookkeeper run-checks` → 启动 |

指标：RPO ≤ 24 小时（发布与迁移前另有备份），RTO ≤ 1 小时。

## 4. 监控与日志

| 项 | 内容 |
|---|---|
| 日志 | JSON 结构化：时间、级别、request_id、账套、操作者、渠道、路由 / 工具、状态码、耗时；保留 30 天（容器日志轮转） |
| 探针 | `/healthz`（进程存活）、`/readyz`（数据库连通、迁移版本匹配、触发器存在决定就绪；worker 心跳是否在 2 分钟内只作报告，不影响 API 就绪，以免 worker 重启时 API 被判为不健康） |
| 告警事件 | 哈希链校验失败、错误级检查失败、备份失败或校验失败、任务连续失败、worker 心跳丢失、磁盘使用 > 80% |
| 告警通道 | Webhook 事件（`check.failed` 等）+ 待办中的 `check_failed`；可选 SMTP（P3） |
| 指标（P3） | Prometheus：请求量与延迟、记账数、导入行数、任务队列长度、MCP 调用量与错误率 |

## 5. 运维命令（`bookkeeper` CLI）

| 命令 | 说明 |
|---|---|
| `serve` / `worker` | 启动 API / worker（生产配置自检不通过时拒绝启动） |
| `migrate` | 执行数据库迁移（使用迁移账号）并授予应用账号权限 |
| `create-user --email --name [--superadmin]` | 创建用户（密码取自 `BK_NEW_PASSWORD` 或交互输入） |
| `reset-password --email` | 重置密码、解除锁定、吊销全部会话 |
| `create-book --name --owner-email [--base --timezone]` | 创建账套（默认科目表） |
| `create-token --book --user-email --name [--preset --mcp --days]` | 创建令牌（明文只输出一次） |
| `run-checks [--book] [--codes]` | 运行检查，任一 error 级失败时退出码 1 |
| `verify-audit [--scope]` | 校验审计哈希链 |
| `export --book --format csv\|xlsx\|beancount\|json [--from --to] --output` | 导出账本 |
| `legacy-migrate --source [--files-dir] [--apply]` | v1 数据迁移（见 11 号文档） |
| `healthcheck` | 容器健康检查 |

备份与恢复演练为宿主机脚本：`deploy/scripts/backup.sh`、`deploy/scripts/restore-check.sh`（§3）。领域错误以 `代码: 说明` 输出到 stderr，退出码 2。
