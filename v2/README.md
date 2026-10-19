# bookkeeper v2

复式记账后端：REST API + MCP（外部 AI 接入）。设计文档见 [`../docs/00-README.md`](../docs/00-README.md)。

版本 2.0.0：后端 + Web 前端（`web/`）。

2026-10-19 精简：自用的中转站经营账，记账即入账，交易可直接修改、删除、恢复，账本只追加、随时可撤回；草稿 / 过账 / 复核 / 预览 / 结账 / 对账等已去掉（[`../docs/17-lean-ledger.md`](../docs/17-lean-ledger.md)）。

- **账本核心**：复式分录（多商品、本位币冻结、兑换腿与尾差）、凭证号与分录哈希链、只追加分录（修改与删除都是冲销 + 重记）、数据库层不变量（13 个触发器）、双时间查询（`as_known_at`）。
- **业务类型**：销售、销售退款、额度采购、费用支出、采购退款、资金划转、手工凭证、期初余额；版本化手续费规则；修改、删除、恢复、按新规则重算、解释链、撤销变更集。
- **导入**：微信、支付宝、Stripe、卡网订单、上游兑换记录、兑换码页面 PDF、通用表格与结构化记录，以及截图 / PDF 的 AI 识别（可选，后台由 Claude 读取，需 `BK_AI_API_KEY`）；去重、分类规则、对上已记过的交易（含当天合计）、最优配对、完成 / 撤销。
- **统计与导出**：概览、利润表、经营日报、销售 / 手续费 / 额度采购分析、试算平衡、通用汇总（每行可反查明细）；CSV / XLSX / Beancount / JSON 导出与月度归档；11 项健康检查。
- **外部 AI**：`/mcp`（Streamable HTTP）35 个工具、资源与提示词；`dry_run`、`idempotency_key`、写入即生效可撤回、限流与调用日志；令牌或 OAuth 2.1（claude.ai、ChatGPT 等远程连接器）。
- **运维**：Compose 部署、生产配置自检、备份与恢复演练脚本、v1 数据迁移（真实数据全部迁移并通过核对）、接口契约快照（`contracts/`，测试保证与代码一致）。

接口清单见 [`../docs/16-interface-index.md`](../docs/16-interface-index.md)（由 `scripts/contracts.py` 生成）。

性能基准：`uv run python scripts/bench_ledger.py`（125 万分录行：记账 p95 ≈ 11 ms，试算平衡 p95 ≈ 5 ms）。

## 本地开发

需要：uv、PostgreSQL 18（`initdb`/`pg_ctl` 在 PATH 中；测试会自动启动临时集群）。

```bash
uv sync                      # 安装依赖（Python 3.14）
uv run pytest                # 全部测试（自动启动临时 PostgreSQL）
uv run ruff check src tests migrations scripts && uv run mypy
uv run python scripts/contracts.py   # 接口变化后更新快照与 16 号文档
```

使用外部数据库运行测试：`BK_TEST_DATABASE_URL=postgresql+psycopg://user:pass@host/postgres uv run pytest`。

本地运行：

```bash
export BK_DATABASE_URL=postgresql+psycopg://postgres@localhost/bookkeeper_dev
uv run bookkeeper migrate
BK_NEW_PASSWORD='至少十二位的密码' uv run bookkeeper create-user --email you@example.com --name 你 --superadmin
uv run bookkeeper create-book --name 主账套 --owner-email you@example.com
uv run bookkeeper create-token --book bk_… --user-email you@example.com --name 本地 --preset reader
uv run bookkeeper serve --port 8000      # API：http://127.0.0.1:8000/api/v1/docs
uv run bookkeeper worker                 # 后台任务
```

## 前端

`web/`：React 19 + Vite + TypeScript + Tailwind v4 + GSAP。界面文案以 `docs/14` 为准；记一笔由交易类型的 `input_schema` 驱动，录入时实时 dry-run，直接显示手续费、到账与折合金额。设计规范见仓库根目录 `DESIGN.md`。

```bash
cd web
npm install
npm run dev                  # http://127.0.0.1:5173，/api 代理到 BK_API（默认 http://127.0.0.1:8010）
npm run build                # 产物 web/dist；API 设 BK_WEB_DIR=web/dist 即同源提供页面
npm test                     # 单元测试（vitest）
node scripts/e2e.mjs         # 端到端冒烟：把开发库复制成临时库 bookkeeper_e2e，构建前端并由 :8011 上的 API 提供（生产路径，含 CSP），结束即删除；开发库不留测试数据
                             # BK_WEB=http://127.0.0.1:5173 node scripts/e2e.mjs 则直接打已运行的服务（其账本会被写入）
node scripts/a11y.mjs dark   # axe 无障碍扫描（light / dark）
```

五个模块：

| 模块 | 内容 |
|---|---|
| 概览 | 本期利润（较上期）、每日收入 / 成本 / 利润图、各币种余额、渠道销售、上游采购、最近记录、待处理 |
| 交易 | 搜索与筛选、按日分组；详情里直接修改、删除（带撤销）、恢复，以及修改历史 |
| 统计 | 趋势、渠道、上游、支出构成、手续费；每一行都能下钻到对应交易 |
| 导入 | 选来源 → 上传账单 → 补全规则没认出的记录 → 完成导入（可整批撤销） |
| 设置 | 往来方、渠道、收支分类、手续费规则、分类规则、导入来源、币种与汇率、AI 接入、操作记录、账户与数据 |

记一笔：侧栏按钮、快捷键 N 或手机底栏的 ＋。所有写入立即生效，提示条上可撤销；没有确认对话框。

## 部署（概要）

`compose.yaml`（PostgreSQL 18 + migrate + api + worker；api 镜像内含前端）+ `compose.production.yaml`；环境变量见 `.env.example`；nginx 片段见 `deploy/nginx/bookkeeper.conf`；首次部署、v1 迁移与切换步骤见 [`../docs/15-deployment-runbook.md`](../docs/15-deployment-runbook.md)。生产部署前需用户确认。

## 目录

| 路径 | 内容 |
|---|---|
| `src/bookkeeper/domain/` | 纯函数：分录构建、业务类型、手续费、汇率、规则引擎、匹配算法、权限、显示文案 |
| `src/bookkeeper/services/` | 应用层用例（REST 与 MCP 共用） |
| `src/bookkeeper/api/` | REST 接口、认证、错误格式、幂等写入 |
| `src/bookkeeper/mcp_api/` | MCP 服务、工具、资源与提示词、OAuth 2.1 |
| `src/bookkeeper/importers/` | 导入解析器 |
| `src/bookkeeper/migration/` | v1 数据迁移 |
| `src/bookkeeper/db/` | ORM 模型、会话、应用账号权限 |
| `src/bookkeeper/jobs/` | 任务队列、worker、内置任务 |
| `migrations/` | Alembic 迁移 |
| `deploy/` | nginx 片段、数据库初始化、备份与恢复演练脚本 |
| `contracts/` | OpenAPI 与 MCP 工具快照 |
| `tests/` | 单元测试与基于真实 PostgreSQL 的接口测试 |
| `web/` | Web 前端（React + Vite），构建产物由 API 同源提供 |
