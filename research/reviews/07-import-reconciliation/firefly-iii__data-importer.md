# firefly-iii/data-importer

- 分类：07 导入器（独立服务，通过 API 写入 Firefly III）
- 语言 / 许可证 / 最近提交：PHP (Laravel) / AGPL-3.0 / 2026-10-18
- 审查范围：`app/Services/{CSV/{Converter,Mapper,Roles,Conversion},Shared/{Configuration,Conversion,Import},Camt,Nordigen,SimpleFIN,EnableBanking,...}`、`config/csv.php`

## 定位

Firefly III 的官方导入器：CSV、CAMT.053 以及多家银行聚合 API（GoCardless/Nordigen、SimpleFIN、Enable Banking、Akahu…），把外部流水转换为 Firefly 交易，通过 REST API 写入。**与主系统解耦**——导入器只是一个 API 客户端。

## 设计要点

- **导入配置（Configuration）可保存为 JSON 并复用**：分隔符、日期格式、默认账户、列角色、映射、去重方式、是否自动套用规则、是否保留为待定等；
- **列角色（roles）**：每列指定语义（日期类：交易/利息/记账/处理/到期/付款/发票日；金额类：金额、借方金额、贷方金额、取反金额、外币金额；账户类：账户名/IBAN/号码、对方名/IBAN/号码；描述、备注、分类、预算、标签（逗号/空格分隔）、外部 ID、外部 URL、内部参考号、币种代码；各银行特有的借贷标志列；SEPA 字段；忽略）；
- **值映射（mapper）**：把某列出现的值映射到系统中已有实体（如“Taobao” → 收款方账户 #12）；
- **转换器（converter）**：金额（各种格式与正负约定）、日期、IBAN、清洗字符串等，各自独立、可测试；
- **去重方式**：`classic`（按交易内容哈希，Firefly 端判重）或 `cell`（指定一列或多列组合成“伪标识符”，作为外部 ID 判重）；
- 导入任务有状态与进度、错误/警告逐行报告；可选导入后自动执行 Firefly 规则。

## 可借鉴

- [DI-1] 导入器作为独立的 API 客户端（解耦），主系统只暴露稳定的写 API（含幂等/去重）。
- [DI-2] 列角色体系 + 值映射 + 可保存的导入配置 JSON。
- [DI-3] 去重两模式：内容哈希 / 指定列组合的伪外部 ID。
- [DI-4] 逐行错误与警告报告。

## 不采用 / 风险

- AGPL；银行聚合 API 对国内场景不适用。

## 对新系统的启示

- 导入配置（ImportProfile）：来源类型、列角色、值映射、默认值、去重键定义（列组合）、导入后规则集；可保存、复用、导出；
- 内部导入器与外部 AI 走同一套 API（MCP 只是另一种客户端）。
