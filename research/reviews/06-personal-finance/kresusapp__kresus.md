# kresusapp/kresus

- 分类：06 个人财务（自托管，银行同步）
- 语言 / 许可证 / 最近提交：TypeScript (Node + TypeORM) / AGPL-3.0 / 2026-10-17
- 审查范围：`server/lib/{diff-transactions,duplicates-manager,filter-duplicate-transactions,rule-engine,alert-manager,poller}.ts`、`server/models/entities/*`

## 定位

通过 woob 等连接器定期拉取银行流水的个人财务管理器：标签/分类、规则、预算、阈值提醒、重复检测。

## 数据模型

- transactions（金额、日期、银行标签、用户自定义标签、类型、分类、**importDate（导入时间）**、是否定期交易生成）、accounts、access（银行连接）、rules（条件 + 动作）、alerts（余额/金额阈值提醒）、recurring-transactions、**duplicates-ignored（用户确认“不是重复”的交易对，永久记住）**、views（自定义视图）。

## 算法

- **同步差异（diff-transactions）**：新拉取的流水与已有流水做“完美匹配（金额+日期+标签）→ 打分匹配”，日期差 ≤ 2 天、标签相似度扣分（每处差异 −0.1，最低相似度 0.9）。
- **重复检测（duplicates-manager）**：只有金额相同（差 ≤ 0.001）才可能重复；**同一次导入中的两笔不算重复**（银行本身就有同日同额交易）；日期差超过阈值不算；两笔都是定期交易生成的不算；若两笔的自定义标签/类型/分类都已填写且不同，不算重复（可选）；标签不完全一致则降分；**用户标记“不是重复”的交易对写入 ignored 表，之后不再提示（阈值调整后也可以撤销忽略）**。
- 余额/交易阈值提醒（邮件/通知）。

## 可借鉴

- [KR1] 重复检测的负面规则（同批导入、定期交易、已人工分类不同 → 不是重复）。
- [KR2] “不是重复”的人工判定持久化（忽略对表），避免反复打扰。
- [KR3] importDate 与交易日期分开。
- [KR4] 阈值提醒。

## 不采用 / 风险

- 单式；AGPL。

## 对新系统的启示

- 去重引擎：硬条件（金额、币种、外部 ID）→ 负面规则 → 相似度打分 → “疑似重复”队列；人工判定（是/否重复）持久化为 `dedup_decisions`；
- 每条外部流水保存 `imported_at` 与导入批次。
