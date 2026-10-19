# mayswind/ezbookkeeping

- 分类：06 个人财务（自托管，中国作者，中文友好）
- 语言 / 许可证 / 最近提交：Go + Vue / MIT / 2026-10-15（近 6 千星）
- 审查范围：`pkg/{models,converters,duplicatechecker,exchangerates,mcp,llm,api/model_context_protocols.go,api/tokens.go}`、`skills/ezbookkeeping`

## 定位

轻量自托管记账（单用户/家庭）：多账户、多币种、分类、标签、模板、地理位置、图片；**导入格式最全的开源记账项目之一**，并内置 MCP 服务与 Agent Skill。

## 数据模型

- Transaction：`Amount int64`（最小单位）、类型（收入/支出/转账/余额调整）、分类、账户、**`TransactionTime` + `TimezoneUtcOffset`（保存原始时区）**、**转账的 `RelatedId` / `RelatedAccountId` / `RelatedAccountAmount`（跨币种转账两端金额）**、隐藏金额、备注、经纬度、`CreatedIp`、软删除；唯一约束 (uid, transaction_time)（同用户同一毫秒唯一，防止重复提交）；
- Account（含子账户、币种、余额）、Category（两级）、Tag + TagGroup、TransactionTemplate（含定时模板）、TransactionPictureInfo（附件）、ExchangeRate（用户自定义汇率）、TokenRecord（令牌含类型：普通、MCP、API）。

## 导入（重点）

- 转换器覆盖：**支付宝（App/Web CSV）**、**微信支付（CSV/XLSX）**、**京东**、**随手记（feidee）**、Beancount、Firefly III、GnuCash、OFX、QIF、IIF、CAMT.053、MT940、通用 CSV/Excel 自定义映射（保存映射方案）、**AI 识别（LLM 识别截图/票据生成交易表）**；
- 导入流程：解析 → 映射（账户/分类/标签名称匹配，可批量替换）→ 预览与勾选 → 批量写入；
- **重复检查器**：按操作类型（新建交易、导入交易、新建账户…）对“同一用户 + 相同请求”在时间窗口内去重，防止重复提交。

## 汇率

- 内置 20+ 家央行数据源（欧洲央行、各国央行）+ 用户自定义数据源；用户可设置基准币种。

## MCP 与 Agent

- MCP 工具：`add_transaction`（**支持 dry_run，返回过账后账户余额**）、`query_transactions`、`query_all_accounts`、`query_all_accounts_balance`、`query_all_transaction_categories`、`query_all_transaction_tags`、`query_latest_exchange_rates`；
- 参数按名称（账户名、分类名）而非 ID，降低 AI 使用难度；金额为字符串；
- MCP 令牌是独立的令牌类型，可单独吊销；
- 提供 Agent Skill（SKILL.md + 跨平台脚本）调用 API。

## 可借鉴

- [EZ1] 支付宝 / 微信 / 京东等国内账单导入解析器（字段含义、状态过滤、收支方向判断）。
- [EZ2] 交易时间 + 原始时区偏移。
- [EZ3] MCP 写工具的 dry_run 与“过账后余额”反馈；参数支持名称解析。
- [EZ4] MCP/API 令牌分类型管理与吊销。
- [EZ5] 请求级重复提交检查。
- [EZ6] AI 识别截图生成交易表（作为导入的一种来源，仍需预览确认）。
- [EZ7] Agent Skill（技能文档 + 脚本）作为 MCP 之外的另一种 AI 接入方式。

## 不采用 / 风险

- 单式（收入/支出/转账），无科目体系与期间。

## 对新系统的启示

1. 导入源插件化：微信、支付宝、卡网订单（链动/云猫）、上游站兑换记录、Stripe 结算、银行/公司卡账单……每个来源一个解析器 + 测试样例；
2. MCP 工具参数允许“名称或 ID”，服务端负责解析并在歧义时返回候选；
3. 写工具统一 `dry_run`，返回将生成的分录与余额变化；
4. 交易保存原始时区偏移，按北京时间做日期归属（与现行规则一致）；
5. 提供 Skill 文档（面向 Claude Code 等），与 MCP 并存。
