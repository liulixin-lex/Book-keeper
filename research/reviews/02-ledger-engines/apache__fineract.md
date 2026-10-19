# apache/fineract

- 分类：02 账本引擎（核心银行系统中的总账模块）
- 语言 / 许可证 / 最近提交：Java (Spring) / Apache-2.0 / 2026-10-17
- 审查范围：`fineract-accounting/.../accounting/{glaccount,journalentry,closure,rule,producttoaccountmapping,financialactivityaccount,trialbalance,accrual}`、`JournalEntryRunningBalanceUpdateServiceImpl`

## 定位

面向小额信贷/储蓄机构的核心银行系统；会计模块把业务事件（放款、还款、计息、手续费）自动过账到总账（GL）。

## 数据模型

- **GLAccount**：`gl_code`、名称、父科目 + `hierarchy`（物化路径）、`classification`（资产/负债/权益/收入/费用）、`usage`（**明细科目 vs 汇总/标题科目**，只有明细科目可记账）、`manual_journal_entries_allowed`（是否允许手工凭证）、`disabled`、标签（CodeValue）。
- **JournalEntry**：一行一个科目借或贷，`transaction_id` 把同一笔业务的多行归组；`entry_date`、`currency_code`、`amount DECIMAL(19,6)`、`reversed` + `reversal_journal_entry`（指向冲销分录）、`manual_entry`、来源业务 ID（贷款/储蓄/客户交易）、机构（office）、支付明细、`running_balance`（由后台任务按科目递推计算）。
- **GLClosure**：按机构的**结账日期**；结账日及之前不能再记账，不能设未来日期，后一次结账日必须晚于前一次。
- **AccountingRule（记账规则）**：预定义的借方科目、贷方科目（或按标签选一组科目）、是否允许多借/多贷——手工凭证的“快捷模板”。
- **Product-to-Account Mapping**：每个金融产品把“业务事件类型 → GL 科目”配置好，系统过账时查表；**Financial Activity Account**：把“资金划转”等财务活动类型映射到具体科目。

## 记账逻辑与算法

- 业务事件触发自动过账：根据产品映射生成多行分录，借贷平衡校验后写入；
- 冲销：生成反向分录，原分录 `reversed=true` 并相互指向；
- 运行余额：异步任务按科目、按日期顺序递推 `running_balance`，回溯录入会触发重算；
- 试算平衡表、计提（accrual）任务、拨备、留存收益结转。

## 追溯与审计

- 所有写操作走命令（Command）模式并记录在审计表（maker-checker 可选）；分录带创建人/时间（审计基类）。

## 导入、分类与对账

- 有批量导入（Excel 模板）；无银行对账。

## 可借鉴

- [FN1] 科目区分“汇总科目/明细科目”，只有明细科目可记账；科目可设置“禁止手工凭证”（只允许系统自动过账）。
- [FN2] 业务事件 → 科目映射表（按产品/业务类型配置），而不是在代码里硬编码科目。
- [FN3] 结账日期（closure）：结账日之前禁止新增/修改，结账只能向前推进。
- [FN4] 记账规则模板（预设借贷科目，支持按标签选择）。
- [FN5] 分录归组号（transaction_id）+ 冲销分录互指。
- [FN6] 运行余额后台递推 + 回溯写入触发重算。

## 不采用 / 风险

- 过于庞大（8000+ 文件），信贷产品逻辑与我们无关；
- 金额 DECIMAL(19,6) 统一精度，不区分币种精度；
- maker-checker（制单-审核）属于审批流程，按用户要求不采用。

## 对新系统的启示

- 科目表：层级 + 性质 + 汇总/明细 + 是否允许手工记账 + 启停；
- 交易模板/业务类型到科目的映射是配置数据，可版本化；
- 期间锁定（结账日）作为硬约束；
- 余额递推/快照在回溯写入时失效重算。
