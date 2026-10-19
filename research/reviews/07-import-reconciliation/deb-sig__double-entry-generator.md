# deb-sig/double-entry-generator

- 分类：07 导入 / 分类（中国账单 → 复式记账）
- 语言 / 许可证 / 最近提交：Go / Apache-2.0 / 2026-10-04（730 星，国内纯文本记账圈最常用的导入器）
- 审查范围：`pkg/{ir,provider/{alipay,wechat,jd,mt,ccb,icbc,cmb,huobi,...},compiler/{beancount,ledger},config,analyser}`、`example/*/config.yaml`

## 定位

规则驱动的账单导入器：解析支付宝、微信、京东、美团、各大银行、券商、火币等账单，生成 Beancount / Ledger 分录。

## 数据模型（中间表示 IR）

- `Order`：订单类型、**交易对方（Peer）**、**商品（Item）**、分类（Category）、**商户订单号 + 平台订单号**、金额、备注、**支付时间**、收/支方向（含原始字段 TypeOriginal、交易类型 TxTypeOriginal）、**支付方式（Method）**、数量/价格/币种、**手续费（Commission）**、单位（基础/目标/手续费币种）、**扩展账户（现金、持仓、手续费、损益、第三方存管）**、正/负账户（MinusAccount/PlusAccount）、元数据、标签；
- 解析层（provider）→ IR → 编译层（compiler）三段式，新增账单源只需写 provider。

## 规则（核心）

- 规则按顺序匹配，**后匹配的覆盖先匹配的**（因此“泛化规则放前面，具体规则放后面”）；
- 匹配字段：`type`（收/支/其他）、`item`、`category`、`peer`、`method`、`txType`、**`time`（时段，如 11:00-14:00 午餐）**、**`minPrice/maxPrice`（金额区间）**、`fullMatch`（精确/包含）、`sep`（多关键字）、`ignore`（忽略该条）；
- 动作：`targetAccount`（对方科目）、`methodAccount`（资金账户）、`commissionAccount`、`pnlAccount`、`tags`；
- 未命中规则时落入 `defaultMinusAccount/defaultPlusAccount`（如 `Assets:FIXME` / `Expenses:FIXME`）待人工处理。

## 业务后处理

- **退款配对**：状态“退款成功”且分类为“退款”的记录，按“订单号前缀匹配 + 金额相等”找到原交易，两者一并标记为无效（可配置保留以便对账）；
- “交易关闭”且“不计收支”的记录剔除；未能配对的退款保留并告警。

## 可借鉴

- [DEG1] **解析器 → 中间表示 → 生成器** 三段式，账单源插件化。
- [DEG2] 支付宝/微信字段语义：交易对方、商品、平台订单号/商户订单号、收/支/不计收支、交易状态（成功/退款成功/关闭）、支付方式。
- [DEG3] 规则：时段、金额区间、多关键字、精确/包含、忽略；后者覆盖前者。
- [DEG4] 未匹配 → FIXME 科目（待处理）。
- [DEG5] 退款与原交易配对（订单号前缀 + 金额）。

## 不采用 / 风险

- 金额 float64；规则无优先级字段、只靠顺序，规则多了难维护（新系统需显式优先级 + 特异性排序 + 命中解释）。

## 对新系统的启示

1. 导入层采用“解析器（source adapter）→ 标准化流水（StatementLine）→ 规则/匹配 → 交易草稿”；
2. 标准化流水字段对齐 DEG 的 IR（对方、商品、平台单号、商户单号、方向、状态、支付方式、手续费）；
3. 微信/支付宝退款、关闭单的规则内置为“预处理规则”；
4. 未匹配统一进入待处理科目/队列。
