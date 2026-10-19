# crater-invoice-inc/crater

- 分类：04 开票与支出管理（非复式）
- 语言 / 许可证 / 最近提交：PHP (Laravel) + Vue / AGPL-3.0 / 2024-08（基本停更）
- 审查范围：`app/Models/*`、`database/migrations/*`（多币种 base 列）、`ExchangeRateProvider`、`CustomField`

## 定位

面向自由职业者和小企业的开票、报价、收款、费用记录工具。

## 数据模型

- Invoice / Estimate / Payment / Expense / RecurringInvoice，金额以整数分存储（unsigned big integer）；
- **多币种：每张单据与明细行都存 `exchange_rate DECIMAL(19,6)` 与 `base_*`（本位币金额），录入当时折算并冻结**；
- **ExchangeRateProvider**（汇率来源配置：驱动、支持币种、启用状态、API 配置）+ **ExchangeRateLog**（每次获取的汇率记录）；
- CustomField（自定义字段：按模型类型定义，值存 custom_field_values）；ExpenseCategory；PaymentMethod。

## 可借鉴

- [CR1] 原币金额 + 当时汇率 + 本位币金额三者同存并冻结（报表不随汇率变化）。
- [CR2] 汇率提供方可配置 + 汇率获取日志（可追溯每个汇率从哪来）。
- [CR3] 自定义字段机制（按实体类型定义字段与类型）。

## 不采用 / 风险

- 非复式；功能停更；AGPL。

## 对新系统的启示

- 汇率表记录 provider、获取时间、原始响应摘要；交易上冻结所用汇率 ID；
- 允许为交易/供应商定义自定义字段（如“站点余额截图编号”“兑换码”），并可被查询过滤。
