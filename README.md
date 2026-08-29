# Book keeper

[![CI](https://github.com/liulixin-lex/Book-keeper/actions/workflows/ci.yml/badge.svg)](https://github.com/liulixin-lex/Book-keeper/actions/workflows/ci.yml)
[![Release](https://img.shields.io/github/v/release/liulixin-lex/Book-keeper)](https://github.com/liulixin-lex/Book-keeper/releases/latest)

这是一个面向中转站运营账务的全栈管理系统。系统以 CNY 为本位币，使用复式记账总账统一计算经营视图与现金视图，支持多人协作、历史表格迁移、独立的收入/支出明细和确定性的 AI 记账工作流。前端采用 React、TypeScript、Vite、Tailwind CSS 与 GSAP，并与 FastAPI 同源部署。

## 核心约束

- 金额使用 8 位定标整数，汇率使用 12 位定标整数；API 返回十进制字符串，不返回 JSON 浮点数。
- 正式凭证必须至少包含两行且借贷平衡；已过账凭证和分录禁止修改，用户删除收入或支出时由应用同步清理完整关联数据。
- 收入按“实际到账金额 + 手续费 = 毛收入”入账；支出按“费用金额 + 手续费 = 实际支出”入账。
- 所有用户可见账务只分为收入和支出；退款、上游充值、订阅等业务含义由类别和来源信息表达，不产生独立记录类型。
- 现金视图只展示现金流入、现金流出和净现金变化，不存在清算中、待结算或待核对金额。
- 外币交易保存交易日汇率快照，历史凭证不会随最新汇率重算；支持 USD、EUR、GBP、JPY、KRW、SGD、PHP，公开参考价来自 Frankfurter 汇总的央行数据。
- AI Chat 模式只能调用只读领域查询；旧 Edit 入口拒绝写入，正式记账必须使用斜杠命令，经服务端提案、规则校验和人工确认后事务提交。正式冲正及高风险配置变更通过审批。
- AI 供应商创建、更新或删除、账本 AI 设置更新及用户角色或启停变更先生成待审批单，管理员批准后才在同一事务中生效。主数据中的手工汇率由记账员直接维护。

## 本地运行

要求 Python 3.12+ 与 SQLite 3.51.3+。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env.local
.\.venv\Scripts\ledger-admin.exe init-db
.\.venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000
```

生产前端位于 `http://127.0.0.1:8000/`，接口文档位于 `http://127.0.0.1:8000/docs`。首次管理员可以在页面中初始化工作区，也可以执行：

```powershell
.\.venv\Scripts\ledger-admin.exe create-admin --email admin@example.com --name 管理员
```

## 前端开发

要求 Node.js 22+。开发模式会把 `/api` 请求代理到本机 `8000` 端口：

```powershell
Set-Location frontend
npm ci
npm run dev
```

交付前验证并生成生产静态资源：

```powershell
npm run typecheck
npm run format:check
npm test
npm run build
```

生产构建输出到 `frontend/dist`。FastAPI 启动时会自动挂载该目录，因此无需单独部署第二个前端服务；Docker 镜像也会在构建阶段完成前端编译。

## AI 配置

管理接口支持配置协议、`base_url`、模型、API Key、自定义请求头、超时、能力标记和 `reasoning_effort`。支持：

- OpenAI Responses：`/v1/responses`
- OpenAI Chat Completions：`/v1/chat/completions`
- Anthropic Messages：`/v1/messages`

默认兼容地址为 `https://api.aiaimax.com/v1`。后台填写的 API Key 会用 `APP_SECRET_KEY` 派生密钥加密后保存；也可选择仅在运行时读取 `OPENAI_API_KEY`，密钥不会写入 SQLite。接口只返回 `api_key_source` 和 `has_api_key`，不会回传明文或密文。

新增或修改供应商默认先发送最小请求，实际验证协议、模型、地址和认证后再进入审批；离线预配置时可显式提交 `probe_before_save=false`。创建、修改和删除均在批准前不改变正式配置。普通与流式 AI 请求均支持 `Idempotency-Key`；Edit 写命令在模型交互期间只暂存，拿到有效最终答复后才在一个短事务中统一提交，任一命令失败则整批回滚。流式断线后可复用原运行记录，且只能精确重放断线前的写命令。成功后会返回真实的 `committed` 工具结果。账本管理员可编辑预填充的 `AGENTS.md`，并独立开关联网能力；联网默认关闭且仅 Chat 模式可用。

## 记账方式

日常账务只保留两种录入类型：收入和支出。用户可以在各自的明细页面直接录入，也可以在“AI 记账”中主动描述业务，由 AI 调用受限的账务命令。人工录入即代表资金已经实际收付并立即过账，不提供暂存状态。新记录统一进入当前系统账本和系统资金账户，不要求接入或选择外部支付、收款账户。

收入录入无需选择提供商；支出录入必须选择启用的提供商，并带出该提供商关联的支出类别。人工支出自动绑定当前登录用户名。收入和支出明细使用服务端分页，可显示数据库中的全部账单；支出还支持按成员筛选，并返回筛选范围内的总金额。系统不提供文件导入和自动分类规则。

“主数据管理”只保留收支类别、总账科目、提供商和汇率表。类别与提供商支持新增、编辑、启停和删除；提供商不再设置客户或角色身份，只需选择一个已启用的支出类别。已经被账单引用时只能停用，不能破坏历史关联。归属项目和业务标签不再作为公开模块或新记账字段。总账科目按《小企业会计准则》常用编号压缩为 10 个系统科目，由系统统一维护。

汇率表进入页面时会刷新最新公开参考价，也支持用户新增、编辑和删除手工汇率。手工汇率优先用于当日记账，下一工作日的新公开参考价会自然接替；参考价仅用于账务折算，不代表实际成交价。

外部编号用于确定性去重；无外部编号时使用业务指纹提示疑似重复，由记账用户明确确认后才能作为不同交易入账。

## 历史数据迁移

源表格保持只读。将自己的历史工作簿放入指定目录后，可使用以下命令幂等迁移：

```powershell
.\.venv\Scripts\ledger-admin.exe migrate-legacy --source .
```

重复执行不会增加已经迁移的记录。原始工作簿、数据库和备份不属于源码仓库，请始终保存在仓库之外。

## Docker 部署

只部署一个 API 实例，并让 API、维护进程和 SQLite 持久卷位于同一台主机。不要把数据库文件放到网络共享盘。

发布镜像位于 `ghcr.io/liulixin-lex/book-keeper`：

```powershell
docker pull ghcr.io/liulixin-lex/book-keeper:0.1.2
```

```powershell
# 在 .env 中至少设置一个足够长的随机 APP_SECRET_KEY
docker compose up --build -d
docker compose ps
```

镜像固定构建 SQLite 3.53.4。维护进程使用 SQLite Online Backup API 定期备份，不运行第二个 API 写实例。公网部署时应由 Caddy、Nginx 或云负载均衡器终止 TLS，并保持 `SESSION_COOKIE_SECURE=true`。SQLite 官方说明 `3.51.3` 起修复 WAL-reset 问题，因此启动时会拒绝更旧的运行时。

## 备份与恢复

```powershell
.\.venv\Scripts\ledger-admin.exe backup
# 恢复前停止 API 和 worker
.\.venv\Scripts\ledger-admin.exe restore --file .\backups\ledger-时间戳.db
```

备份和恢复都会执行 `PRAGMA integrity_check`。恢复会先写入同目录临时数据库，校验成功后再原子替换目标文件。

## 验证

```powershell
.\.venv\Scripts\ruff.exe check .
.\.venv\Scripts\mypy.exe app
.\.venv\Scripts\pytest.exe
Set-Location frontend
npm run typecheck
npm run format:check
npm test
npm run build
```
