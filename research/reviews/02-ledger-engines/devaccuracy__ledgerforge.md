# devaccuracy/ledgerforge

- 分类：02 账本引擎（Blnk 衍生，增加 MCP 与 Agent 安全）
- 语言 / 许可证 / 最近提交：Go + PostgreSQL + Redis / Apache-2.0（开源核心 + 企业版）/ 2026-10-10
- 审查范围：`ARCHITECTURE.md`、`docs/{mcp,agent-safety,concepts,verification}.md`、`cmd/ledgerforge-mcp`、`model/`

## 定位

“面向 AI 原生资金流转的账本”：在 Blnk 的余额/交易/在途/对账/溯源能力之上，增加本地 MCP 服务、Agent 支出策略、密钥委托与独立审批、只读完整性重放。

## 数据模型

与 Blnk 一致（ledger / balance / transaction / identity / lineage / reconciliation），新增 **policy**（每个 API Key 的支出策略：币种+精度白名单、单笔上限、日限额、超额需审批阈值、允许的账簿/余额列表）与持久化的准入/审批决策。

## 记账逻辑与算法

- Posting = 来源借记 + 目标贷记（整数最小单位），余额 = 贷计数 − 借计数；在途计数单独维护；版本号检测并发更新。
- “已受理/已排队”与“已过账”是不同状态，接口如实区分。
- **交易控制字段不可变**：执行、溯源、策略相关字段与客户元数据分离，元数据更新不能改变已受理的执行参数。
- 拆分/批量的限额按币种聚合计算——拆单不能绕过单笔上限。

## 追溯与审计

- `internal/integrity`：基于一致性快照的只读会计重放，独立验证余额与过账记录一致。
- MCP 每次写工具调用产生结构化审计日志（stderr）。
- 架构测试用 import 图约束领域层不依赖 HTTP/框架。

## 导入、分类与对账

继承 Blnk 对账引擎（上传、规则、策略、进度）。

## API 与扩展（重点：MCP 设计）

- MCP 默认**只读**：查账簿、余额、交易、历史时点余额、资金溯源；分页上限 100。
- **高层任务型工具**而非裸 CRUD：`find_balance`（按标识+币种找账户）、`get_transaction_context`（交易 + 两端余额摘要）、`get_balance_at_time`（历史时点余额）。
- **MCP Resources**：`ledgerforge://ledgers/{id}`、`balances/{id}`、`transactions/{id}` 作为上下文资源。
- **MCP Prompts**：`investigate_balance`、`investigate_transaction`、`prepare_transfer`，引导 Agent 按正确流程操作。
- 所有结果都附带精确的 `*_minor` 整数字符串，明确告诉 Agent “不要用浮点数做会计判断”。
- 写工具需运营者显式 `--allow-write` 才注册；每次写调用要求 `confirm: true`（意图确认，不等于审批）；可绑定 API Key，按该 Key 的 scope 与策略逐次校验。
- `reference` 即幂等键；批量 1–100 笔，可原子。
- 委托密钥只能收窄父级权限，兄弟密钥共享父级日额度。

## 可借鉴

- [LF1] MCP 默认只读、写能力需运营者显式开启并按 API Key 的 scope 逐次鉴权。
- [LF2] 任务型 MCP 工具 + Resources + Prompts 的组合，而不是把 REST 接口一比一暴露。
- [LF3] 工具返回值同时给出精确整数（minor units）与展示值，并在描述中声明以整数为准。
- [LF4] 每次 MCP 写调用记录结构化审计（调用者、参数、结果）。
- [LF5] 交易控制字段与自由元数据分离，后者不能改变前者。
- [LF6] 只读完整性重放（独立验证账实一致）。
- [LF7] API Key 策略：额度上限、白名单、委托只收窄 —— 外部 AI 接入的限权模型。
- [LF8] 区分“已受理”与“已过账”。

## 不采用 / 风险

- 用户已要求去掉审批模块：新系统不做“超额需审批”的流程，改为“额度/范围限制 + dry-run + 批次可整体冲正”的安全模型。
- 支出策略中的日限额是支付场景的需求，记账场景只需要“允许写入的科目/类型范围”和“单批最大条数/金额”。

## 对新系统的启示

1. MCP 服务：默认只读；写工具需在服务端为该 Token 开启写权限；所有写工具支持 `dry_run`，返回预览后再用同一参数提交。
2. 工具设计以任务为中心：`search_transactions`、`get_account_balance(at=日期)`、`explain_transaction`（含分录、来源凭证、审计链）、`propose_entries`（按模板生成分录预览）、`post_entries`、`reverse_transaction`、`import_statement`、`reconcile`……
3. 金额字段双表示：精确字符串 + 最小单位整数；文档明确禁止浮点。
4. API Token 支持 scope（read / write:transactions / write:master-data / admin）与范围限制（可写的账簿、科目、交易类型）。
5. 提供 `verify_integrity` 只读重放接口（借贷平衡、余额重算、审计哈希链）。
