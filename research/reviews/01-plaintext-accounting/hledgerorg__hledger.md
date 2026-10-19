# hledgerorg/hledger

- 分类：01 纯文本复式记账
- 语言 / 许可证 / 最近提交：Haskell / GPL-3.0 / 2026-10-18（非常活跃）
- 审查范围：`hledger-lib/Hledger/Data/{Types,Balancing,Valuation,Lots,TransactionModifier,PeriodicTransaction,JournalChecks}.hs`、`hledger/Hledger/Cli/Commands/{Check,Import,Close,Balance*}.md`、`hledger/hledger.m4.md`（手册：CSV rules、valuation、costs、lots、auto postings）

## 定位

Ledger 的 Haskell 重写与增强：纯文本日记账 + 强校验 + 强大的 CSV 导入规则 + 多种估值口径的报表，提供 CLI、TUI、Web（含 JSON API）。

## 数据模型

- Journal = 指令（account/commodity/payee/tag 声明、价格 P、定期交易 `~`、自动过账 `=`）+ Transaction（日期、**可选的第二日期**、状态 `*`/`!`、代码 code、描述 description（可拆为 payee|note）、标签、postings）；
- Posting：账户、金额（可多币种）、**成本 `@`/`@@`**、余额断言/余额赋值（`= X`、`== X` 严格单币种、`=*` 含子账户）、posting 级日期、标签；
- 账户类型可声明（Asset/Liability/Equity/Revenue/Expense/Cash/Conversion），供报表自动分类；
- 金额为任意精度十进制，**每个商品的显示精度从数据推断或由 commodity 指令指定**。

## 记账逻辑与算法

- **平衡**：自动推断缺失金额与换算价；`balanced`（严格）模式禁止隐式换算，跨币种必须写成本或权益换算分录（`equity:conversion`）——防止因笔误产生的错误汇率。
- **估值（valuation）**：`--value=cost|then|end|now|日期`，可指定目标币种；价格来自 P 指令与交易成本推断——同一份数据可产出“按记账汇率”“按当时汇率”“按期末汇率”的报表。
- **批次与资本利得**：lot 子账户、成本基础、已实现损益校验（`check lots`）。
- **自动过账（auto postings）**：按查询匹配交易，自动追加 posting（如按比例计提手续费/税），可只作用于预测交易。
- **定期交易 / 预测**：`~ monthly` 规则生成预测交易与预算。
- **结账（close）**：生成期末结转与期初开账分录，`--assert` 自动写入余额断言。
- 报表：balance（多期、累计/期间/历史余额）、balancesheet、incomestatement、cashflow、aregister（单账户流水含运行余额）、activity、roi 等，均可按查询过滤。

## 追溯与审计

- 文本 + Git；每个错误报告带文件与行列，并给出上下文片段。

## 导入、分类与对账（重点）

- **CSV rules 文件**：`source`（可带清洗管道）、`archive`（导入后归档原始文件）、`skip`、`date-format`、`timezone`、`decimal-mark`、`fields`（命名字段并映射到 date/description/amount/account1…）、字段赋值（`%字段` 插值）、**`if` 条件规则（按字段正则匹配，多个匹配器可 AND/OR，支持捕获组 `\1`）设置科目/备注或跳过记录**、`ifs` 表格式规则、`merge`（多条记录合并为一笔交易）、`balance-type`（从对账单生成余额断言）、`include`（规则复用）。规则评估顺序有明确文档（顶层规则后者覆盖前者，条件规则自上而下）。
- **增量导入去重**：`import` 记住每个数据源最后导入的日期与当天条数（`.latest.*` 文件），只追加新记录；`--dry-run` 预览。
- **对账**：余额断言 + `recentassertions` 检查（每个有断言的账户在最近一笔记录前 7 天内必须有断言，督促定期对账）。

## 校验体系

- 默认：可解析、平衡（含推断）、余额断言、批次合法；
- 严格模式：禁止隐式换算、商品必须声明、账户必须声明；
- 可选：标签/收付款方必须声明、文件内日期有序、近期断言、叶子账户名唯一；可写自定义检查脚本。

## API 与扩展

- hledger-web 提供 JSON API（读取交易/账户、添加交易）；附加命令（add-on）机制。

## 可借鉴

- [HL1] 分级校验（默认/严格/可选）且可单独运行 —— 对应新系统的“校验规则集”与 `/checks` API。
- [HL2] 跨币种必须显式写换算（成本或权益换算分录），禁止隐式换算。
- [HL3] 多种估值口径（成本、当时、期末、现在、指定日）× 目标币种。
- [HL4] CSV 导入规则 DSL：字段映射 + 条件规则（正则、多匹配器、捕获组）+ 合并多行 + 跳过 + 从对账单生成余额断言 + 原始文件归档 —— 导入模块的核心参考。
- [HL5] 增量导入：记录每个来源的导入水位线（最后日期+当日条数），只追加新记录；dry-run 预览。
- [HL6] 自动过账规则（按查询匹配交易追加分录，如按比例计手续费）。
- [HL7] 结账命令同时生成断言；“近期必须有断言”的督促式检查。
- [HL8] 账户类型声明驱动报表分类；交易状态（未确认/待定/已确认）。
- [HL9] 交易与 posting 都可带独立日期（如付款日 vs 到账日）。
- [HL10] 错误信息带精确位置与上下文。

## 不采用 / 风险

- 文本文件存储的并发与权限问题同 beancount；GPL-3.0 只参考设计。
- CSV 规则 DSL 对非技术用户门槛高——新系统需要可视化规则编辑 + 规则测试（给样例行看结果）。

## 对新系统的启示

1. 导入模块：数据源（来源类型 + 解析配置）→ 字段映射 → 条件规则（匹配器 + 动作：设置交易类型/科目/维度/备注、跳过、合并）→ 预览 → 写入；原始文件归档并哈希防重。
2. 每个数据源维护导入水位线与外部 ID 去重。
3. 报表引擎支持估值口径参数 `valuation=cost|txn_date|period_end|as_of:<date>` 与 `currency=<目标币种>`。
4. “对账新鲜度”检查：关键账户 N 天内必须有余额核对记录。
5. 规则引擎支持“自动追加分录”（如按渠道比例自动生成手续费分录）。
