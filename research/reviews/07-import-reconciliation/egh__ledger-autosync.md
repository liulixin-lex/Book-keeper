# egh/ledger-autosync

- 分类：07 银行同步与去重（OFX → ledger/hledger）
- 语言 / 许可证 / 最近提交：Python / GPL-3.0 / 2026-04
- 审查范围：`ledgerautosync/{sync,converter,cli,ledgerwrapper}.py`、README

## 定位

从银行（OFX Direct Connect 或 OFX 文件）拉取交易，只生成账本中尚不存在的交易，从不直接修改账本文件。

## 设计要点

- **稳定外部 ID**：`ofxid = 账户ID.交易FITID`，写入 posting 元数据；同步前查询账本中是否已存在该 ID——幂等的增量同步；账户号可截短或硬编码以适配账户变更；
- **首次同步标记**：第一次同步写入 `autosync_initial` 期初交易（带余额断言），之后增量；
- **余额断言**：每次同步可附带银行报告的余额断言，立即发现漏记；
- 过滤“注释交易”（金额 0、同时间戳）；投资账户支持证券 CUSIP/ticker 映射；
- 输出为文本追加，不就地修改（安全）。

## 可借鉴

- [LA-1] 外部 ID = 来源账户 + 来源交易号，存于交易元数据作为幂等键。
- [LA-2] 同步时附带外部余额断言。
- [LA-3] 只追加、不修改既有数据。

## 不采用 / 风险

- GPL；OFX 对国内渠道不适用。

## 对新系统的启示

- 外部流水唯一键：`(source_type, source_account, external_id)` 唯一约束；
- 每次导入可同时导入“来源报告的余额”（如上游站当前余额、Stripe 余额），生成余额断言记录。
