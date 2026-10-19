# envato/double_entry

- 分类：03 复式记账库（Ruby on Rails）
- 语言 / 许可证 / 最近提交：Ruby / MIT / 2026-01
- 审查范围：`README.md`、`lib/double_entry/{account,transfer,line,locking,validation}`

## 定位

Envato（大型数字商品市场）生产使用的“资金流转”库：每次转账写两条 line，余额存于 line 上，并通过配置白名单约束允许的转账。

## 数据模型

- **账户在配置中定义**：标识（如 `:savings`）+ 作用域（scope，如按用户拆分为每人一个子账户）+ 币种 + `positive_only`（不得为负）；
- **转账白名单**：配置中定义 `from → to` 允许的组合与业务代码 `code`（如 `:deposit`、`:withdraw`），未定义的转账一律拒绝；
- `double_entry_lines`：每笔转账两行（源/目标），每行存 **running balance**（该账户过账后余额）、code、partner 账户、metadata（JSONB）；
- `account_balances`：每账户当前余额缓存，同时作为行锁对象。

## 记账逻辑与算法

- 当前余额 = 该账户最新一条 line 的 balance；
- **显式锁**：`lock_accounts(a, b) { ... }` 在最外层事务中按确定顺序锁定账户余额行，内部可做多笔转账与其他业务写入，原子提交；
- 不同币种账户之间禁止转账。

## 追溯与审计

- **LineCheck**：定时任务校验每行的 running balance 是否等于重新累加的结果、account_balances 是否等于最新行，结果写入 `double_entry_line_checks` 表；可选 **AccountFixer** 自动修复——“相信但要核验”。

## 可借鉴

- [DE1] 转账类型白名单（from 科目、to 科目、业务代码）—— 杜绝不合规的科目组合（对应“交易类型模板只允许特定借贷科目”）。
- [DE2] 账户作用域（同一科目按用户/供应商/渠道拆分子账户）。
- [DE3] 每行存过账后余额 + 当前余额缓存表作为锁对象。
- [DE4] 定期核验任务（重算余额对比缓存）+ 检查结果入库。

## 不采用 / 风险

- 只有两腿转账，不支持多借多贷凭证；不区分科目性质；配置写在代码里，运行期不可改。

## 对新系统的启示

- 交易类型模板 = 允许的借贷科目组合（白名单），API 写入时强校验；
- 子账户/维度机制（供应商、渠道）；
- 余额核验后台任务 + 核验记录表 + 告警。
