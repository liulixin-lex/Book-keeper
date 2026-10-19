# kedder/ofxstatement

- 分类：07 导入（专有对账单 → OFX 的插件框架）
- 语言 / 许可证 / 最近提交：Python / GPL-3.0 / 2026-08
- 审查范围：`src/ofxstatement/{statement,parser,plugin,ofx,tool}.py`、插件生态说明

## 定位

把各银行专有格式（CSV/PDF/XLS）的对账单统一转换为 OFX，供 GnuCash/HomeBank 等导入；银行格式由社区插件实现。

## 设计要点

- **统一对账单模型**：Statement（账户 ID、币种、**期初余额、期末余额、起止日期**、银行 ID）+ StatementLine（**唯一 ID（FITID）**、日期、金额、**收付款方**、备注、交易类型、支票号、参考号、用户/冲正标记）；
- 插件接口：`get_parser(filename) → parser.parse() → Statement`；
- **校验**：`assert_valid()` 检查必需字段、ID 唯一、**期初余额 + 明细合计 = 期末余额**（若提供）；
- 缺少唯一 ID 时提供生成稳定 ID 的工具：`generate_transaction_id`（日期、备注、金额的 SHA-1）与 `generate_unique_transaction_id`（冲突时追加序号）——ID 必须“同一笔每次生成都相同”，否则重叠期间的对账单会被重复导入。

## 可借鉴

- [OS-1] 标准化对账单模型：账户、币种、期间、期初/期末余额 + 带唯一 ID 的明细行。
- [OS-2] 期初 + 明细 = 期末 的硬校验。
- [OS-3] 无源 ID 时的稳定 ID 生成规则（内容哈希 + 同日序号）。

## 对新系统的启示

- `Statement`（导入批次）实体保存来源声明的期初/期末余额与期间；`StatementLine` 必有稳定 `external_id`（源 ID 或确定性哈希）。
