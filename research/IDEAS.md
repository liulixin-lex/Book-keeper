# 可借鉴要点总表

从 81 份审查的“可借鉴”一节自动汇总。重构方案文档中的 `[ID]` 引用均指向此表。

| ID | 项目 | 要点 |
|---|---|---|
| PS1 | [ananthakumaran/paisa](reviews/01-plaintext-accounting/ananthakumaran__paisa.md) | 规则化“账务体检”：科目方向异常（收入出现借方、费用出现贷方）、资产为负、缺汇率、价格不一致 —— 可直接作为新系统的健康检查项。 |
| PS2 | [ananthakumaran/paisa](reviews/01-plaintext-accounting/ananthakumaran__paisa.md) | TF-IDF 相似度推荐科目/交易类型。 |
| PS3 | [ananthakumaran/paisa](reviews/01-plaintext-accounting/ananthakumaran__paisa.md) | 文本/源数据为真、数据库为可重建缓存的思路（新系统中对应：事件为真、投影可重建）。 |
| PS4 | [ananthakumaran/paisa](reviews/01-plaintext-accounting/ananthakumaran__paisa.md) | 可保存的导入模板。 |
| BC1 | [beancount/beancount](reviews/01-plaintext-accounting/beancount__beancount.md) | 余额断言（某日某账户余额应为 X）+ 容差 —— 对账与防漏账核心机制（对应上游站余额、渠道余额、钱包余额核对）。 |
| BC2 | [beancount/beancount](reviews/01-plaintext-accounting/beancount__beancount.md) | 账户声明允许的币种、开户/销户日期，越界报错。 |
| BC3 | [beancount/beancount](reviews/01-plaintext-accounting/beancount__beancount.md) | tags + links：标签分类 + 关联号串联多笔相关交易（订单号、兑换批次、导入批次）。 |
| BC4 | [beancount/beancount](reviews/01-plaintext-accounting/beancount__beancount.md) | 每条数据的来源定位（文件、行号）——新系统对应“来源凭证 + 行号/字段路径”。 |
| BC5 | [beancount/beancount](reviews/01-plaintext-accounting/beancount__beancount.md) | 自动补全 + 按币种容差推断 —— 舍入有据可依。 |
| BC6 | [beancount/beancount](reviews/01-plaintext-accounting/beancount__beancount.md) | 批次成本与 booking 方法（FIFO/AVERAGE…）—— 外币/上游额度成本核算。 |
| BC7 | [beancount/beancount](reviews/01-plaintext-accounting/beancount__beancount.md) | 价格库 + 按成本/按市值/按日期换算的报表口径；`Equity:Conversions` 处理多币种换算差。 |
| BC8 | [beancount/beancount](reviews/01-plaintext-accounting/beancount__beancount.md) | 插件式校验规则（可组合的不变量检查）。 |
| BC9 | [beancount/beancount](reviews/01-plaintext-accounting/beancount__beancount.md) | flag（`*` / `!`）区分已确认与待核实。 |
| BC10 | [beancount/beancount](reviews/01-plaintext-accounting/beancount__beancount.md) | 期间汇总/结转为期初分录。 |
| FV1 | [beancount/fava](reviews/01-plaintext-accounting/beancount__fava.md) | 收付款方 → 科目推荐（指数衰减加权历史频次）+ 最近交易作为模板 —— 录入提效。 |
| FV2 | [beancount/fava](reviews/01-plaintext-accounting/beancount__fava.md) | 修改操作携带“读取时的版本/哈希”做乐观并发控制。 |
| FV3 | [beancount/fava](reviews/01-plaintext-accounting/beancount__fava.md) | 从任一条目跳转到来源原文（source slice）与上下文（前后余额）。 |
| FV4 | [beancount/fava](reviews/01-plaintext-accounting/beancount__fava.md) | 导入流程：上传 → 识别导入器 → 预览抽取结果 → 逐条确认 → 写入 + 文档归档挂接。 |
| FV5 | [beancount/fava](reviews/01-plaintext-accounting/beancount__fava.md) | 报表统一的换算参数（成本/市值/单位/目标币种）与时间过滤器。 |
| HL1 | [hledgerorg/hledger](reviews/01-plaintext-accounting/hledgerorg__hledger.md) | 分级校验（默认/严格/可选）且可单独运行 —— 对应新系统的“校验规则集”与 `/checks` API。 |
| HL2 | [hledgerorg/hledger](reviews/01-plaintext-accounting/hledgerorg__hledger.md) | 跨币种必须显式写换算（成本或权益换算分录），禁止隐式换算。 |
| HL3 | [hledgerorg/hledger](reviews/01-plaintext-accounting/hledgerorg__hledger.md) | 多种估值口径（成本、当时、期末、现在、指定日）× 目标币种。 |
| HL4 | [hledgerorg/hledger](reviews/01-plaintext-accounting/hledgerorg__hledger.md) | CSV 导入规则 DSL：字段映射 + 条件规则（正则、多匹配器、捕获组）+ 合并多行 + 跳过 + 从对账单生成余额断言 + 原始文件归档 —— 导入模块的核心参考。 |
| HL5 | [hledgerorg/hledger](reviews/01-plaintext-accounting/hledgerorg__hledger.md) | 增量导入：记录每个来源的导入水位线（最后日期+当日条数），只追加新记录；dry-run 预览。 |
| HL6 | [hledgerorg/hledger](reviews/01-plaintext-accounting/hledgerorg__hledger.md) | 自动过账规则（按查询匹配交易追加分录，如按比例计手续费）。 |
| HL7 | [hledgerorg/hledger](reviews/01-plaintext-accounting/hledgerorg__hledger.md) | 结账命令同时生成断言；“近期必须有断言”的督促式检查。 |
| HL8 | [hledgerorg/hledger](reviews/01-plaintext-accounting/hledgerorg__hledger.md) | 账户类型声明驱动报表分类；交易状态（未确认/待定/已确认）。 |
| HL9 | [hledgerorg/hledger](reviews/01-plaintext-accounting/hledgerorg__hledger.md) | 交易与 posting 都可带独立日期（如付款日 vs 到账日）。 |
| HL10 | [hledgerorg/hledger](reviews/01-plaintext-accounting/hledgerorg__hledger.md) | 错误信息带精确位置与上下文。 |
| LD1 | [ledger/ledger](reviews/01-plaintext-accounting/ledger__ledger.md) | 自动交易：谓词匹配 + 金额乘数（按比例生成手续费/税分录）。 |
| LD2 | [ledger/ledger](reviews/01-plaintext-accounting/ledger__ledger.md) | 交易级/分录级生效日（记账日 vs 实际收付日）。 |
| LD3 | [ledger/ledger](reviews/01-plaintext-accounting/ledger__ledger.md) | 商品等价关系（内部换算约定，如“上游额度 $1 = ¥1”作为显式规则而非硬编码）。 |
| LD4 | [ledger/ledger](reviews/01-plaintext-accounting/ledger__ledger.md) | 虚拟 posting 用于预算/备忘跟踪，不污染真实账。 |
| LD5 | [ledger/ledger](reviews/01-plaintext-accounting/ledger__ledger.md) | 类型化元数据（声明字段类型，查询时按类型比较）。 |
| LD6 | [ledger/ledger](reviews/01-plaintext-accounting/ledger__ledger.md) | 成本（批次固定）与价格（换算参考）严格区分。 |
| RL1 | [rustledger/rustledger](reviews/01-plaintext-accounting/rustledger__rustledger.md) | 导入结果附带分类方法、置信度、备选、指纹 —— 自动分类可解释、可复核。 |
| RL2 | [rustledger/rustledger](reviews/01-plaintext-accounting/rustledger__rustledger.md) | 结构指纹去重：顺序无关、排除元数据。 |
| RL3 | [rustledger/rustledger](reviews/01-plaintext-accounting/rustledger__rustledger.md) | Agent 接口统一响应信封（ok / code / result / warnings / next_action）。 |
| RL4 | [rustledger/rustledger](reviews/01-plaintext-accounting/rustledger__rustledger.md) | 严格拒绝未知参数；人类接口与 Agent 接口之间的漂移检测测试。 |
| RL5 | [rustledger/rustledger](reviews/01-plaintext-accounting/rustledger__rustledger.md) | 插件沙箱（WASI）运行用户规则代码。 |
| KN1 | [sboehler/knut](reviews/01-plaintext-accounting/sboehler__knut.md) | posting 同时保存原币数量与本位币估值；估值随日期变化由“重估分录”体现，而不是改写原分录。 |
| KN2 | [sboehler/knut](reviews/01-plaintext-accounting/sboehler__knut.md) | 按日重估外币资产/负债，差额进汇兑损益科目 —— 解决“外币余额折算本位币时怎么体现汇率变化”。 |
| KN3 | [sboehler/knut](reviews/01-plaintext-accounting/sboehler__knut.md) | 价格图归一化（间接汇率推导）。 |
| KN4 | [sboehler/knut](reviews/01-plaintext-accounting/sboehler__knut.md) | 按日处理器管道（日初/逐笔/日末钩子）作为报表计算框架。 |
| TK1 | [tackler-ng/tackler](reviews/01-plaintext-accounting/tackler-ng__tackler.md) | 报表附带“数据集指纹”（交易 ID 集合哈希 + 条数 + 数据版本 + 过滤条件）—— 报表可复算、可证明。 |
| TK2 | [tackler-ng/tackler](reviews/01-plaintext-accounting/tackler-ng__tackler.md) | 交易强制带全局唯一 ID（审计模式）。 |
| TK3 | [tackler-ng/tackler](reviews/01-plaintext-accounting/tackler-ng__tackler.md) | 交易过滤器是可序列化的表达式，随报表一起输出。 |
| TK4 | [tackler-ng/tackler](reviews/01-plaintext-accounting/tackler-ng__tackler.md) | 用大量固定测试向量做回归。 |
| EK1 | [Ekwo-ai/ekwo-os](reviews/02-ledger-engines/Ekwo-ai__ekwo-os.md) | 单据（业务）层与分录（会计）层分离，分录只能由过账函数生成。 |
| EK2 | [Ekwo-ai/ekwo-os](reviews/02-ledger-engines/Ekwo-ai__ekwo-os.md) | 数据库层强制：已过账必须平衡、借贷单侧非负、汇总字段由触发器维护、锁账日触发器拒绝写入。 |
| EK3 | [Ekwo-ai/ekwo-os](reviews/02-ledger-engines/Ekwo-ai__ekwo-os.md) | 草稿不占号，过账时按“日记账/年度”原子分配连续编号。 |
| EK4 | [Ekwo-ai/ekwo-os](reviews/02-ledger-engines/Ekwo-ai__ekwo-os.md) | 冲销翻转借贷方向而非写负数；会计锁账与税务锁账分开。 |
| EK5 | [Ekwo-ai/ekwo-os](reviews/02-ledger-engines/Ekwo-ai__ekwo-os.md) | 分录行级核销（matching_number + matched_amount，部分核销）与到期日（账龄）。 |
| EK6 | [Ekwo-ai/ekwo-os](reviews/02-ledger-engines/Ekwo-ai__ekwo-os.md) | 报表只有一个实现（数据库函数），API/MCP/前端都调用它。 |
| EK7 | [Ekwo-ai/ekwo-os](reviews/02-ledger-engines/Ekwo-ai__ekwo-os.md) | MCP：服务端 instructions 写清首次会话流程与更正规则；命名化错误 + 下一步提示；以用户身份执行、拒绝超级密钥；OAuth 远程接入；用户授权时选择只读/可写。 |
| EK8 | [Ekwo-ai/ekwo-os](reviews/02-ledger-engines/Ekwo-ai__ekwo-os.md) | 规则（税、科目表、申报格式）作为带版本的数据包，并附样例账验证。 |
| M1 | [LerianStudio/midaz](reviews/02-ledger-engines/LerianStudio__midaz.md) | 业务动作 → 会计科目映射路由（按动作类型给出借贷科目）—— 让“记账员录的是业务、系统产出标准分录”。 |
| M2 | [LerianStudio/midaz](reviews/02-ledger-engines/LerianStudio__midaz.md) | 手续费模型：固定/比例/取大者 + 计算基数 + 优先级 + 内扣/外加 + 入账科目 —— 正好覆盖链动 3%（内含）、云猫 1.8%、Stripe 手续费、卡网加价等全部场景。 |
| M3 | [LerianStudio/midaz](reviews/02-ledger-engines/LerianStudio__midaz.md) | 每条分录保存前后余额与版本（balance trail），`recorded_at` 不可回填。 |
| M4 | [LerianStudio/midaz](reviews/02-ledger-engines/LerianStudio__midaz.md) | 组合/分部作为分析维度（对应我们的渠道、站点、项目）。 |
| M5 | [LerianStudio/midaz](reviews/02-ledger-engines/LerianStudio__midaz.md) | 编号化错误码 + 面向 AI 的文档（llms.txt）。 |
| M6 | [LerianStudio/midaz](reviews/02-ledger-engines/LerianStudio__midaz.md) | 拆分守恒测试（property/fuzz）。 |
| FN1 | [apache/fineract](reviews/02-ledger-engines/apache__fineract.md) | 科目区分“汇总科目/明细科目”，只有明细科目可记账；科目可设置“禁止手工凭证”（只允许系统自动过账）。 |
| FN2 | [apache/fineract](reviews/02-ledger-engines/apache__fineract.md) | 业务事件 → 科目映射表（按产品/业务类型配置），而不是在代码里硬编码科目。 |
| FN3 | [apache/fineract](reviews/02-ledger-engines/apache__fineract.md) | 结账日期（closure）：结账日之前禁止新增/修改，结账只能向前推进。 |
| FN4 | [apache/fineract](reviews/02-ledger-engines/apache__fineract.md) | 记账规则模板（预设借贷科目，支持按标签选择）。 |
| FN5 | [apache/fineract](reviews/02-ledger-engines/apache__fineract.md) | 分录归组号（transaction_id）+ 冲销分录互指。 |
| FN6 | [apache/fineract](reviews/02-ledger-engines/apache__fineract.md) | 运行余额后台递推 + 回溯写入触发重算。 |
| B1 | [blnkfinance/blnk](reviews/02-ledger-engines/blnkfinance__blnk.md) | 百分比/固定/剩余三种拆分 + 尾差处理 —— 手续费、分账规则的通用表达。 |
| B2 | [blnkfinance/blnk](reviews/02-ledger-engines/blnkfinance__blnk.md) | 交易与批量交易的 dry-run 预演 —— 外部 AI/MCP 写入前预检。 |
| B3 | [blnkfinance/blnk](reviews/02-ledger-engines/blnkfinance__blnk.md) | 对账规则 = 多条件 + 容差（金额 %、时间秒）+ 1:1 / 1:N / N:1 策略 + 断点续跑 + dry-run。 |
| B4 | [blnkfinance/blnk](reviews/02-ledger-engines/blnkfinance__blnk.md) | 资金溯源（FIFO/LIFO/按比例）—— 追踪上游额度与购买订单、渠道的对应关系。 |
| B5 | [blnkfinance/blnk](reviews/02-ledger-engines/blnkfinance__blnk.md) | 在途余额（inflight）与部分提交。 |
| B6 | [blnkfinance/blnk](reviews/02-ledger-engines/blnkfinance__blnk.md) | 余额监控阈值 + Webhook —— 例如上游站余额低于阈值告警。 |
| B7 | [blnkfinance/blnk](reviews/02-ledger-engines/blnkfinance__blnk.md) | parent_transaction 关联拆分/退款；effective_date 回填。 |
| LF1 | [devaccuracy/ledgerforge](reviews/02-ledger-engines/devaccuracy__ledgerforge.md) | MCP 默认只读、写能力需运营者显式开启并按 API Key 的 scope 逐次鉴权。 |
| LF2 | [devaccuracy/ledgerforge](reviews/02-ledger-engines/devaccuracy__ledgerforge.md) | 任务型 MCP 工具 + Resources + Prompts 的组合，而不是把 REST 接口一比一暴露。 |
| LF3 | [devaccuracy/ledgerforge](reviews/02-ledger-engines/devaccuracy__ledgerforge.md) | 工具返回值同时给出精确整数（minor units）与展示值，并在描述中声明以整数为准。 |
| LF4 | [devaccuracy/ledgerforge](reviews/02-ledger-engines/devaccuracy__ledgerforge.md) | 每次 MCP 写调用记录结构化审计（调用者、参数、结果）。 |
| LF5 | [devaccuracy/ledgerforge](reviews/02-ledger-engines/devaccuracy__ledgerforge.md) | 交易控制字段与自由元数据分离，后者不能改变前者。 |
| LF6 | [devaccuracy/ledgerforge](reviews/02-ledger-engines/devaccuracy__ledgerforge.md) | 只读完整性重放（独立验证账实一致）。 |
| LF7 | [devaccuracy/ledgerforge](reviews/02-ledger-engines/devaccuracy__ledgerforge.md) | API Key 策略：额度上限、白名单、委托只收窄 —— 外部 AI 接入的限权模型。 |
| LF8 | [devaccuracy/ledgerforge](reviews/02-ledger-engines/devaccuracy__ledgerforge.md) | 区分“已受理”与“已过账”。 |
| MD1 | [flash-oss/medici](reviews/02-ledger-engines/flash-oss__medici.md) | 层级账户路径 + 前缀聚合查询（汇总到父科目）。 |
| MD2 | [flash-oss/medici](reviews/02-ledger-engines/flash-oss__medici.md) | 分录 meta 可直接作为查询维度。 |
| MD3 | [flash-oss/medici](reviews/02-ledger-engines/flash-oss__medici.md) | 余额快照 = 最近快照 + 增量；快照按“账户+过滤条件”分别缓存。 |
| MD4 | [flash-oss/medici](reviews/02-ledger-engines/flash-oss__medici.md) | 只锁需要防透支的账户，降低锁竞争。 |
| MD5 | [flash-oss/medici](reviews/02-ledger-engines/flash-oss__medici.md) | void 凭证可选原日期冲回 + 原因必填。 |
| F1 | [formancehq/ledger](reviews/02-ledger-engines/formancehq__ledger.md) | 金额 = 整数 + 资产精度后缀，绝不用浮点 —— 杜绝舍入误差。 |
| F2 | [formancehq/ledger](reviews/02-ledger-engines/formancehq__ledger.md) | Posting 化的交易（每条腿自平衡）+ `@world` 边界账户 —— 模型最简且天然平衡。 |
| F3 | [formancehq/ledger](reviews/02-ledger-engines/formancehq__ledger.md) | Volumes（累计流入/流出）而不仅是余额 —— 发生额报表免扫全表。 |
| F4 | [formancehq/ledger](reviews/02-ledger-engines/formancehq__ledger.md) | 生效时间与入账时间分离 + PIT 查询 —— 支持补录、追溯任意时点余额。 |
| F5 | [formancehq/ledger](reviews/02-ledger-engines/formancehq__ledger.md) | Revert 生成反向交易、原交易只打标记、可选按原生效日冲回 —— 历史不可变。 |
| F6 | [formancehq/ledger](reviews/02-ledger-engines/formancehq__ledger.md) | 系统级幂等键 + 输入哈希冲突检测，覆盖所有写操作。 |
| F7 | [formancehq/ledger](reviews/02-ledger-engines/formancehq__ledger.md) | 用地址模式定义科目类型 + 强制模式 —— 科目表约束可配置。 |
| F8 | [formancehq/ledger](reviews/02-ledger-engines/formancehq__ledger.md) | 透支默认禁止 —— 余额护栏。 |
| F9 | [formancehq/ledger](reviews/02-ledger-engines/formancehq__ledger.md) | 每个接口声明权限 scope；审计记录失败的写入。 |
| F10 | [formancehq/ledger](reviews/02-ledger-engines/formancehq__ledger.md) | 可版本化的交易模板（Numscript 库）—— 手续费拆分等规则可复用、可追溯版本。 |
| SQ1 | [hoophq/sequence](reviews/02-ledger-engines/hoophq__sequence.md) | 分录行内嵌“过账后余额”，余额查询 O(1)，历史余额天然可得。 |
| SQ2 | [hoophq/sequence](reviews/02-ledger-engines/hoophq__sequence.md) | 按账户的哈希链 + “前驱唯一”约束 = 防篡改 + 乐观并发。 |
| SQ3 | [hoophq/sequence](reviews/02-ledger-engines/hoophq__sequence.md) | genesis 记录让每个账户链有确定起点。 |
| PG1 | [pgr0ss/pgledger](reviews/02-ledger-engines/pgr0ss__pgledger.md) | 账户级 `allow_negative_balance` / `allow_positive_balance` 双向约束（如资产类不得为负，费用类不得为正冲）。 |
| PG2 | [pgr0ss/pgledger](reviews/02-ledger-engines/pgr0ss__pgledger.md) | 分录存 previous/current balance + version，审计友好。 |
| PG3 | [pgr0ss/pgledger](reviews/02-ledger-engines/pgr0ss__pgledger.md) | `event_at`（业务时间）与 `created_at`（写入时间）分离。 |
| PG4 | [pgr0ss/pgledger](reviews/02-ledger-engines/pgr0ss__pgledger.md) | 带类型前缀的 ULID 主键（`acc_`、`txn_`、`ent_`）—— 日志与排错一眼可辨。 |
| PG5 | [pgr0ss/pgledger](reviews/02-ledger-engines/pgr0ss__pgledger.md) | 数据库层 CHECK 约束兜底（金额有限、正数、两端不同）；按 ID 顺序加锁防死锁。 |
| PG6 | [pgr0ss/pgledger](reviews/02-ledger-engines/pgr0ss__pgledger.md) | 账本写入与业务写入同库同事务。 |
| T1 | [tigerbeetle/tigerbeetle](reviews/02-ledger-engines/tigerbeetle__tigerbeetle.md) | 科目性质决定余额方向，数据库只存累计借贷 —— 报表口径统一。 |
| T2 | [tigerbeetle/tigerbeetle](reviews/02-ledger-engines/tigerbeetle__tigerbeetle.md) | 每个币种一个独立“账本分区”，跨币种必须通过换汇分录 —— 杜绝不同币种金额直接相加。 |
| T3 | [tigerbeetle/tigerbeetle](reviews/02-ledger-engines/tigerbeetle__tigerbeetle.md) | 手续费/点差单独成分录，不混进汇率 —— 事后可还原汇率与费用（对应我们的 Stripe 手续费、卡网加价）。 |
| T4 | [tigerbeetle/tigerbeetle](reviews/02-ledger-engines/tigerbeetle__tigerbeetle.md) | 两阶段（pending → post/void/expire）—— 表示“已付款未兑换”“已兑换未匹配订单”等在途状态。 |
| T5 | [tigerbeetle/tigerbeetle](reviews/02-ledger-engines/tigerbeetle__tigerbeetle.md) | 链接事件 = 原子多腿交易，错误精确定位到第一条失败。 |
| T6 | [tigerbeetle/tigerbeetle](reviews/02-ledger-engines/tigerbeetle__tigerbeetle.md) | 只追加更正 + 更正原因代码 + 关联 ID —— 完整更正时间线。 |
| T7 | [tigerbeetle/tigerbeetle](reviews/02-ledger-engines/tigerbeetle__tigerbeetle.md) | 客户端生成时间有序 ID 作为幂等键，重试返回 `exists`。 |
| T8 | [tigerbeetle/tigerbeetle](reviews/02-ledger-engines/tigerbeetle__tigerbeetle.md) | `code`（为什么）与 `user_data`（谁/何时/何地）的语义分工 —— 交易分类与外部实体关联的范式。 |
| T9 | [tigerbeetle/tigerbeetle](reviews/02-ledger-engines/tigerbeetle__tigerbeetle.md) | 资产精度一次定好、取足够大。 |
| T10 | [tigerbeetle/tigerbeetle](reviews/02-ledger-engines/tigerbeetle__tigerbeetle.md) | 余额约束（不得为负/区间）作为数据库级不变量。 |
| HK1 | [adamcharnock/django-hordak](reviews/03-accounting-libraries/adamcharnock__django-hordak.md) | 延迟约束触发器在提交时校验交易平衡（允许事务中逐腿插入）。 |
| HK2 | [adamcharnock/django-hordak](reviews/03-accounting-libraries/adamcharnock__django-hordak.md) | 货币交易账户（Trading account）法处理换汇，每笔交易单币种平衡，汇兑损益可从交易账户余额推出。 |
| HK3 | [adamcharnock/django-hordak](reviews/03-accounting-libraries/adamcharnock__django-hordak.md) | 账户允许币种列表；银行类账户单币种。 |
| HK4 | [adamcharnock/django-hordak](reviews/03-accounting-libraries/adamcharnock__django-hordak.md) | 账户编码树 + 自动维护完整编码。 |
| HK5 | [adamcharnock/django-hordak](reviews/03-accounting-libraries/adamcharnock__django-hordak.md) | 流水导入批次 → 流水行 → 关联交易（核对状态）→ 由流水生成交易。 |
| HK6 | [adamcharnock/django-hordak](reviews/03-accounting-libraries/adamcharnock__django-hordak.md) | 窗口函数计算每条分录前后余额（无需存储冗余列也能查询）。 |
| DL1 | [arrobalytics/django-ledger](reviews/03-accounting-libraries/arrobalytics__django-ledger.md) | 科目角色（role）分类体系：报表项目由角色决定，而不是靠科目名称/编码约定 —— 用户可自由命名科目，报表仍正确归类。 |
| DL2 | [arrobalytics/django-ledger](reviews/03-accounting-libraries/arrobalytics__django-ledger.md) | 凭证活动类型（经营/投资/筹资）自动推断 → 自动生成现金流量表。 |
| DL3 | [arrobalytics/django-ledger](reviews/03-accounting-libraries/arrobalytics__django-ledger.md) | 账簿/凭证两级 posted + locked 状态。 |
| DL4 | [arrobalytics/django-ledger](reviews/03-accounting-libraries/arrobalytics__django-ledger.md) | 结账余额快照加速报表。 |
| DL5 | [arrobalytics/django-ledger](reviews/03-accounting-libraries/arrobalytics__django-ledger.md) | 银行流水暂存表（staged）→ 匹配已有交易或生成新交易；fit_id 去重；支持拆分。 |
| DL6 | [arrobalytics/django-ledger](reviews/03-accounting-libraries/arrobalytics__django-ledger.md) | 主体单元（部门/项目）作为分录维度。 |
| PY1 | [datasignstech/pyluca](reviews/03-accounting-libraries/datasignstech__pyluca.md) | 业务事件与会计分录分离，过账规则完全配置化（事件类型 → 借贷科目 + 金额表达式）。 |
| PY2 | [datasignstech/pyluca](reviews/03-accounting-libraries/datasignstech__pyluca.md) | 规则变更后的“重放 + 差额调整”：重新计算应有余额，与现有账比较，仅追加调整分录 —— 正好对应我们反复遇到的“手续费规则改了，需要回溯修正历史”的场景。 |
| PY3 | [datasignstech/pyluca](reviews/03-accounting-libraries/datasignstech__pyluca.md) | 截至任意时刻的账本视图。 |
| PA1 | [ekmungai/python-accounting](reviews/03-accounting-libraries/ekmungai__python-accounting.md) | 单据类型 → 允许的主科目类型 / 明细科目类型（配置化校验）。 |
| PA2 | [ekmungai/python-accounting](reviews/03-accounting-libraries/ekmungai__python-accounting.md) | 期间三态：开放 / 调整中 / 已关闭。 |
| PA3 | [ekmungai/python-accounting](reviews/03-accounting-libraries/ekmungai__python-accounting.md) | 总账行哈希链（含上一行哈希 + 盐）检测数据库层篡改。 |
| PA4 | [ekmungai/python-accounting](reviews/03-accounting-libraries/ekmungai__python-accounting.md) | 核销（Assignment）：收款/付款与发票/账单的部分核销与未清余额、账龄表。 |
| PA5 | [ekmungai/python-accounting](reviews/03-accounting-libraries/ekmungai__python-accounting.md) | 报表结构配置化（按科目类型分区）。 |
| PA6 | [ekmungai/python-accounting](reviews/03-accounting-libraries/ekmungai__python-accounting.md) | 回收站式软删除（可恢复且留痕）。 |
| PA7 | [ekmungai/python-accounting](reviews/03-accounting-libraries/ekmungai__python-accounting.md) | 单据号按类型前缀 + 主体内唯一自动编号。 |
| DE1 | [envato/double_entry](reviews/03-accounting-libraries/envato__double_entry.md) | 转账类型白名单（from 科目、to 科目、业务代码）—— 杜绝不合规的科目组合（对应“交易类型模板只允许特定借贷科目”）。 |
| DE2 | [envato/double_entry](reviews/03-accounting-libraries/envato__double_entry.md) | 账户作用域（同一科目按用户/供应商/渠道拆分子账户）。 |
| DE3 | [envato/double_entry](reviews/03-accounting-libraries/envato__double_entry.md) | 每行存过账后余额 + 当前余额缓存表作为锁对象。 |
| DE4 | [envato/double_entry](reviews/03-accounting-libraries/envato__double_entry.md) | 定期核验任务（重算余额对比缓存）+ 检查结果入库。 |
| PL1 | [mbulat/plutus](reviews/03-accounting-libraries/mbulat__plutus.md) | 科目类型决定正常余额方向 + 备抵科目反转。 |
| PL2 | [mbulat/plutus](reviews/03-accounting-libraries/mbulat__plutus.md) | 凭证多态关联业务单据（commercial_document）。 |
| PL3 | [mbulat/plutus](reviews/03-accounting-libraries/mbulat__plutus.md) | 试算平衡为零作为全局不变量检查。 |
| AK1 | [akaunting/akaunting](reviews/04-smb-accounting/akaunting__akaunting.md) | 交易记录 `created_from`（来源渠道）+ `created_by` —— 追溯写入方（界面/API/导入/AI）。 |
| AK2 | [akaunting/akaunting](reviews/04-smb-accounting/akaunting__akaunting.md) | 对账会话：期间 + 对账单期末余额 + 勾选交易 + 差额为零才完成，并保存核对的交易清单。 |
| AK3 | [akaunting/akaunting](reviews/04-smb-accounting/akaunting__akaunting.md) | 重复交易模板生成子交易（parent_id）；拆分交易（split_id）。 |
| AK4 | [akaunting/akaunting](reviews/04-smb-accounting/akaunting__akaunting.md) | 币种表包含显示精度、符号、千分位等展示属性。 |
| AK5 | [akaunting/akaunting](reviews/04-smb-accounting/akaunting__akaunting.md) | 全面的领域事件钩子 → 模块化扩展。 |
| ES1 | [andrewdwallo/erpsaas](reviews/04-smb-accounting/andrewdwallo__erpsaas.md) | 未分类收入/未分类费用科目 + `reviewed` 标记：导入即入账但待复核，复核时改分类 —— 不阻塞流水入账，又保留待办。 |
| ES2 | [andrewdwallo/erpsaas](reviews/04-smb-accounting/andrewdwallo__erpsaas.md) | 备抵科目在类型层面完整覆盖。 |
| ES3 | [andrewdwallo/erpsaas](reviews/04-smb-accounting/andrewdwallo__erpsaas.md) | 交易保存时自动生成分录（简单录入 → 标准分录）。 |
| ES4 | [andrewdwallo/erpsaas](reviews/04-smb-accounting/andrewdwallo__erpsaas.md) | 金额与汇率都用整数定点存储。 |
| BG1 | [bigcapitalhq/bigcapital](reviews/04-smb-accounting/bigcapitalhq__bigcapital.md) | 科目类型元数据（正常方向、根类型、报表归属、是否允许多币种）集中定义。 |
| BG2 | [bigcapitalhq/bigcapital](reviews/04-smb-accounting/bigcapitalhq__bigcapital.md) | 银行流水三去向：分类（生成新交易）/ 匹配（已有交易）/ 排除；未处理流水队列。 |
| BG3 | [bigcapitalhq/bigcapital](reviews/04-smb-accounting/bigcapitalhq__bigcapital.md) | 银行规则：多条件 AND/OR + 方向 + 自动分类动作，命中后标记“已识别”待确认。 |
| BG4 | [bigcapitalhq/bigcapital](reviews/04-smb-accounting/bigcapitalhq__bigcapital.md) | 匹配候选按金额差、日期差排序，支持一对多与撤销。 |
| BG5 | [bigcapitalhq/bigcapital](reviews/04-smb-accounting/bigcapitalhq__bigcapital.md) | 按模块锁账 + 部分解锁区间（临时开放修改窗口并留痕）。 |
| BG6 | [bigcapitalhq/bigcapital](reviews/04-smb-accounting/bigcapitalhq__bigcapital.md) | 总账分录回指来源单据（reference_type/id），“按参考号查交易”报表。 |
| BG7 | [bigcapitalhq/bigcapital](reviews/04-smb-accounting/bigcapitalhq__bigcapital.md) | 导入导出带样例数据与映射校验。 |
| CR1 | [crater-invoice-inc/crater](reviews/04-smb-accounting/crater-invoice-inc__crater.md) | 原币金额 + 当时汇率 + 本位币金额三者同存并冻结（报表不随汇率变化）。 |
| CR2 | [crater-invoice-inc/crater](reviews/04-smb-accounting/crater-invoice-inc__crater.md) | 汇率提供方可配置 + 汇率获取日志（可追溯每个汇率从哪来）。 |
| CR3 | [crater-invoice-inc/crater](reviews/04-smb-accounting/crater-invoice-inc__crater.md) | 自定义字段机制（按实体类型定义字段与类型）。 |
| DB1 | [dubbl-org/dubbl](reviews/04-smb-accounting/dubbl-org__dubbl.md) | 分录行存原币整数金额 + 定点整数汇率；币种表定义真实小数位。 |
| DB2 | [dubbl-org/dubbl](reviews/04-smb-accounting/dubbl-org__dubbl.md) | 凭证来源（source_type/source_id）、作废原因、冲销互指、自动冲回日。 |
| DB3 | [dubbl-org/dubbl](reviews/04-smb-accounting/dubbl-org__dubbl.md) | 科目 reporting_code 与 is_system 标记。 |
| DB4 | [dubbl-org/dubbl](reviews/04-smb-accounting/dubbl-org__dubbl.md) | 审计日志记录 JSON 差异 + IP + UA。 |
| DB5 | [dubbl-org/dubbl](reviews/04-smb-accounting/dubbl-org__dubbl.md) | MCP OAuth 2.1：令牌只存哈希、每次校验成员关系与角色。 |
| DB6 | [dubbl-org/dubbl](reviews/04-smb-accounting/dubbl-org__dubbl.md) | MCP 工具按领域模块化，与 REST 共享服务层。 |
| DB7 | [dubbl-org/dubbl](reviews/04-smb-accounting/dubbl-org__dubbl.md) | 任意实体打标签（多对多）。 |
| AC1 | [erp-mafia/accounted](reviews/04-smb-accounting/erp-mafia__accounted.md) | 四轮确定性匹配 + 方法/置信度记录 + 低置信度存为建议。 |
| AC2 | [erp-mafia/accounted](reviews/04-smb-accounting/erp-mafia__accounted.md) | “参考号匹配必须带时间窗，绝不只凭描述”。 |
| AC3 | [erp-mafia/accounted](reviews/04-smb-accounting/erp-mafia__accounted.md) | MCP 工具契约：严格 schema、短描述、统一写结果信封、scope 默认拒绝、静态定义、体积上限。 |
| AC4 | [erp-mafia/accounted](reviews/04-smb-accounting/erp-mafia__accounted.md) | Agent briefing / 推荐工具组合 / 工具搜索 / “你是不是要找”。 |
| AC5 | [erp-mafia/accounted](reviews/04-smb-accounting/erp-mafia__accounted.md) | 只读 Resources 提供上下文（当前期间、待办、科目表、能力）。 |
| AC6 | [erp-mafia/accounted](reviews/04-smb-accounting/erp-mafia__accounted.md) | 无人值守模式服务端降权；连接级范围绑定。 |
| AC7 | [erp-mafia/accounted](reviews/04-smb-accounting/erp-mafia__accounted.md) | 归档文件 SHA-256 完整性。 |
| FB1 | [frappe/books](reviews/04-smb-accounting/frappe__books.md) | Schema 驱动的数据模型与表单、列表、校验（新系统前端阶段可参考：后端暴露 JSON Schema，前端自动生成表单）。 |
| FB2 | [frappe/books](reviews/04-smb-accounting/frappe__books.md) | 文档三态（草稿/已提交/已取消）与提交/取消钩子，取消时自动生成反向分录。 |
| FB3 | [frappe/books](reviews/04-smb-accounting/frappe__books.md) | 总账行的动态引用（来源单据类型 + 编号）与冲销互指。 |
| FB4 | [frappe/books](reviews/04-smb-accounting/frappe__books.md) | 尾差自动入“四舍五入”科目，且有明确阈值。 |
| FB5 | [frappe/books](reviews/04-smb-accounting/frappe__books.md) | 编号序列独立管理（前缀 + 自增）。 |
| FB6 | [frappe/books](reviews/04-smb-accounting/frappe__books.md) | 定点小数库处理金额。 |
| LS1 | [ledgersmb/LedgerSMB](reviews/04-smb-accounting/ledgersmb__LedgerSMB.md) | 余额检查点 = 结账日 + 各科目余额快照，检查点之前禁止过账（一个实体同时解决“锁账”和“报表加速”）。 |
| LS2 | [ledgersmb/LedgerSMB](reviews/04-smb-accounting/ledgersmb__LedgerSMB.md) | 分录行级的“已勾对 / 勾对日期 / 已对账日期”字段。 |
| LS3 | [ledgersmb/LedgerSMB](reviews/04-smb-accounting/ledgersmb__LedgerSMB.md) | 对账报告：对账单余额 vs 我方已勾对余额，逐行状态，完成后不可改。 |
| LS4 | [ledgersmb/LedgerSMB](reviews/04-smb-accounting/ledgersmb__LedgerSMB.md) | 业务单元多维度（类别 + 层级 + 生效期间）。 |
| LS5 | [ledgersmb/LedgerSMB](reviews/04-smb-accounting/ledgersmb__LedgerSMB.md) | 批次（batch）把一组凭证作为一个单元录入与过账，带控制号。 |
| LS6 | [ledgersmb/LedgerSMB](reviews/04-smb-accounting/ledgersmb__LedgerSMB.md) | 汇兑损益行显式标记（fx_transaction）。 |
| MY1 | [midday-ai/midday](reviews/04-smb-accounting/midday-ai__midday.md) | 召回（数据库粗筛）+ 精排（分项打分）两阶段匹配。 |
| MY2 | [midday-ai/midday](reviews/04-smb-accounting/midday-ai__midday.md) | 分项分数（名称/金额/日期/币种）与权重、加成、惩罚全部显式化，结果保存分项分数便于解释。 |
| MY3 | [midday-ai/midday](reviews/04-smb-accounting/midday-ai__midday.md) | 非对称日期窗口（按单据类型）。 |
| MY4 | [midday-ai/midday](reviews/04-smb-accounting/midday-ai__midday.md) | 从人工确认/拒绝中学习：别名、拒绝惩罚、阈值自校准。 |
| MY5 | [midday-ai/midday](reviews/04-smb-accounting/midday-ai__midday.md) | “建议”与“自动匹配”两级阈值。 |
| MY6 | [midday-ai/midday](reviews/04-smb-accounting/midday-ai__midday.md) | 匹配质量离线评估脚本。 |
| DO1 | [Dolibarr/dolibarr](reviews/05-erp-accounting/Dolibarr__dolibarr.md) | 辅助账（subledger）：主科目“应付账款”下按往来方的明细账号——总账科目保持精简，往来明细独立。 |
| DO2 | [Dolibarr/dolibarr](reviews/05-erp-accounting/Dolibarr__dolibarr.md) | 分类（科目绑定）与过账分离，绑定阶段可批量建议与修改。 |
| DO3 | [Dolibarr/dolibarr](reviews/05-erp-accounting/Dolibarr__dolibarr.md) | 核销码（完全/部分）。 |
| DO4 | [Dolibarr/dolibarr](reviews/05-erp-accounting/Dolibarr__dolibarr.md) | 验证即锁定（按日期范围批量写入验证时间）；导出时间标记。 |
| DO5 | [Dolibarr/dolibarr](reviews/05-erp-accounting/Dolibarr__dolibarr.md) | import_key 追踪导入批次；来源单据 + 明细行引用。 |
| OCA1 | [OCA/account-reconcile](reviews/05-erp-accounting/OCA__account-reconcile.md) | 暂挂科目：外部流水先入账到暂挂（待核对）科目，核对过程就是把暂挂余额逐步转到正确科目；暂挂余额 = 未处理金额。 |
| OCA2 | [OCA/account-reconcile](reviews/05-erp-accounting/OCA__account-reconcile.md) | 核对工作区可保存草稿（JSON），支持多人/多次完成。 |
| OCA3 | [OCA/account-reconcile](reviews/05-erp-accounting/OCA__account-reconcile.md) | 部分分配 + 剩余留暂挂；外币核对自动生成汇兑差额对冲行。 |
| OCA4 | [OCA/account-reconcile](reviews/05-erp-accounting/OCA__account-reconcile.md) | “付款中”中间状态（已付款未对账）。 |
| OF1 | [apache/ofbiz-framework](reviews/05-erp-accounting/apache__ofbiz-framework.md) | 科目类型间接层：业务规则引用“科目类型/用途”，由映射表解析为具体科目——更换科目表不改代码。 |
| OF2 | [apache/ofbiz-framework](reviews/05-erp-accounting/apache__ofbiz-framework.md) | 财务口径类型（实际/预算/预测）共用账本结构。 |
| OF3 | [apache/ofbiz-framework](reviews/05-erp-accounting/apache__ofbiz-framework.md) | 分录行原币 + 本位币；外部凭证号与对方交易号字段。 |
| OF4 | [apache/ofbiz-framework](reviews/05-erp-accounting/apache__ofbiz-framework.md) | 计划过账日（未来自动过账）。 |
| OF5 | [apache/ofbiz-framework](reviews/05-erp-accounting/apache__ofbiz-framework.md) | 核对记录（期初/核对后余额 + 分录级核对金额）。 |
| OF6 | [apache/ofbiz-framework](reviews/05-erp-accounting/apache__ofbiz-framework.md) | XBRL 分类映射（标准化报表编码）。 |
| EN1 | [frappe/erpnext](reviews/05-erp-accounting/frappe__erpnext.md) | 三层币种金额（本位币 / 科目币种 / 交易币种）+ 各自汇率，必要时加报告币种。 |
| EN2 | [frappe/erpnext](reviews/05-erp-accounting/frappe__erpnext.md) | 来源单据 + 明细行号（voucher_type/no/detail_no）精确追溯。 |
| EN3 | [frappe/erpnext](reviews/05-erp-accounting/frappe__erpnext.md) | 往来未清金额专用台账（Payment Ledger）与 GL 分离；核销/取消核销只动台账。 |
| EN4 | [frappe/erpnext](reviews/05-erp-accounting/frappe__erpnext.md) | 按单据类型分别关闭期间；冻结日期 + 豁免角色。 |
| EN5 | [frappe/erpnext](reviews/05-erp-accounting/frappe__erpnext.md) | 多账簿（finance_book）。 |
| EN6 | [frappe/erpnext](reviews/05-erp-accounting/frappe__erpnext.md) | 维度 + 维度过滤（某些科目必须/禁止某维度取值）。 |
| EN7 | [frappe/erpnext](reviews/05-erp-accounting/frappe__erpnext.md) | 尾差容差 + 自动尾差科目；超过容差报错。 |
| EN8 | [frappe/erpnext](reviews/05-erp-accounting/frappe__erpnext.md) | 期末汇率重估凭证。 |
| EN9 | [frappe/erpnext](reviews/05-erp-accounting/frappe__erpnext.md) | 重过账（Repost）：配置/规则修正后对指定单据重新生成分录。 |
| EN10 | [frappe/erpnext](reviews/05-erp-accounting/frappe__erpnext.md) | 账本健康监控与二分定位差异工具。 |
| EN11 | [frappe/erpnext](reviews/05-erp-accounting/frappe__erpnext.md) | 银行规则含金额区间与优先级。 |
| ID1 | [idempiere/idempiere](reviews/05-erp-accounting/idempiere__idempiere.md) | 过账流水线 + 明确的状态码（未平衡、不可换算、期间关闭、科目无效、错误、已过账）。 |
| ID2 | [idempiere/idempiere](reviews/05-erp-accounting/idempiere__idempiere.md) | 业务单据与会计事实分离，单据可“未过账/过账失败”并给出原因，修复后重过账。 |
| ID3 | [idempiere/idempiere](reviews/05-erp-accounting/idempiere__idempiere.md) | 原币平衡与本位币平衡分开处理：原币差额 → 暂挂科目，汇率舍入差额 → 币种平衡科目。 |
| ID4 | [idempiere/idempiere](reviews/05-erp-accounting/idempiere__idempiere.md) | 多套会计架构并行（不同本位币/准则）。 |
| ID5 | [idempiere/idempiere](reviews/05-erp-accounting/idempiere__idempiere.md) | 期间 × 单据类型的开关控制。 |
| ID6 | [idempiere/idempiere](reviews/05-erp-accounting/idempiere__idempiere.md) | GL 分配（按百分比拆到多个维度值）。 |
| ID7 | [idempiere/idempiere](reviews/05-erp-accounting/idempiere__idempiere.md) | 重过账前保存历史，可比较前后差异。 |
| OD1 | [odoo/odoo](reviews/05-erp-accounting/odoo__odoo.md) | balance（本位币带符号）为准，借贷派生；原币 amount_currency 并存。 |
| OD2 | [odoo/odoo](reviews/05-erp-accounting/odoo__odoo.md) | 部分核销表（两侧行、两种币种金额）+ 结清后的完全核销 + 自动汇兑差异凭证。 |
| OD3 | [odoo/odoo](reviews/05-erp-accounting/odoo__odoo.md) | 行级未核销余额（residual）随核销实时维护。 |
| OD4 | [odoo/odoo](reviews/05-erp-accounting/odoo__odoo.md) | 多类锁账日期 + 硬锁 + 临时锁账例外（用户、期限、原因）。 |
| OD5 | [odoo/odoo](reviews/05-erp-accounting/odoo__odoo.md) | 锁账期内的录入自动顺延到可用日期（可配置为拒绝或顺延）。 |
| OD6 | [odoo/odoo](reviews/05-erp-accounting/odoo__odoo.md) | 核对模型：金额区间、标签正则、往来方映射、容差（金额/百分比）、自动/手动、生成分录模板（金额可从文本正则提取）。 |
| OD7 | [odoo/odoo](reviews/05-erp-accounting/odoo__odoo.md) | 分析分摊 JSON（按百分比分配到多个维度值）。 |
| OD8 | [odoo/odoo](reviews/05-erp-accounting/odoo__odoo.md) | 已过账凭证哈希链 + 无断号安全序号。 |
| OD9 | [odoo/odoo](reviews/05-erp-accounting/odoo__odoo.md) | 序列断号检测。 |
| GE1 | [osbzr/gooderp_addons](reviews/05-erp-accounting/osbzr__gooderp_addons.md) | 凭证字 + 期间内连续凭证号 + 附件张数（国内会计习惯，便于纸质/电子凭证对应）。 |
| GE2 | [osbzr/gooderp_addons](reviews/05-erp-accounting/osbzr__gooderp_addons.md) | 科目“借方禁止/贷方禁止 + 提示语”——用数据规则防止错误方向记账。 |
| GE3 | [osbzr/gooderp_addons](reviews/05-erp-accounting/osbzr__gooderp_addons.md) | 辅助核算（客户/供应商/部门/项目）挂在凭证行上，科目设定需要哪些辅助核算。 |
| GE4 | [osbzr/gooderp_addons](reviews/05-erp-accounting/osbzr__gooderp_addons.md) | 只能向明细科目记账；会计要素分类（含“共同类”）。 |
| GE5 | [osbzr/gooderp_addons](reviews/05-erp-accounting/osbzr__gooderp_addons.md) | 系统生成的凭证只能从源单据撤销，保持单据与凭证一致。 |
| GE6 | [osbzr/gooderp_addons](reviews/05-erp-accounting/osbzr__gooderp_addons.md) | 期末调汇（按科目开关）。 |
| TR1 | [tryton/tryton](reviews/05-erp-accounting/tryton__tryton.md) | 期间三态 open/closed/locked，锁定不可逆。 |
| TR2 | [tryton/tryton](reviews/05-erp-accounting/tryton__tryton.md) | 凭证模板 = 关键字 + 表达式行（金额、描述可引用关键字）—— 业务模板的成熟范式。 |
| TR3 | [tryton/tryton](reviews/05-erp-accounting/tryton__tryton.md) | 流水规则：描述正则命名分组提取往来方/单据号/付款参考，金额表达式可用剩余金额 `pending`。 |
| TR4 | [tryton/tryton](reviews/05-erp-accounting/tryton__tryton.md) | 安全表达式求值 + Decimal 化 + 按币种舍入。 |
| TR5 | [tryton/tryton](reviews/05-erp-accounting/tryton__tryton.md) | origin 引用任意来源单据。 |
| GC1 | [Gnucash/gnucash](reviews/06-personal-finance/Gnucash__gnucash.md) | value（交易币种）+ amount（账户币种）双金额，交易按 value 平衡。 |
| GC2 | [Gnucash/gnucash](reviews/06-personal-finance/Gnucash__gnucash.md) | 分录级对账状态（未清/已清/已对账/冻结/作废）。 |
| GC3 | [Gnucash/gnucash](reviews/06-personal-finance/Gnucash__gnucash.md) | 批次（lot）+ 分配策略（FIFO/LIFO）——用于外币/额度成本与配对。 |
| GC4 | [Gnucash/gnucash](reviews/06-personal-finance/Gnucash__gnucash.md) | 不平衡自动落入 `Imbalance-币种` 科目并提示，绝不静默丢弃。 |
| GC5 | [Gnucash/gnucash](reviews/06-personal-finance/Gnucash__gnucash.md) | 占位（汇总）账户不可记账。 |
| GC6 | [Gnucash/gnucash](reviews/06-personal-finance/Gnucash__gnucash.md) | 价格库带来源与类型；有理数精确运算。 |
| GC7 | [Gnucash/gnucash](reviews/06-personal-finance/Gnucash__gnucash.md) | 作废保留痕迹（原值 + 原因）。 |
| KM1 | [KDE/kmymoney](reviews/06-personal-finance/KDE__kmymoney.md) | 收付款方匹配规则（名称/关键字/精确 + 默认分类），由对手名推断分类。 |
| KM2 | [KDE/kmymoney](reviews/06-personal-finance/KDE__kmymoney.md) | 导入匹配分三级（完全/疑似/无），疑似需人工确认。 |
| KM3 | [KDE/kmymoney](reviews/06-personal-finance/KDE__kmymoney.md) | 与计划交易匹配。 |
| KM4 | [KDE/kmymoney](reviews/06-personal-finance/KDE__kmymoney.md) | 对账报告留档。 |
| BCC1 | [TNT-Likely/BeeCount-Cloud](reviews/06-personal-finance/TNT-Likely__BeeCount-Cloud.md) | MCP 写入自动加来源标签/字段，AI 写入可筛选、可批量撤回。 |
| BCC2 | [TNT-Likely/BeeCount-Cloud](reviews/06-personal-finance/TNT-Likely__BeeCount-Cloud.md) | 歧义（多账本、重名）时返回候选而不是猜。 |
| BCC3 | [TNT-Likely/BeeCount-Cloud](reviews/06-personal-finance/TNT-Likely__BeeCount-Cloud.md) | MCP 工具复用 REST 业务层（同一校验、同一审计）。 |
| BCC4 | [TNT-Likely/BeeCount-Cloud](reviews/06-personal-finance/TNT-Likely__BeeCount-Cloud.md) | MCP 调用日志 + 查询接口。 |
| BCC5 | [TNT-Likely/BeeCount-Cloud](reviews/06-personal-finance/TNT-Likely__BeeCount-Cloud.md) | 变更日志 + 投影 + 快照的同步架构（若未来需要多端实时）。 |
| BC-A1 | [TNT-Likely/BeeCount](reviews/06-personal-finance/TNT-Likely__BeeCount.md) | “本地优先 + 多种同步后端可选”：数据可随时导出带走（SQLite + 附件）。 |
| BC-A2 | [TNT-Likely/BeeCount](reviews/06-personal-finance/TNT-Likely__BeeCount.md) | 多种快捷记账入口（截图 OCR、语音、文本 → AI 解析成草稿 → 用户确认）。 |
| BC-A3 | [TNT-Likely/BeeCount](reviews/06-personal-finance/TNT-Likely__BeeCount.md) | 中文/繁体/英文完整本地化。 |
| AT1 | [actualbudget/actual](reviews/06-personal-finance/actualbudget__actual.md) | 规则分阶段（pre/normal/post）+ 按特异性自动排序 —— 解决规则冲突与顺序依赖。 |
| AT2 | [actualbudget/actual](reviews/06-personal-finance/actualbudget__actual.md) | `isapprox`、`isbetween` 金额条件；拆分动作（固定/百分比/剩余）。 |
| AT3 | [actualbudget/actual](reviews/06-personal-finance/actualbudget__actual.md) | 导入匹配：外部唯一号精确匹配 → 金额+日期窗口模糊匹配 → 合并而不覆盖人工字段；已核对记录受保护。 |
| AT4 | [actualbudget/actual](reviews/06-personal-finance/actualbudget__actual.md) | 从人工修改中学习生成规则。 |
| AT5 | [actualbudget/actual](reviews/06-personal-finance/actualbudget__actual.md) | 计划交易的容差匹配（金额约等、日期窗口）。 |
| AT6 | [actualbudget/actual](reviews/06-personal-finance/actualbudget__actual.md) | 字段级变更消息 + HLC 时钟（如需离线/多端）。 |
| CB1 | [dingdangdog/cashbook](reviews/06-personal-finance/dingdangdog__cashbook.md) | 流水来源（origin）与归属人（attribution）分开记录。 |
| CB2 | [dingdangdog/cashbook](reviews/06-personal-finance/dingdangdog__cashbook.md) | “平账”：把互相抵消的流水（如转账两端、退款与原支出）标记为已平账，统计时剔除；可选择忽略。 |
| CB3 | [dingdangdog/cashbook](reviews/06-personal-finance/dingdangdog__cashbook.md) | 应收台账：发生流水 ↔ 结清流水、预计/实际日期、坏账类状态。 |
| CB4 | [dingdangdog/cashbook](reviews/06-personal-finance/dingdangdog__cashbook.md) | “不计收支”类型（内部转移不进统计）。 |
| FF1 | [firefly-iii/firefly-iii](reviews/06-personal-finance/firefly-iii__firefly-iii.md) | 交易对手作为账户（收款方=费用账户、付款方=收入账户）——对手统计免额外维度。 |
| FF2 | [firefly-iii/firefly-iii](reviews/06-personal-finance/firefly-iii__firefly-iii.md) | 拆分交易组（group → journals → postings）。 |
| FF3 | [firefly-iii/firefly-iii](reviews/06-personal-finance/firefly-iii__firefly-iii.md) | 多种业务日期（发生日、记账日、到期日、付款日、发票日）作为可选元数据。 |
| FF4 | [firefly-iii/firefly-iii](reviews/06-personal-finance/firefly-iii__firefly-iii.md) | 规则引擎：规则组 + strict/非 strict + 三级 stop_processing + 丰富触发器 + 动作表达式 + 对历史批量执行。 |
| FF5 | [firefly-iii/firefly-iii](reviews/06-personal-finance/firefly-iii__firefly-iii.md) | 搜索语法与规则触发器同源（同一套操作符），学习成本低。 |
| FF6 | [firefly-iii/firefly-iii](reviews/06-personal-finance/firefly-iii__firefly-iii.md) | 导入去重哈希 + API 参数“重复即报错”。 |
| FF7 | [firefly-iii/firefly-iii](reviews/06-personal-finance/firefly-iii__firefly-iii.md) | 核对产生“核对差额”交易并标记已核对。 |
| FF8 | [firefly-iii/firefly-iii](reviews/06-personal-finance/firefly-iii__firefly-iii.md) | Webhook：触发 × 响应 × 投递记录与重试。 |
| MN1 | [getmoneynote/moneynote-api](reviews/06-personal-finance/getmoneynote__moneynote-api.md) | 账簿级默认值（默认账户/分类/币种）—— 减少录入。 |
| MN2 | [getmoneynote/moneynote-api](reviews/06-personal-finance/getmoneynote__moneynote-api.md) | 流水“已确认/未确认”与“计入统计/不计入统计”两个独立开关。 |
| MN3 | [getmoneynote/moneynote-api](reviews/06-personal-finance/getmoneynote__moneynote-api.md) | 流水按金额拆分到多个分类（多对多带金额）。 |
| MN4 | [getmoneynote/moneynote-api](reviews/06-personal-finance/getmoneynote__moneynote-api.md) | 原币金额 + 账簿币种换算金额同存。 |
| GF1 | [ghostfolio/ghostfolio](reviews/06-personal-finance/ghostfolio__ghostfolio.md) | 派生币种 = 固定倍率声明：可用来表达“上游额度美元 USD-credit 与 CNY 按 1:1 结算”这类内部换算约定，而不是把它伪装成真实汇率。 |
| GF2 | [ghostfolio/ghostfolio](reviews/06-personal-finance/ghostfolio__ghostfolio.md) | 历史汇率缺失时经基准币种间接换算，并能区分实时/历史口径。 |
| GF3 | [ghostfolio/ghostfolio](reviews/06-personal-finance/ghostfolio__ghostfolio.md) | 计算器接口 + 工厂选择不同算法（报表口径可插拔）。 |
| CT1 | [glink25/Cent](reviews/06-personal-finance/glink25__Cent.md) | 以 Git 提交历史作为天然的审计轨迹与可回滚版本（每次保存 = 一次提交）。 |
| CT2 | [glink25/Cent](reviews/06-personal-finance/glink25__Cent.md) | 二级分类 + 自定义标签 + 预算 + 统计的极简组合；PWA 离线可用。 |
| CT3 | [glink25/Cent](reviews/06-personal-finance/glink25__Cent.md) | 协作权限直接复用外部平台（仓库协作者）。 |
| KR1 | [kresusapp/kresus](reviews/06-personal-finance/kresusapp__kresus.md) | 重复检测的负面规则（同批导入、定期交易、已人工分类不同 → 不是重复）。 |
| KR2 | [kresusapp/kresus](reviews/06-personal-finance/kresusapp__kresus.md) | “不是重复”的人工判定持久化（忽略对表），避免反复打扰。 |
| KR3 | [kresusapp/kresus](reviews/06-personal-finance/kresusapp__kresus.md) | importDate 与交易日期分开。 |
| KR4 | [kresusapp/kresus](reviews/06-personal-finance/kresusapp__kresus.md) | 阈值提醒。 |
| EZ1 | [mayswind/ezbookkeeping](reviews/06-personal-finance/mayswind__ezbookkeeping.md) | 支付宝 / 微信 / 京东等国内账单导入解析器（字段含义、状态过滤、收支方向判断）。 |
| EZ2 | [mayswind/ezbookkeeping](reviews/06-personal-finance/mayswind__ezbookkeeping.md) | 交易时间 + 原始时区偏移。 |
| EZ3 | [mayswind/ezbookkeeping](reviews/06-personal-finance/mayswind__ezbookkeeping.md) | MCP 写工具的 dry_run 与“过账后余额”反馈；参数支持名称解析。 |
| EZ4 | [mayswind/ezbookkeeping](reviews/06-personal-finance/mayswind__ezbookkeeping.md) | MCP/API 令牌分类型管理与吊销。 |
| EZ5 | [mayswind/ezbookkeeping](reviews/06-personal-finance/mayswind__ezbookkeeping.md) | 请求级重复提交检查。 |
| EZ6 | [mayswind/ezbookkeeping](reviews/06-personal-finance/mayswind__ezbookkeeping.md) | AI 识别截图生成交易表（作为导入的一种来源，仍需预览确认）。 |
| EZ7 | [mayswind/ezbookkeeping](reviews/06-personal-finance/mayswind__ezbookkeeping.md) | Agent Skill（技能文档 + 脚本）作为 MCP 之外的另一种 AI 接入方式。 |
| MX1 | [moneymanagerex/moneymanagerex](reviews/06-personal-finance/moneymanagerex__moneymanagerex.md) | 交易状态含“待跟进”“疑似重复”——人工复核队列的标记方式。 |
| MX2 | [moneymanagerex/moneymanagerex](reviews/06-personal-finance/moneymanagerex__moneymanagerex.md) | 自定义字段（作用对象 + 类型 + 属性），通用且可查询。 |
| MX3 | [moneymanagerex/moneymanagerex](reviews/06-personal-finance/moneymanagerex__moneymanagerex.md) | 跨币种转账两端金额分别记录。 |
| MX4 | [moneymanagerex/moneymanagerex](reviews/06-personal-finance/moneymanagerex__moneymanagerex.md) | 收付款方别名/正则映射与合并。 |
| MX5 | [moneymanagerex/moneymanagerex](reviews/06-personal-finance/moneymanagerex__moneymanagerex.md) | 软删除时间戳 + 最后更新时间。 |
| RT1 | [rotki/rotki](reviews/06-personal-finance/rotki__rotki.md) | 金额类型封装禁止浮点（代码规范层面的硬约束）。 |
| RT2 | [rotki/rotki](reviews/06-personal-finance/rotki__rotki.md) | 成本基础方法可插拔；缺失购入记录作为报告中的显式问题。 |
| RT3 | [rotki/rotki](reviews/06-personal-finance/rotki__rotki.md) | 规则两级：按类型的默认规则 + 按单个事件的覆盖。 |
| RT4 | [rotki/rotki](reviews/06-personal-finance/rotki__rotki.md) | 报告保存计算设置快照 + 调试导出，保证可复算。 |
| SR1 | [we-promise/sure](reviews/06-personal-finance/we-promise__sure.md) | 字段级来源 + 用户修改锁定：自动化（规则/AI/导入）不得覆盖人工确认过的字段。 |
| SR2 | [we-promise/sure](reviews/06-personal-finance/we-promise__sure.md) | 余额锚点 + 外部报告余额作为核对点（重置漂移）——类似“余额断言”，但用于计算而非仅校验。 |
| SR3 | [we-promise/sure](reviews/06-personal-finance/we-promise__sure.md) | 反向计算（已知当前余额倒推历史）适合只有“当前余额截图”的上游站点。 |
| SR4 | [we-promise/sure](reviews/06-personal-finance/we-promise__sure.md) | 每日余额物化表。 |
| OR-1 | [GrandmasterTash/OpenRec](reviews/07-import-reconciliation/GrandmasterTash__OpenRec.md) | 未匹配池：未匹配记录跨批次持续参与匹配。 |
| OR-2 | [GrandmasterTash/OpenRec](reviews/07-import-reconciliation/GrandmasterTash__OpenRec.md) | 按键分组 + 约束规则（净额为零、容差、自定义表达式）定义“什么算对平”。 |
| OR-3 | [GrandmasterTash/OpenRec](reviews/07-import-reconciliation/GrandmasterTash__OpenRec.md) | 派生字段（从文本提取键）用安全脚本/表达式实现。 |
| OR-4 | [GrandmasterTash/OpenRec](reviews/07-import-reconciliation/GrandmasterTash__OpenRec.md) | ChangeSet：对未匹配数据的人工修正（忽略/改值）作为有序、可追溯的指令日志。 |
| OR-5 | [GrandmasterTash/OpenRec](reviews/07-import-reconciliation/GrandmasterTash__OpenRec.md) | 匹配作业结果归档。 |
| BG-1 | [beancount/beangulp](reviews/07-import-reconciliation/beancount__beangulp.md) | 导入器统一接口：识别、归属账户、文件日期、抽取、去重、归档命名。 |
| BG-2 | [beancount/beangulp](reviews/07-import-reconciliation/beancount__beangulp.md) | 原始文件按账户/日期归档，与分录互相引用。 |
| BG-3 | [beancount/beangulp](reviews/07-import-reconciliation/beancount__beangulp.md) | 相似度去重窗口 + 金额容差。 |
| BG-4 | [beancount/beangulp](reviews/07-import-reconciliation/beancount__beangulp.md) | 导入器样例文件 + 期望输出的回归测试。 |
| SI-1 | [beancount/smart_importer](reviews/07-import-reconciliation/beancount__smart_importer.md) | 以历史已确认交易为训练集的分类建议（插件式，可关闭）。 |
| SI-2 | [beancount/smart_importer](reviews/07-import-reconciliation/beancount__smart_importer.md) | 预测与规则并存：规则优先，模型补充，置信度低则不填。 |
| MP-1 | [benjamin-awd/monopoly](reviews/07-import-reconciliation/benjamin-awd__monopoly.md) | 解析结果的合计校验（解析合计必须能在原文档的数字中找到），失败拒绝导入。 |
| MP-2 | [benjamin-awd/monopoly](reviews/07-import-reconciliation/benjamin-awd__monopoly.md) | 银行特征指纹自动识别模板 + 通用解析器回退。 |
| MP-3 | [benjamin-awd/monopoly](reviews/07-import-reconciliation/benjamin-awd__monopoly.md) | PDF 文本层优先，OCR/LLM 作为回退（需额外校验）。 |
| DEG1 | [deb-sig/double-entry-generator](reviews/07-import-reconciliation/deb-sig__double-entry-generator.md) | 解析器 → 中间表示 → 生成器 三段式，账单源插件化。 |
| DEG2 | [deb-sig/double-entry-generator](reviews/07-import-reconciliation/deb-sig__double-entry-generator.md) | 支付宝/微信字段语义：交易对方、商品、平台订单号/商户订单号、收/支/不计收支、交易状态（成功/退款成功/关闭）、支付方式。 |
| DEG3 | [deb-sig/double-entry-generator](reviews/07-import-reconciliation/deb-sig__double-entry-generator.md) | 规则：时段、金额区间、多关键字、精确/包含、忽略；后者覆盖前者。 |
| DEG4 | [deb-sig/double-entry-generator](reviews/07-import-reconciliation/deb-sig__double-entry-generator.md) | 未匹配 → FIXME 科目（待处理）。 |
| DEG5 | [deb-sig/double-entry-generator](reviews/07-import-reconciliation/deb-sig__double-entry-generator.md) | 退款与原交易配对（订单号前缀 + 金额）。 |
| BT1 | [dhr2333/Beancount-Trans](reviews/07-import-reconciliation/dhr2333__Beancount-Trans.md) | 关键字映射 + 映射模板（可版本化、可共享）——非技术用户也能维护分类规则。 |
| BT2 | [dhr2333/Beancount-Trans](reviews/07-import-reconciliation/dhr2333__Beancount-Trans.md) | 导入管道分步骤、统一错误收集、可缓存重放。 |
| BT3 | [dhr2333/Beancount-Trans](reviews/07-import-reconciliation/dhr2333__Beancount-Trans.md) | 退款沿用原单科目（预扫描原支付行）。 |
| BT4 | [dhr2333/Beancount-Trans](reviews/07-import-reconciliation/dhr2333__Beancount-Trans.md) | 跨多次上传的重叠账单去重。 |
| BT5 | [dhr2333/Beancount-Trans](reviews/07-import-reconciliation/dhr2333__Beancount-Trans.md) | 统一审核队列（待确认条目，跨来源）。 |
| BT6 | [dhr2333/Beancount-Trans](reviews/07-import-reconciliation/dhr2333__Beancount-Trans.md) | 周期对账任务：按 RRULE 生成“对账待办”，记录对账日期、对账条目、差额如何分配，并可撤销。 |
| BT7 | [dhr2333/Beancount-Trans](reviews/07-import-reconciliation/dhr2333__Beancount-Trans.md) | MCP 只读查询走 BQL（领域查询语言）。 |
| LA-1 | [egh/ledger-autosync](reviews/07-import-reconciliation/egh__ledger-autosync.md) | 外部 ID = 来源账户 + 来源交易号，存于交易元数据作为幂等键。 |
| LA-2 | [egh/ledger-autosync](reviews/07-import-reconciliation/egh__ledger-autosync.md) | 同步时附带外部余额断言。 |
| LA-3 | [egh/ledger-autosync](reviews/07-import-reconciliation/egh__ledger-autosync.md) | 只追加、不修改既有数据。 |
| DI-1 | [firefly-iii/data-importer](reviews/07-import-reconciliation/firefly-iii__data-importer.md) | 导入器作为独立的 API 客户端（解耦），主系统只暴露稳定的写 API（含幂等/去重）。 |
| DI-2 | [firefly-iii/data-importer](reviews/07-import-reconciliation/firefly-iii__data-importer.md) | 列角色体系 + 值映射 + 可保存的导入配置 JSON。 |
| DI-3 | [firefly-iii/data-importer](reviews/07-import-reconciliation/firefly-iii__data-importer.md) | 去重两模式：内容哈希 / 指定列组合的伪外部 ID。 |
| DI-4 | [firefly-iii/data-importer](reviews/07-import-reconciliation/firefly-iii__data-importer.md) | 逐行错误与警告报告。 |
| BI-1 | [jbms/beancount-import](reviews/07-import-reconciliation/jbms__beancount-import.md) | 多来源交叉合并：同一业务在不同来源各有一条记录（如“微信付款”+“上游站兑换记录”+“卡网订单”），合并为一笔带全部证据的交易。 |
| BI-2 | [jbms/beancount-import](reviews/07-import-reconciliation/jbms__beancount-import.md) | 权威来源标记（cleared）约束匹配：来自同一权威来源的两条记录不能互相合并。 |
| BI-3 | [jbms/beancount-import](reviews/07-import-reconciliation/jbms__beancount-import.md) | 候选展示“将新增/删除哪些行”。 |
| BI-4 | [jbms/beancount-import](reviews/07-import-reconciliation/jbms__beancount-import.md) | 来源 ID 写入交易元数据作为去重依据。 |
| HS-1 | [juspay/hyperswitch-reconciliation](reviews/07-import-reconciliation/juspay__hyperswitch-reconciliation.md) | 预期-确认模型：来源侧记录生成“预期条目”，目标侧记录到达后确认；部分确认 → Expected，全部确认 → Posted，不符 → Mismatched，异常 → 人工复核。 |
| HS-2 | [juspay/hyperswitch-reconciliation](reviews/07-import-reconciliation/juspay__hyperswitch-reconciliation.md) | 对账交易版本化（旧版本归档、新版本演进），过程可追溯。 |
| HS-3 | [juspay/hyperswitch-reconciliation](reviews/07-import-reconciliation/juspay__hyperswitch-reconciliation.md) | 规则 = 触发 + 优先级 + 检索标识 + 匹配规则 + 策略（1:1/1:N/N:1/N:N），规则 schema 版本化。 |
| HS-4 | [juspay/hyperswitch-reconciliation](reviews/07-import-reconciliation/juspay__hyperswitch-reconciliation.md) | 数据管道：获取（ingestion）→ 转换（transformation）→ 暂存（staging）→ 对账。 |
| HS-5 | [juspay/hyperswitch-reconciliation](reviews/07-import-reconciliation/juspay__hyperswitch-reconciliation.md) | 金额类型强约束（i64 最小单位 + 币种，异币种运算报错）；生效时间必填。 |
| HS-6 | [juspay/hyperswitch-reconciliation](reviews/07-import-reconciliation/juspay__hyperswitch-reconciliation.md) | AI 开发文档分层（规则、关键路径、领域笔记）。 |
| OS-1 | [kedder/ofxstatement](reviews/07-import-reconciliation/kedder__ofxstatement.md) | 标准化对账单模型：账户、币种、期间、期初/期末余额 + 带唯一 ID 的明细行。 |
| OS-2 | [kedder/ofxstatement](reviews/07-import-reconciliation/kedder__ofxstatement.md) | 期初 + 明细 = 期末 的硬校验。 |
| OS-3 | [kedder/ofxstatement](reviews/07-import-reconciliation/kedder__ofxstatement.md) | 无源 ID 时的稳定 ID 生成规则（内容哈希 + 同日序号）。 |
| SB-1 | [StdioA/beancount-mcp](reviews/08-mcp-ai-access/StdioA__beancount-mcp.md) | 交易 ID 稳定可引用（但应是持久主键，不是内容哈希）。 |
| SB-2 | [StdioA/beancount-mcp](reviews/08-mcp-ai-access/StdioA__beancount-mcp.md) | 外部修改（文件/数据库）后自动刷新缓存。 |
| XR-1 | [XeroAPI/xero-mcp-server](reviews/08-mcp-ai-access/XeroAPI__xero-mcp-server.md) | 工具按 CRUD 动词组织，命名统一；报表类工具独立。 |
| XR-2 | [XeroAPI/xero-mcp-server](reviews/08-mcp-ai-access/XeroAPI__xero-mcp-server.md) | 描述中写清前置调用（先查科目）与会计约束（借贷平衡、金额符号）。 |
| XR-3 | [XeroAPI/xero-mcp-server](reviews/08-mcp-ai-access/XeroAPI__xero-mcp-server.md) | 写入默认草稿；返回深链接供人核对。 |
| XR-4 | [XeroAPI/xero-mcp-server](reviews/08-mcp-ai-access/XeroAPI__xero-mcp-server.md) | 细粒度 scope。 |
| MO-1 | [erpipe-org/mcp-odoo](reviews/08-mcp-ai-access/erpipe-org__mcp-odoo.md) | preview → validate（服务端实时校验 + 登记令牌，TTL）→ execute（只接受令牌） 三段式写入；令牌是规范化请求的哈希，执行时内容不可更改。 |
| MO-2 | [erpipe-org/mcp-odoo](reviews/08-mcp-ai-access/erpipe-org__mcp-odoo.md) | 写入默认关闭；业务动作白名单可版本化并附审核信息；配置错误时一律禁止。 |
| MO-3 | [erpipe-org/mcp-odoo](reviews/08-mcp-ai-access/erpipe-org__mcp-odoo.md) | MCP 工具注解（read-only / destructive / idempotent）。 |
| MO-4 | [erpipe-org/mcp-odoo](reviews/08-mcp-ai-access/erpipe-org__mcp-odoo.md) | 字段级读取 ACL + `redacted_fields` 提示。 |
| MO-5 | [erpipe-org/mcp-odoo](reviews/08-mcp-ai-access/erpipe-org__mcp-odoo.md) | 写路径审计 JSONL（只存令牌摘要）。 |
| MO-6 | [erpipe-org/mcp-odoo](reviews/08-mcp-ai-access/erpipe-org__mcp-odoo.md) | 按工具限流；写入不自动重试，读取指数退避。 |
| MO-7 | [erpipe-org/mcp-odoo](reviews/08-mcp-ai-access/erpipe-org__mcp-odoo.md) | OAuth 内省 + audience + scopes。 |
| FM-1 | [etnperlong/firefly-iii-mcp](reviews/08-mcp-ai-access/etnperlong__firefly-iii-mcp.md) | 从 OpenAPI 自动生成 MCP 工具，保证与 REST 一致。 |
| FM-2 | [etnperlong/firefly-iii-mcp](reviews/08-mcp-ai-access/etnperlong__firefly-iii-mcp.md) | 工具按领域标签分组，提供“预设工具集”控制暴露范围与上下文体积。 |
| FM-3 | [etnperlong/firefly-iii-mcp](reviews/08-mcp-ai-access/etnperlong__firefly-iii-mcp.md) | 凭证放请求头而非 URL。 |
| AB-1 | [henfrydls/actual-budget-mcp](reviews/08-mcp-ai-access/henfrydls__actual-budget-mcp.md) | 破坏性操作“先预览、再确认”，按名称定位时要求回显确切名称。 |
| AB-2 | [henfrydls/actual-budget-mcp](reviews/08-mcp-ai-access/henfrydls__actual-budget-mcp.md) | 创建前查重并返回已存在记录。 |
| AB-3 | [henfrydls/actual-budget-mcp](reviews/08-mcp-ai-access/henfrydls__actual-budget-mcp.md) | 只读模式隐藏写工具。 |
| AB-4 | [henfrydls/actual-budget-mcp](reviews/08-mcp-ai-access/henfrydls__actual-budget-mcp.md) | 分析型工具（预测、趋势、预算对比、余额差额解释）。 |
| AB-5 | [henfrydls/actual-budget-mcp](reviews/08-mcp-ai-access/henfrydls__actual-budget-mcp.md) | 名称解析 + 歧义候选；自然语言日期。 |
| HM-1 | [iiAtlas/hledger-mcp](reviews/08-mcp-ai-access/iiAtlas__hledger-mcp.md) | 写入流水线：工作副本 → 全量校验 → dryRun 返回 / 备份 + 原子提交。 |
| HM-2 | [iiAtlas/hledger-mcp](reviews/08-mcp-ai-access/iiAtlas__hledger-mcp.md) | 修改/删除必须携带“期望的当前内容”（乐观并发前置条件，相当于 If-Match/ETag）。 |
| HM-3 | [iiAtlas/hledger-mcp](reviews/08-mcp-ai-access/iiAtlas__hledger-mcp.md) | 先查后改：find 返回稳定定位信息，修改工具只接受该定位信息。 |
| HM-4 | [iiAtlas/hledger-mcp](reviews/08-mcp-ai-access/iiAtlas__hledger-mcp.md) | 服务器级只读开关 + 每个写工具的 dryRun；只读下允许 dryRun。 |
| HM-5 | [iiAtlas/hledger-mcp](reviews/08-mcp-ai-access/iiAtlas__hledger-mcp.md) | 报表工具齐全（资产负债、损益、现金流、统计），参数与 CLI 一致。 |
| QB-1 | [intuit/quickbooks-online-mcp-server](reviews/08-mcp-ai-access/intuit__quickbooks-online-mcp-server.md) | 搜索类工具统一的查询参数（条件数组、排序、分页、只计数、取全部）。 |
| QB-2 | [intuit/quickbooks-online-mcp-server](reviews/08-mcp-ai-access/intuit__quickbooks-online-mcp-server.md) | 描述中点明最常见的结构性错误。 |
| QB-3 | [intuit/quickbooks-online-mcp-server](reviews/08-mcp-ai-access/intuit__quickbooks-online-mcp-server.md) | 报表工具覆盖三大报表、总账、账龄。 |
| NM-1 | [norman-finance/norman-mcp-server](reviews/08-mcp-ai-access/norman-finance__norman-mcp-server.md) | 领域任务级工具，命名用业务动词（categorize / verify / link / find_missing_documents）。 |
| NM-2 | [norman-finance/norman-mcp-server](reviews/08-mcp-ai-access/norman-finance__norman-mcp-server.md) | 规则 dry-run 预览 + 首个命中 + 命中统计。 |
| NM-3 | [norman-finance/norman-mcp-server](reviews/08-mcp-ai-access/norman-finance__norman-mcp-server.md) | 错误分类：不可重试的业务错误明确说明，并给出下一步。 |
| NM-4 | [norman-finance/norman-mcp-server](reviews/08-mcp-ai-access/norman-finance__norman-mcp-server.md) | 账套上下文 Resource（本位币、科目表、业务约定）供模型首先读取。 |
| NM-5 | [norman-finance/norman-mcp-server](reviews/08-mcp-ai-access/norman-finance__norman-mcp-server.md) | 工作流剧本（Skills / Prompts）：月结、对账、补票据，标出需人工确认的节点。 |
| NM-6 | [norman-finance/norman-mcp-server](reviews/08-mcp-ai-access/norman-finance__norman-mcp-server.md) | `tool_filter`：同一代码按部署暴露不同工具子集（预设）。 |
| NM-7 | [norman-finance/norman-mcp-server](reviews/08-mcp-ai-access/norman-finance__norman-mcp-server.md) | 交易“核验（verified）”状态作为月结前置条件；缺票据交易清单。 |
| EM-1 | [rakeshgangwar/erpnext-mcp-server](reviews/08-mcp-ai-access/rakeshgangwar__erpnext-mcp-server.md) | 资源模板 `scheme://{type}/{id}` 统一按 ID 读取实体。 |
| EM-2 | [rakeshgangwar/erpnext-mcp-server](reviews/08-mcp-ai-access/rakeshgangwar__erpnext-mcp-server.md) | 默认精简返回 + `verbose` 开关，控制 token 消耗。 |
| EM-3 | [rakeshgangwar/erpnext-mcp-server](reviews/08-mcp-ai-access/rakeshgangwar__erpnext-mcp-server.md) | 在工具描述中说明状态机约束（草稿 → 过账 → 冲正）。 |
| ST-1 | [stripe/ai](reviews/08-mcp-ai-access/stripe__ai.md) | MCP 权限 = 调用凭证（API Key/OAuth token）的权限，单一权限模型。 |
| ST-2 | [stripe/ai](reviews/08-mcp-ai-access/stripe__ai.md) | 连接级上下文绑定（固定账簿/主体），所有调用自动限定范围。 |
| ST-3 | [stripe/ai](reviews/08-mcp-ai-access/stripe__ai.md) | 工具定义单一来源，自动导出到多种 Agent 框架。 |
| ST-4 | [stripe/ai](reviews/08-mcp-ai-access/stripe__ai.md) | 文档检索工具 + LLM 可读文档（.md）。 |
| ST-5 | [stripe/ai](reviews/08-mcp-ai-access/stripe__ai.md) | Agent 任务基准与评分器。 |
| ST-6 | [stripe/ai](reviews/08-mcp-ai-access/stripe__ai.md) | 请求头标记来源（MCP/toolkit），服务端可审计。 |
| BQ-1 | [vanto/beanquery-mcp](reviews/08-mcp-ai-access/vanto__beanquery-mcp.md) | 用 Resources 提供“查询 schema + 账户词表”，模型自行组合查询。 |
| BQ-2 | [vanto/beanquery-mcp](reviews/08-mcp-ai-access/vanto__beanquery-mcp.md) | 明确的数据外发隐私提示。 |
| XA-1 | [XeroAPI/Xero-OpenAPI](reviews/09-api-specs-standards/XeroAPI__Xero-OpenAPI.md) | 幂等键请求头 + 批量写入的两种错误汇总模式。 |
| XA-2 | [XeroAPI/Xero-OpenAPI](reviews/09-api-specs-standards/XeroAPI__Xero-OpenAPI.md) | 增量同步：`If-Modified-Since` 与按连续分录号 `offset` 拉取。 |
| XA-3 | [XeroAPI/Xero-OpenAPI](reviews/09-api-specs-standards/XeroAPI__Xero-OpenAPI.md) | 单据与系统派生总账分录分离；总账分录只读、连续编号、带来源。 |
| XA-4 | [XeroAPI/Xero-OpenAPI](reviews/09-api-specs-standards/XeroAPI__Xero-OpenAPI.md) | 每个实体统一的 History 与 Attachments 子资源。 |
| XA-5 | [XeroAPI/Xero-OpenAPI](reviews/09-api-specs-standards/XeroAPI__Xero-OpenAPI.md) | 收付实现制 / 权责发生制双视图。 |
| XA-6 | [XeroAPI/Xero-OpenAPI](reviews/09-api-specs-standards/XeroAPI__Xero-OpenAPI.md) | Webhook 签名 + 订阅验证握手。 |
| AD-1 | [apideck-libraries/openapi-specs](reviews/09-api-specs-standards/apideck-libraries__openapi-specs.md) | 科目 `classification` + `type` + `sub_type` 三层分类，`header` 标记分组科目。 |
| AD-2 | [apideck-libraries/openapi-specs](reviews/09-api-specs-standards/apideck-libraries__openapi-specs.md) | 分录行 `base_currency_amount` 与原币金额并存；行级维度（部门、地点、往来方、跟踪类别）。 |
| AD-3 | [apideck-libraries/openapi-specs](reviews/09-api-specs-standards/apideck-libraries__openapi-specs.md) | 游标分页 + meta / links 结构 + 稀疏字段 `fields`。 |
| AD-4 | [apideck-libraries/openapi-specs](reviews/09-api-specs-standards/apideck-libraries__openapi-specs.md) | `row_version` 乐观并发；`meta.warnings` 非致命警告。 |
| AD-5 | [apideck-libraries/openapi-specs](reviews/09-api-specs-standards/apideck-libraries__openapi-specs.md) | 附件以 `{reference_type}/{reference_id}` 多态挂载到任意实体。 |
| AD-6 | [apideck-libraries/openapi-specs](reviews/09-api-specs-standards/apideck-libraries__openapi-specs.md) | 字段重要度权重：设计数据模型时区分核心字段与边缘字段。 |
| CN-1 | [r3f/china-chart-of-accounts](reviews/09-api-specs-standards/r3f__china-chart-of-accounts.md) | 国标一级科目编码 + 名称作为“标准科目”参考，便于与中国会计报表对齐。 |
| CN-2 | [r3f/china-chart-of-accounts](reviews/09-api-specs-standards/r3f__china-chart-of-accounts.md) | 科目“类型”（功能角色）与“根类型”（报表分类）分离；关键角色科目必须存在。 |
