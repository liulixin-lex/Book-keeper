# 15 部署与切换手册（v1 → v2）

> 适用于服务器 <服务器地址>（bill.example.com）。**每一步涉及生产的操作都需要事先征得用户同意**；本手册只描述做法。

## 0. 前提与决定

| 项 | 说明 |
|---|---|
| 前端 | v2 前端已随镜像构建（`v2/web`）。切换前 v1 界面仍在使用，因此 v2 先在独立入口上线，按 §8 验收后再切换 |
| 推荐方式 | v2 部署在独立入口（如 `ledger.example.com`，或 bill.example.com 上的独立端口），v1 保持现状；外部 AI 通过 v2 的 `/mcp` 记账 |
| 数据唯一性 | v2 正式迁移后，新数据只写 v2；v1 冻结为只读（停止所有导入脚本与自动写入账号），避免两边分叉 |
| 需用户确认 | ① v2 的访问入口（子域名 / 端口）；② 冻结 v1 的时间点；③ 试迁移报告；④ 是否推送镜像到 GHCR（或在服务器本地构建） |

## 1. 准备（不影响 v1）

```bash
# 服务器上；代码从本地仓库 scp v2/ 目录（或获准后从 GitHub 拉取）
cd /opt/bookkeeper                              # = v2 目录
docker build -t book-keeper:2.0.0 .
cp .env.example .env && chmod 600 .env          # 填写两个数据库密码（openssl rand -hex 24）、BK_PUBLIC_URL
# .env 中 COMPOSE_FILE 已合并 production 覆盖；BK_HOST_PORT=8010（v1 占用 8000）
docker compose up -d db && docker compose run --rm migrate
BK_NEW_PASSWORD='…' docker compose run --rm -e BK_NEW_PASSWORD api \
  bookkeeper create-user --email <v1 管理员邮箱> --name <姓名> --superadmin
docker compose up -d api worker
curl -fsS http://127.0.0.1:8010/readyz
```

超级管理员与 v1 管理员使用同一邮箱：迁移时按邮箱复用该用户并设为账套所有者（其余 v1 用户沿用原 argon2id 密码哈希）。**想让所有人继续用 v1 的原密码登录时，跳过这一步**：迁移会把 v1 账号连同 argon2id 密码哈希一起带过来，v1 管理员成为账套所有者；超级管理员只在跨账套管理用户时需要，日常记账用不到。

## 2. 试迁移（只读 v1，不改任何数据）

```bash
# 用 SQLite 在线备份取一致快照（v1 运行中直接复制文件可能读到半写的 WAL）
docker exec book-keeper-api-1 python -c "import sqlite3; d=sqlite3.connect('/tmp/v1.db'); sqlite3.connect('file:/app/data/ledger.db?mode=ro', uri=True).backup(d); d.close()"
docker cp book-keeper-api-1:/tmp/v1.db /opt/bookkeeper/v1-snapshot.db && docker exec book-keeper-api-1 rm /tmp/v1.db
docker compose run --rm -v /opt/bookkeeper/v1-snapshot.db:/import/v1.db:ro \
  api bookkeeper legacy-migrate --source /import/v1.db --report-dir /data/migration
docker compose cp api:/data/migration ./migration-report     # 交给用户审阅
```

报告包含：映射与重分类、未迁移记录清单、舍入清单、往来方重命名、V1–V10 核对、30 笔抽样对照。本地快照的试迁移：全部迁移、无未迁移记录，V1–V10 全部通过（收入、成本费用、资金净流量与 v1 完全一致；手续费只有分以下的舍入差，原成本 / 管理费用中的手续费重分类到手续费科目）。账套主人自己的往来方改名与站点别名放在本地映射文件里（不进代码库），试迁移与正式迁移都加 `--mappings /import/mappings.json`（同样以只读方式挂载）。

## 3. 正式迁移（用户确认报告后）

1. 冻结 v1：停止导入脚本与自动写入；按 §2 再取一次快照 `v1-final.db`，重新试迁移确认无新增未迁移记录。
2. 备份：`deploy/scripts/backup.sh`（迁移前的 v2 也备份一次，便于重来）。
3. 执行：

```bash
docker compose run --rm -v /opt/bookkeeper/v1-final.db:/import/v1.db:ro \
  api bookkeeper legacy-migrate --source /import/v1.db --apply --report-dir /data/migration
```

   任何核对不通过都不会提交（整体回滚），按报告处理后重跑。报告开头列出新账套 ID。
4. 创建令牌：`docker compose exec api bookkeeper create-token --book <账套ID> --user-email <邮箱> --name claude --tier user_write --mcp`（AI 用，明文令牌只输出一次），按需另建 `--tier admin_write` 令牌。档位见 08 号 §3.3。
5. 运行检查：`POST /api/v1/books/{id}/checks:run` 或 MCP `run_checks`，全部通过。

## 3.1 AI 识别（可选）

导入里的“截图（AI）”来源把截图和 PDF 交给 AI 读成记录（06 号 §0.1）。不配置就不可用，其余功能不受影响。

有两种配置方式，可以并存：

1. **网页配置（推荐）**：`.env` 设 `BK_MASTER_KEY`（`openssl rand -hex 32`，≥ 32 个字符，api 与 worker 都要读到），然后管理员在 设置 → AI 模型 添加提供商（Anthropic 或 OpenAI 兼容）、点“测试连接”、在“任务分配”里给识别选模型与备用。密钥加密保存，只显示末 4 位，令牌与 MCP 改不了（19 号文档）。**`BK_MASTER_KEY` 要和数据库备份分开保存**；丢了或更换后，已存的密钥都要重新填写。
2. **环境变量**：下表的 `BK_AI_*`，作为没有分配提供商时的默认。

| 配置（`.env`） | 默认 | 说明 |
|---|---|---|
| `BK_AI_API_KEY` | 无 | Anthropic API 密钥；未设时也读 `ANTHROPIC_API_KEY`。api 与 worker 都要读到（compose 两者都用 `env_file: .env`） |
| `BK_AI_MODEL` | `claude-opus-5-5` | 读取用的模型 |
| `BK_AI_EFFORT` | `medium` | 推理强度（`low` / `medium` / `high`），越高越慢越贵 |
| `BK_AI_MAX_FILES` | `12` | 每次上传最多文件数 |
| `BK_AI_DAILY_FILES` | `200` | 每个账套每天最多读多少个文件，`0` 不限；超出返回 429 |
| `BK_MASTER_KEY` | 无 | 加密网页里保存的提供商密钥（≥ 32 个字符）；未设时网页不能保存密钥 |

- **隐私**：截图与 PDF 由**服务器**发到所分配的提供商（默认 Anthropic API `api.anthropic.com`），用于读取记录；启用前与用户确认，不要上传含完整卡密、密码的截图。服务器需能访问外网 HTTPS。
- **后台执行**：识别在 worker 里进行（每个文件一次请求，超时用提供商设置的值，环境变量方式为 240 秒），上传接口立即返回“识别中”，所以 **worker 必须在运行**（`docker compose up -d api worker`）；worker 停着时，批次在 10 分钟后转为识别失败“识别超时”（打开导入页时判断），worker 恢复后点“再读一次”即可。
- **超时**：nginx 的 `/api/` 设 `proxy_read_timeout 300s`，覆盖多文件上传与大文件解析；AI 识别本身不占这个请求。
- **成本**：截图按原分辨率识别，只有长边超过 2576 px 才缩到 2576 px（缩小会让数字变糊；整批截图原分辨率约 1 美元，读错金额的代价更大）；同一来源同一组文件重传直接返回已有批次，不会再调用 AI；`BK_AI_DAILY_FILES` 可限制每天的文件数。

## 3.2 数据库迁移 0012–0014

`0012_import_kinds`：导入来源类型增加 `redeem_page`、`ai_extract`，批次状态增加 `extracting`、`failed`（只改 CHECK 约束，不动数据）。随 `docker compose run --rm migrate` 执行，可回退（回退前须先撤销或删除用到这些值的来源与批次）。

`0014_token_tiers`：令牌改为四个档位（08 号 §3.3）。reader → 用户只读，bookkeeper → 用户读写，admin → 管理员读写；自定义令牌映射到其作用域覆盖的最高一档，没有 `ledger:read` 的直接吊销。迁移在输出里打印各档数量与每个自定义令牌的去向，**生产迁移时保存这段输出**。OAuth 授权码与刷新令牌一起换算。可回退（管理员只读回退为自定义）。

`0013_ai_providers`：新增 `ai_providers`（提供商，密钥为密文）与 `ai_usage`（每次调用的 token 与费用估算）两张表，不动已有数据，可回退。

## 4. 接入外部 AI

- 支持自定义请求头的客户端（Claude Code、Codex CLI、Cursor 等）用令牌：

```bash
claude mcp add --transport http bookkeeper https://<v2 入口>/mcp --header "Authorization: Bearer $BK_TOKEN"
```

- 只支持 OAuth 的远程连接器（claude.ai 网页 / 桌面 / 手机的“自定义连接器”、ChatGPT 连接器）：`.env` 设 `BK_OAUTH_ENABLED=true`（默认开启于 `.env.example`），nginx 加上 OAuth 两段 location，然后在客户端添加连接器 URL `https://<v2 入口>/mcp`，按提示登录 bookkeeper、选择账套与权限档位（建议“用户读写”）。授权生成的令牌显示在令牌管理中（名称“OAuth · 客户端名”），吊销即断开。

写入立即生效（2026-10-19 起没有“预览 → 确认”）；AI 写错时用 `undo_change_set` 撤回整次写入，或 `restore_transaction` 恢复删除的交易。

## 5. nginx

`deploy/nginx/bookkeeper.conf` 中的 `/api/`、`/mcp`、`/healthz`、`/readyz`、`/.well-known/oauth-`、`/oauth/` 与 `/` 片段放入 v2 入口的 server 块（代理到 127.0.0.1:8010，`/mcp` 关闭缓冲，`/api/` 读超时 300 秒）。镜像内含前端（`BK_WEB_DIR=/app/web`），API 进程直接提供页面：`index.html` 不缓存并带 CSP，`/assets/*` 带内容哈希、缓存一年；同源访问，无需 CORS。v1 的 server 块保持不变，直到前端切换；切换后把 `BK_HOST_PORT` 改回 8000 或保持 8010 并同步 nginx。

## 6. 备份与恢复演练

| 任务 | 命令 | 频率 |
|---|---|---|
| 备份 | `cd /opt/bookkeeper && deploy/scripts/backup.sh` | cron 每日 03:00 |
| 恢复演练 | `deploy/scripts/restore-check.sh backups/db/<最新>.dump` | 每周 |
| 异地副本 | rsync `backups/` 到另一台主机（可 age 加密） | 每日 |

## 7. 回退

- v2 尚未成为唯一数据源时：停止 v2 容器即可，v1 不受影响。
- 正式迁移后发现问题：用迁移前备份恢复 v2 空库，修正后重新迁移；v1 快照始终保留。

## 8. 前端切换

前端位于 `v2/web`（React + Vite），随镜像一起构建，见 v2/README.md “前端”。验收步骤：

1. 在 v2 入口（独立主机名或端口）用管理员账号登录，逐项检查 概览 / 交易 / 统计 / 导入 / 设置；
2. 用真实账单走一遍：上传 → 补全分类 → 完成导入 → 统计下钻；改一笔、删一笔、撤销；
3. 确认后 nginx 的 bill.example.com 指向 v2，v1 只读保留 30 天后停止并归档数据库与报告。

以上切换与生产部署都需用户确认后执行。

## 9. 代码仓库与推送

公开仓库只推孤立分支 `v2`：它从去掉真实业务信息后的代码树起步（单个初始提交），之后在本地以 `v2` 为基线开发，推送都是正常的快进，不用 force。含真实数据的旧提交历史只留在本地（标签 `private-history`），永不推送；远端 `main`（v1 代码）与 v1 的其他分支不动。真实数据（v1 快照、往来方映射文件、导出、截图）只放在 git 忽略的目录里，推送前用 grep 核对没有真实站点名、真实数字、域名与凭据。

