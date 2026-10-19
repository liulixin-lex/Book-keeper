# moneymanagerex/moneymanagerex（MMEX）

- 分类：06 个人财务（桌面，单式账户流水）
- 语言 / 许可证 / 最近提交：C++ (wxWidgets) + SQLite / GPL-2.0 / 2026-10-17
- 审查范围：`src/table/tables_en.sql`（数据库结构）、`src/import_export/{univcsvdialog,ofx_import_gui,qif_import,payeematchandmerge,webapp}`

## 定位

简单易用的跨平台个人理财：银行/信用卡/储蓄/投资/资产账户、多级分类、拆分交易、预算、计划交易、报表。

## 数据模型

- `CHECKINGACCOUNT_V1`（交易）：账户、`TOACCOUNTID` 与 `TOTRANSAMOUNT`（转账目标账户与目标金额——**跨币种转账两端金额分别记录**）、收付款方、类型（取出/存入/转账）、金额、**状态（无 / 已对账 / 作废 / 待跟进 / 疑似重复）**、交易号、备注、分类、日期、最后更新时间、**删除时间（软删除）**、颜色标记；
- `SPLITTRANSACTIONS_V1`（拆分）、`TAG_V1` + `TAGLINK_V1`（多标签）、`TRANSLINK_V1`（交易关联资产/股票）、`ATTACHMENT_V1`（附件，按引用类型挂载）；
- **`CUSTOMFIELD_V1` / `CUSTOMFIELDDATA_V1`**：自定义字段，可作用于交易/股票/资产/账户/计划交易/收付款方，类型含 字符串/整数/小数/布尔/日期/时间/单选/多选（带属性 JSON）；
- `CURRENCYHISTORY_V1`（币种汇率历史）、`CURRENCYFORMATS_V1`（显示格式）。

## 导入

- 通用 CSV 导入（列映射可保存为预设）、OFX、QIF；**收付款方匹配与合并**（payeematchandmerge：按正则/通配符把导入名映射为标准收付款方）；Web App 同步（手机录入后导入桌面）。

## 可借鉴

- [MX1] 交易状态含“待跟进”“疑似重复”——人工复核队列的标记方式。
- [MX2] 自定义字段（作用对象 + 类型 + 属性），通用且可查询。
- [MX3] 跨币种转账两端金额分别记录。
- [MX4] 收付款方别名/正则映射与合并。
- [MX5] 软删除时间戳 + 最后更新时间。

## 不采用 / 风险

- 单式模型；GPL。

## 对新系统的启示

- 交易 `review_flags`（follow_up、suspected_duplicate）；
- 自定义字段机制（类型化，可过滤）；
- 交易对手别名表（正则/关键字 → 标准对手）。
