# tryton/tryton（modules/account、account_statement、account_statement_rule、currency）

- 分类：05 ERP 会计模块
- 语言 / 许可证 / 最近提交：Python / GPL-3.0 / 2026-10-15
- 审查范围（稀疏检出）：`modules/account/{move,move_template,period,fiscalyear,journal,account}.py`、`modules/account_statement_rule/account.py`、`modules/account_statement`、`modules/currency`

## 定位

模块化、严谨的 ERP 框架；会计模块以“凭证 + 期间工作流 + 模板 + 流水规则”为核心，代码风格克制。

## 数据模型

- **Fiscal Year / Period**：状态工作流 **open → closed → locked**（关闭可重新打开；**锁定不可逆**）；关闭期间禁止过账；
- **Move**：期间、日记账、日期、`post_date`、编号（过账时分配）、`origin`（**Reference 字段，可指向任意业务单据**）、状态 draft/posted、描述；
- **Move Template（凭证模板）**：关键字（keywords：名称、标签、类型 char/numeric/date/party）+ 行模板（借/贷、**金额为表达式（用关键字计算）**、科目、往来方关键字、描述含关键字替换）+ 税行模板——用户填写几个关键字即生成完整凭证；
- **Statement Rule（流水规则，按顺序匹配）**：日记账、**金额区间（low/high）**、**描述正则（可定义命名分组：party、bank_account、invoice、payment_reference）**、信息规则（按流水结构化信息键值匹配）、规则行（**金额表达式，可用 amount 与 pending（剩余未分配）变量**、往来方（缺省取正则分组提取的 party）、科目（缺省取往来方的应收/应付））。

## 记账逻辑与算法

- 流水规则：按顺序尝试每条规则，命中后按规则行逐条生成流水明细行；`pending` 让多行规则可以“先分 3% 手续费，剩余全部给某科目”；
- 表达式用安全求值（simple_eval + 十进制化），结果按币种精度舍入；
- 期间关闭前检查未过账凭证。

## 可借鉴

- [TR1] 期间三态 open/closed/locked，锁定不可逆。
- [TR2] **凭证模板 = 关键字 + 表达式行**（金额、描述可引用关键字）—— 业务模板的成熟范式。
- [TR3] **流水规则：描述正则命名分组提取往来方/单据号/付款参考**，金额表达式可用剩余金额 `pending`。
- [TR4] 安全表达式求值 + Decimal 化 + 按币种舍入。
- [TR5] origin 引用任意来源单据。

## 不采用 / 风险

- GPL；框架耦合。

## 对新系统的启示

1. 交易模板定义：参数（名称、类型、校验）+ 行（借/贷、科目或科目选择规则、金额表达式、维度）；表达式用安全求值器（白名单函数、Decimal）；
2. 导入规则支持正则命名分组提取字段（如从“云猫订单 1029384 100R兑换码”提取订单号、面值）；
3. 规则行支持 `remaining` 变量，实现“先扣手续费、剩余入成本”。
