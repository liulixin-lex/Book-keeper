# juspay/hyperswitch-reconciliation（Hyperswitch Recon）

- 分类：07 支付对账引擎
- 语言 / 许可证 / 最近提交：Rust (Actix + Diesel + PostgreSQL) / Apache-2.0 / 2026-10-16
- 审查范围：`ai-docs/{INDEX,RULES,CRITICAL-PATHS}.md`、`ai-docs/domains/{reconciliation,recon-rules,transactions,ingestion,transformation,audit-trail,accounts}/*`、`ai-docs/patterns/HANDLE-MONEY.md`、`migrations/`

## 定位

Juspay（Hyperswitch 支付编排）的对账服务：从各支付服务商（PSP）拉取/接收结算文件 → 转换为暂存条目 → 按规则与预期匹配 → 生成对账交易与异常，全部带审计。

## 数据模型

- 商户 → 业务配置（profile）→ **账户（accounts，余额 = 期初 + 贷 − 借）**；
- **Ingestion**（文件获取配置与历史：PSP 文件、Webhook、存储）→ **Transformation**（文件到暂存条目的转换配置与历史）→ **Staging Entry**（暂存条目：金额 MinorUnit i64、币种、**生效时间（必填）**、元数据（加密）、处理模式 transaction / confirmation、状态）；
- **Recon Rule**：触发条件（trigger）、优先级、源账户/目标账户、**搜索标识（source/target 字段映射，用于找对方）**、**匹配规则（字段比较、容差）**；策略（版本化枚举）：One-to-One（单对单、单对多、多对单、多对多）、One-to-Many；
- **Transaction（对账交易，带版本号）→ Entries（expected 预期条目 / confirmed 已确认条目）→ Search Expectations（等待对方出现的检索键）**；
- 异常管理（人工对账 API，含 v2 增量接口）、审计轨迹（按事件分组、按 profile 隔离）、元数据 schema 与检索组。

## 对账流程（重点：预期-确认模型）

1. **交易模式**（来源侧记录到达，如订单/付款）：找到“该账户为来源”的规则，按触发条件筛选、按优先级选一条；生成对账交易 + **每个目标一条“预期条目”（方向相反）** + 检索期望；暂存条目标记已处理；
2. **确认模式**（目标侧记录到达，如银行结算/到账）：按“该账户为目标”的规则，用检索标识在多个目标中查找预期；匹配规则判定；
3. **交易演进**：旧版本交易/条目/期望整体归档，创建**新版本**交易：已确认条目 + 剩余未确认的预期条目；
4. 状态判定：匹配失败 → **Mismatched**；通过但仍有剩余预期 → **Expected**；全部确认 → **Posted**；处理异常 → 新版本 **NeedsManualReview**；
5. 可选哈希去重（按转换配置）：重复暂存条目进入人工复核。
- 金额规范：**永不使用 f64，一律 MinorUnit(i64) + 币种**，币种不一致的运算直接报错；所有表软删除；时间存 UTC，业务时区为配置元数据。
- 面向 AI 的开发文档体系（INDEX → RULES → CRITICAL-PATHS → 领域 AGENT-NOTES）。

## 可借鉴

- [HS-1] **预期-确认模型**：来源侧记录生成“预期条目”，目标侧记录到达后确认；部分确认 → Expected，全部确认 → Posted，不符 → Mismatched，异常 → 人工复核。
- [HS-2] 对账交易版本化（旧版本归档、新版本演进），过程可追溯。
- [HS-3] 规则 = 触发 + 优先级 + 检索标识 + 匹配规则 + 策略（1:1/1:N/N:1/N:N），规则 schema 版本化。
- [HS-4] 数据管道：获取（ingestion）→ 转换（transformation）→ 暂存（staging）→ 对账。
- [HS-5] 金额类型强约束（i64 最小单位 + 币种，异币种运算报错）；生效时间必填。
- [HS-6] AI 开发文档分层（规则、关键路径、领域笔记）。

## 不采用 / 风险

- 多商户/多 profile 层级对单主体不必要；元数据加密可按需。

## 对新系统的启示

1. 卡网订单（链动/云猫）到达 → 生成“预期兑换”（目标：对应上游站点，面值、时间窗）；兑换记录到达 → 确认；未确认的预期 = 已付款未兑换（在途），超时进入异常；
2. Stripe 收入到达 → 预期结算到账；银行/结算报告到达 → 确认；
3. 对账交易版本化 + 状态机（expected / matched / mismatched / needs_review / closed）；
4. 规则 schema 带版本号，变更可追溯。
