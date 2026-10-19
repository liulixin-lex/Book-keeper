# pgr0ss/pgledger

- 分类：02 账本引擎（纯数据库实现）
- 语言 / 许可证 / 最近提交：PL/pgSQL / MIT / 2026-10-16
- 审查范围：`README.md`、`pgledger.sql`、`examples/`

## 定位

全部逻辑写在 PostgreSQL 表、函数和视图里的复式账本，任何语言都能用，并能与业务写入处在同一个数据库事务中。

## 数据模型

- `pgledger_accounts`：名称、币种、`balance NUMERIC`、`version`、`allow_negative_balance` / `allow_positive_balance`、metadata；
- `pgledger_transfers`：from/to 账户、`amount NUMERIC`（CHECK > 0 且有限、from≠to）、`created_at`（写入时间）+ `event_at`（业务发生时间）、metadata；
- `pgledger_entries`：每笔转账两条分录，记录 `amount`（带符号）、`account_previous_balance`、`account_current_balance`、`account_version`；
- ID 用带前缀的 ULID（`pgla_`、`pglt_`、`pgle_`），可读且时间有序。

## 记账逻辑与算法

- 创建转账时按账户 ID 排序加行锁（避免死锁），更新余额与版本，写两条分录，检查余额约束；
- 批量转账按数组顺序逐条应用，每条后检查余额约束，任何一条失败整批回滚；
- 方向由 from/to 决定，金额永远为正；0、负数、NaN、Infinity 一律拒绝。
- 币种不同的账户之间禁止转账。

## 追溯与审计

- 分录存前后余额与账户版本，可回放、可校验；
- 视图（`*_view`）对外提供友好查询，底表只追加。

## 可借鉴

- [PG1] 账户级 `allow_negative_balance` / `allow_positive_balance` 双向约束（如资产类不得为负，费用类不得为正冲）。
- [PG2] 分录存 previous/current balance + version，审计友好。
- [PG3] `event_at`（业务时间）与 `created_at`（写入时间）分离。
- [PG4] 带类型前缀的 ULID 主键（`acc_`、`txn_`、`ent_`）—— 日志与排错一眼可辨。
- [PG5] 数据库层 CHECK 约束兜底（金额有限、正数、两端不同）；按 ID 顺序加锁防死锁。
- [PG6] 账本写入与业务写入同库同事务。

## 不采用 / 风险

- `NUMERIC` 不限精度，但没有资产精度约束（需在币种表定义 scale 并校验）。
- 只有转账原语，没有多腿凭证、科目性质、期间、报表。

## 对新系统的启示

- 采用前缀 ULID；分录写 `balance_after` 与账户版本；账户级正负余额约束；数据库 CHECK 约束兜底金额合法性；加锁按账户 ID 排序。
