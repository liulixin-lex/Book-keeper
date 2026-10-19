# flash-oss/medici

- 分类：02 账本引擎（Node.js + MongoDB 库）
- 语言 / 许可证 / 最近提交：TypeScript / MIT / 2026-07-29
- 审查范围：`README.md`、`src/{Book,Entry}.ts`、`src/models/{journal,transaction,balance,lock}.ts`

## 定位

嵌入应用的复式记账库：Book（账簿）→ Journal（凭证）→ Transaction（分录，每条对应一个账户的借或贷）。

## 数据模型

- **账户名是冒号分层路径**（`Assets:Cash`、`Liabilities:Client:123`），查询 `Assets` 会包含所有子账户；
- Journal：memo、datetime、`void` / `void_reason`、`voided_journal`（被冲的原凭证）；
- Transaction：account、credit/debit、datetime、meta（任意业务字段，可在查询中直接按 meta 过滤，如 `client: "Joe"`）；
- 金额为 JS Number，可配精度（默认 8 位小数）——有浮点风险。

## 记账逻辑与算法

- 链式 API：`book.entry("memo").debit(acct, amt, meta).credit(acct, amt).commit()`，提交时校验借贷相等，不等抛错。
- **Void**：生成一张金额相反的新凭证，原凭证标记 void 并记原因；可选 `use_original_date` 用原日期冲回。
- **余额快照缓存**：对“账簿+账户+meta 过滤条件”生成 key（SHA-1），首次查询聚合后存快照，之后的查询 = 最近快照 + 快照之后的增量；快照过期自动重建（TTL 索引）。也支持按交易 ID 区间求余额（`start_tx_id`/`end_tx_id`）。
- **写锁**：`writelockAccounts` 只锁需要防透支的账户（如钱包），配合 MongoDB 事务防止并发超支。

## 追溯与审计

- void 链（原凭证 ↔ 冲销凭证）；meta 存业务引用。
- 已知问题：用原日期冲回时余额快照会暂时不一致（最长 48 小时后重算）——说明“回溯修改历史日期”与“余额缓存”的冲突需要专门处理。

## 可借鉴

- [MD1] 层级账户路径 + 前缀聚合查询（汇总到父科目）。
- [MD2] 分录 meta 可直接作为查询维度。
- [MD3] 余额快照 = 最近快照 + 增量；快照按“账户+过滤条件”分别缓存。
- [MD4] 只锁需要防透支的账户，降低锁竞争。
- [MD5] void 凭证可选原日期冲回 + 原因必填。

## 不采用 / 风险

- 浮点金额；MongoDB 读一致性坑（README 专门警告 `readConcern: majority` 导致负余额）。
- 回填日期会让快照失效——新系统的余额快照必须在有过去日期的写入时按日期失效重算。

## 对新系统的启示

- 账户树（父子）+ 汇总查询；分录维度标签可查询；
- 余额快照按（账户, 币种, 日期）落盘，任何生效日期 ≤ 快照日期的写入都要使对应快照失效（或增量修正）；
- 冲正支持“按原日期”与“按冲正日”两种口径，原因必填。
