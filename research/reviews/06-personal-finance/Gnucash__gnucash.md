# Gnucash/gnucash（libgnucash/engine）

- 分类：06 个人/小企业复式记账（桌面经典）
- 语言 / 许可证 / 最近提交：C / C++ / GPL-2.0+ / 2026-10-18
- 审查范围（稀疏检出）：`libgnucash/engine/{Transaction,Split,Account,gnc-lot,cap-gains,policy,gnc-pricedb,SchedXaction,Recurrence,Scrub,Scrub2,Scrub3}.{h,cpp}`、`libgnucash/backend/sql`

## 定位

25 年历史的复式记账软件，引擎层的多币种与批次模型是很多后来者的参照。

## 数据模型

- **Transaction**：交易币种（currency）、过账日期 + 录入日期、编号、描述、备注、KVP 槽（任意元数据）、作废信息；
- **Split（分录）**：账户、备注、动作（action）、**value（以交易币种计）与 amount（以账户商品/币种计）**——两者之比即成交价/汇率；对账状态 **n（未清）/ c（已清）/ y（已对账）/ f（冻结于已结账期间）/ v（作废）** + 对账日期；所属 lot；
- **Account**：商品（currency 或证券）、类型（银行、现金、资产、信用卡、负债、股票、基金、收入、费用、权益、应收、应付、**交易 Trading**）、父子层级、占位（placeholder，不可记账）、隐藏、编码；
- **GNCLot**：批次（同一账户内一组相关分录，用于资本利得、发票-付款配对），关闭条件为余额为零；**Policy**：FIFO/LIFO 批次分配策略；
- **Price DB**：商品价格（日期、来源：用户/交易推算/在线报价、类型）；
- **SchedXaction**：计划交易模板 + Recurrence 周期，“自上次运行以来”批量生成；
- 金额用 **gnc_numeric（有理数：分子/分母）** 精确运算，按商品最小单位舍入。

## 记账逻辑与算法

- 平衡规则：同一交易所有 split 的 **value 之和为 0**（交易币种下平衡），各账户以自己的 amount 记账——一笔交易可同时涉及多种币种；
- **Scrub（清洗/修复）**：发现不平衡交易时自动生成 `Imbalance-<币种>` 账户分录补平、无账户分录归入 `Orphan-<币种>`，提示用户修正而不是丢数据；Scrub2/3 修复批次与资本利得；
- 可选**交易账户（Trading Accounts）**：跨币种交易自动通过交易账户平衡每种商品，便于计算未实现汇兑损益；
- 作废（void）：保留交易，金额清零，原值存入 KVP 并记原因；
- 结账（book closing）：生成结转分录，已结账分录状态为 frozen。

## 可借鉴

- [GC1] **value（交易币种）+ amount（账户币种）双金额**，交易按 value 平衡。
- [GC2] 分录级对账状态（未清/已清/已对账/冻结/作废）。
- [GC3] 批次（lot）+ 分配策略（FIFO/LIFO）——用于外币/额度成本与配对。
- [GC4] 不平衡自动落入 `Imbalance-币种` 科目并提示，绝不静默丢弃。
- [GC5] 占位（汇总）账户不可记账。
- [GC6] 价格库带来源与类型；有理数精确运算。
- [GC7] 作废保留痕迹（原值 + 原因）。

## 不采用 / 风险

- 桌面单用户；GPL；有理数存储方式不利于 SQL 汇总（新系统用定点整数）。

## 对新系统的启示

- 分录行的“原币金额 + 本位币金额”对应 amount/value 概念；
- 导入异常不阻断：无法确定科目的金额进入“待处理（Imbalance/Suspense）”科目，形成待办；
- 分录对账状态五态；作废 = 冲正（我们统一用冲正交易），原因必填。
