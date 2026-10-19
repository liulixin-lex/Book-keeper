# 07 报表、查询、导出与健康检查

## 1. 原则

1. 报表只有一个实现：应用层 `services/reports.py` 调用领域层计算器；REST、MCP、导出、前端共用。
2. 报表只读取有效交易的当前分录：已删除的交易、修改前的旧分录都不计入（给出 `as_known_at` 时改为回看当时已记录的全部分录，冲销相抵）。
3. 分类由科目 `classification` + `role` 决定，不依赖编码或名称。
4. 每份报表输出**数据集指纹**与参数快照，可复算、可证明。
5. 金额输出同时给整数最小单位与展示字符串，声明以整数为准。

## 2. 公共参数

| 参数 | 说明 | 默认 |
|---|---|---|
| `date_from` / `date_to` 或 `as_of` | 业务日期区间 / 时点 | 当月 / 今天 |
| `period` | `2026-10`、`2026-Q4`、`2026` 等快捷写法 | |
| `valuation` | `historical`（入账时冻结的本位币，默认）/ `original`（不折算，按商品分列） | historical |
| `target_commodity` | 展示币种（`historical` 时须为本位币） | 本位币 |
| `basis` | `accrual`（默认）/ `cash`（只统计涉及现金类角色科目的分录） | accrual |
| `filter` | 查询 DSL（交易类型、往来方、维度、科目、标签…） | |
| `group_by` | 维度分组：`account`、`counterparty`、`dimension.<type>`、`transaction_type`、`day` / `week` / `month` | 依报表 |
| `as_known_at` | 只计入 `recorded_at ≤` 该时间的分录（双时间查询） | 现在 |
| `include_zero` | 显示零余额行 | false |
| `depth` | 科目层级展开深度 | 全部 |

## 3. 报表目录

2026-10-19 精简后只保留经营统计需要的报表（17 号文档）；资产负债表、现金流量表、外币敞口、总账、明细账、未清项账龄、对账状态、变更报告已去掉。

### 3.1 当前实现

一个通用聚合（`reports/query`，对每笔有效交易的当前分录按维度汇总）支撑全部报表；每行附 `drilldown`：可直接用作 `GET transactions` 的参数（日期、渠道、科目、往来方、类型），实现报表 → 明细的互联。

| 接口 | 内容 |
|---|---|
| `reports/summary` | 概览：利润、各币种资金余额、前五渠道、前五站点、需留意事项（估算手续费笔数、待核对款项余额） |
| `reports/income-statement` | 利润表：营业收入、营业成本、毛利、销售 / 管理 / 财务费用、营业利润、营业外收支、净利润；`columns=day/week/month/quarter/year` 逐期列 |
| `reports/operations` | 经营日报 / 周报 / 月报：销售收入、其他收入、手续费、额度成本、其他成本、期间费用、利润，及销售 / 采购 / 支出笔数 |
| `reports/sales` | 销售分析（按渠道，可逐期）：订单数、毛额、退款、净销售、手续费、到账、费率、客单价 |
| `reports/fees` | 手续费分析（渠道 × 类型）：手续费、计费基数、实际费率、其中估算 |
| `reports/credit-purchases` | 额度采购分析（按站点，可逐期）：笔数、面值、手续费、实付、退款、净成本、额度数量、单位额度成本 |
| `reports/trial-balance` | 试算平衡表：每个科目 × 商品的期初、借方、贷方、期末 |
| `reports/query` | 分组：`year / quarter / month / week / day / account / top_account / classification / channel / counterparty / transaction_type / line_role / commodity / is_estimate`；度量：`base_amount / amount / debit / credit / count / quantity`；`sign=natural`（各科目按正常方向显示）或 `debit` |

## 4. 计算与性能

- **余额**：期初余额 = 期初日之前的 `daily_balances` 发生额之和；区间发生额来自 `daily_balances`；需要维度过滤或 `as_known_at` 时直接聚合 `journal_lines`（带索引）。
- **一致性**：`daily_balances` 只存发生额、入账时同事务累加，因此任何时刻都与分录行一致，无需失效重算；`daily_balances` 检查项每日复核。
- **实测**（M1，125 万分录行）：入账 p95 10.7 ms；试算平衡 p95 5 ms；`as_known_at` 试算平衡 p95 709 ms（`scripts/bench_ledger.py`）。
- **一致性**：报表在 `REPEATABLE READ` 只读事务中执行，结果对应同一快照；同时返回 `ledger_seq`（快照时的最大分录序号）。

## 5. 数据集指纹

```
fingerprint = SHA-256( canonical_json({"report": code, "params": 规范化参数, "book_id": …,
                                       "ledger_seq": 快照最大 seq, "head_hash": 最新分录哈希}) )
```

每份报表返回 `meta.fingerprint`、`meta.ledger_seq`、`meta.params`：相同参数、相同账本状态得到相同指纹；任何新分录都会改变 `ledger_seq` 与 `head_hash`。报表快照保存与复算比对接口未实现（指纹已足够判断“报表之后账本是否变化”，变化内容可查变更集 `change-sets`）。

## 6. 受限聚合查询（`query_ledger`）

供 API 与 MCP 使用的安全查询，替代任意 SQL：

```jsonc
{
  "measures": ["base_amount_sum", "amount_sum", "line_count", "quantity_sum", "debit_sum", "credit_sum"],
  "group_by": ["month", "dimension.channel", "counterparty", "account", "transaction_type", "line_role", "commodity"],
  "filter": { "all": [ { "field": "account.classification", "op": "eq", "value": "revenue" },
                       { "field": "effective_date", "op": "date_between", "value": ["2026-09-01", "2026-10-31"] } ] },
  "order_by": [ { "field": "base_amount_sum", "dir": "desc" } ],
  "limit": 200,
  "as_known_at": null
}
```

- 维度与度量为白名单，字段经参数化 SQL 生成；`limit ≤ 1000`；单次执行超时 5 秒；
- 结果附指纹；可用维度、度量、字段说明通过资源 `ledger://schema/query` 发布。

## 7. 导出

`GET /books/{id}/exports/{csv|xlsx|beancount|json}?date_from=&date_to=`（区间省略则为全部），MCP `export_ledger`（存入文件库并返回下载地址与现场导出地址），CLI `bookkeeper export`。按分录序号流式读取，导出内容只取决于数据（文件头记录截至的分录序号），相同数据得到相同文件。

| 格式 | 内容 |
|---|---|
| CSV | 每行一条分录行：凭证号、业务日期、分录类型、交易号、交易类型、摘要、行号、科目、商品、借 / 贷、本位币借 / 贷、汇率、往来方、渠道、行用途、统计数量、行备注、外部单号、记录时间；UTF-8 BOM，Excel 可直接打开 |
| XLSX | 工作表“分录”（同 CSV，金额为数值）与“科目” |
| Beancount | `commodity`、`open`（按科目层级命名，如 `Expenses:5401-主营业务成本:02-账号`）、每张分录一笔交易（往来方、摘要、元数据 entry / transaction / type / kind / external-ref，行元数据 role / quantity / memo）；外币行 `原币 @@ 本位币金额`，仅本位币金额的行（尾差、汇兑损益）记为本位币，因此每笔交易按本位币精确平衡；修改与删除留下的冲销 / 重记分录照样导出。测试用 beancount 3 的加载器校验（0 错误），真实迁移数据同样通过 |
| JSON | 账套、科目表与全部分录（含行），金额为十进制字符串 |

月度可读归档：worker 每日检查已结束月份，分录有变化（最大分录序号变化）时重写 `<data>/archive/<账套>/<YYYY-MM>/ledger.beancount`、`journal.csv` 与 `manifest.json`（含 SHA-256）。

## 8. 健康检查目录

| 代码 | 级别 | 内容 |
|---|---|---|
| `trial_balance_zero` | error | 各商品 Σamount = 0、Σbase_amount = 0（全账套） |
| `entries_balanced` | error | 每张分录各商品与本位币平衡（数据库约束的独立复核） |
| `hash_chain` | error | 分录哈希链与账套审计哈希链连续、可重算 |
| `sequence_gaps` | error | 分录 seq 与凭证号无断号 |
| `balances_cache` | error | `account_balances` 与分录行重算一致 |
| `daily_balances` | error | 每日发生额与分录行重算一致 |
| `immutability_guard` | error | 数据库不变量触发器齐全且启用 |
| `orphans` | error | 交易状态与分录一致：每笔交易都有当前分录；已入账的当前分录未被冲销，已删除的当前分录已被冲销 |
| `suspense_zero` | warning | 待核对款项余额为 0 |
| `normal_side` | warning | 科目余额方向异常（如收入借方余额、资金为负） |
| `duplicate_risk` | warning | 同日、同类型、同往来方、同金额，且外部单号、订单号、发生时间都无法区分的有效交易对；确是两笔的，补上订单号或时间即不再提示 |

估算手续费、未处理来源记录、待确认匹配由待办（`work-items`）覆盖，不单列检查。

运行方式：`POST /checks:run`（全部或指定代码，结果写 `check_runs` / `check_results`）、每日定时任务、CLI `bookkeeper run-checks`。每项结果含数量与最多 50 条样例。

## 9. 二分定位差异（规划）

输入：一个可计算的“期望值”来源（如对账单逐日余额、外部报表日合计）与科目 / 报表项目、日期区间。算法：在区间上二分，比较“截至中点日期的账面值 vs 期望值”，收敛到第一个出现差异的日期，返回该日的分录行与来源记录对照。原基于余额断言的实现已随对账功能去掉（17 号文档）；需要时可由 AI 用 `query_ledger` 按日汇总完成同样的定位。
