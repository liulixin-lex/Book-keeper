# 01 调研综合：优秀功能、逻辑与算法汇总

> **2026-10-19**：草稿、过账、复核、两段式预览、期间结账与锁账、期末重估、对账与核销等已去掉，本文相关内容仅作设计记录；现状见 [17 精简账本](17-lean-ledger.md)。

> 输入：`research/INDEX.md`（81 个项目、9 个类别）与 `research/reviews/**`（逐个审查）。
> 每条结论后的 `[ID]` 指向 `research/IDEAS.md` 中的可借鉴要点，可追溯到具体项目与代码位置。
> 本文只做“横向比较 + 取舍”，具体设计见 03–10 号文档。

## 0. 调研范围

| 类别 | 数量 | 代表项目 | 主要贡献 |
|---|---|---|---|
| 01 纯文本复式记账 | 8 | ledger、hledger、beancount、fava、tackler | 余额断言、显式换算、校验分级、导入规则 DSL、报表指纹 |
| 02 账本引擎 / 核心库 | 10 | formance、tigerbeetle、midaz、blnk、pgledger、sequence | 整数金额、posting 模型、幂等、双时间、两阶段、手续费模型、哈希链 |
| 03 会计库 / 框架 | 6 | django-hordak、django-ledger、pyluca、python-accounting | 延迟平衡约束、交易账户法换汇、科目角色、规则重放 |
| 04 中小企业记账 | 9 | akaunting、bigcapital、erpsaas、LedgerSMB、accounted、midday | 银行规则、未分类科目、对账会话、检查点、匹配打分、MCP 契约 |
| 05 ERP 会计模块 | 8 | odoo、erpnext、idempiere、tryton、ofbiz、dolibarr、gooderp | 核销、锁账与例外、多币种三层金额、重过账、凭证模板、辅助核算 |
| 06 个人 / 家庭财务 | 15 | firefly-iii、actual、gnucash、sure、kresus、ezbookkeeping | 规则引擎、导入匹配、字段来源锁、去重负面规则、国内账单 |
| 07 导入、分类与对账 | 11 | beangulp、double-entry-generator、hyperswitch-recon、OpenRec、monopoly | 解析器→中间表示→生成器、预期-确认对账、未匹配池、合计校验 |
| 08 MCP / 外部 AI 接入 | 11 | mcp-odoo、hledger-mcp、norman、xero-mcp、stripe/ai | 只读默认、预览-提交、工具注解、作用域、调用日志、领域化工具 |
| 09 API 规范与标准 | 3 | Xero OpenAPI、Apideck、中国科目表 | 幂等头、增量同步、批量错误模式、统一字段、国标科目 |

审查方式：浅克隆或稀疏检出后只读阅读源码（不执行任何仓库脚本）；不确定的结论回到代码核实（monopoly、ofxstatement、smart_importer 三份已按代码更正）。

---

## 1. 金额与精度

| 做法 | 代表 | 评价 |
|---|---|---|
| 整数最小单位 + 币种精度 | formance [F1]、tigerbeetle [T9]、hyperswitch [HS-5]、erpsaas [ES4]、dubbl [DB1] | 无舍入漂移，数据库可直接求和；**采纳** |
| 有理数 / 定点小数库 | gnucash [GC6]、frappe books [FB6] | 精确，但数据库层聚合不便 |
| 浮点 | 多个个人记账 App | 反面教材；rotki 在代码规范层禁止浮点 [RT1] |

**采纳**：金额一律 `BIGINT` 最小单位，精度由商品（币种）定义；汇率用 `NUMERIC(28,12)`；运算在应用层用 `Decimal`，落库前按商品精度舍入；API 同时返回整数与展示字符串，并声明以整数为准 [LF3]。

## 2. 多币种与汇率

| 做法 | 代表 | 要点 |
|---|---|---|
| 原币 + 本位币双金额，本位币冻结 | odoo [OD1]、crater [CR1]、gnucash value/amount [GC1] | 报表不随汇率变化 |
| 三层金额（本位币 / 科目币种 / 交易币种） | erpnext [EN1] | 全面，但复杂 |
| 每币种单独平衡，跨币种必须显式换算 | tigerbeetle [T2]、hledger [HL2]、beancount [BC7] | 杜绝不同币种直接相加 |
| 交易账户法（Trading account） | hordak [HK2] | 每笔交易各币种自平衡，汇兑损益可由交易账户推出 |
| 期末重估生成汇兑损益凭证 | erpnext [EN8]、knut [KN1][KN2]、gooderp [GE6] | 不改写原分录 |
| 原币平衡与本位币舍入差分别处理 | idempiere [ID3] | 原币差额进暂挂，舍入差进币种平衡科目 |
| 派生商品 / 固定倍率 | ghostfolio [GF1]、ledger 商品等价 [LD3] | 内部换算约定显式化，不伪装成市场汇率 |
| 汇率来源与获取日志、间接换算 | crater [CR2]、ghostfolio [GF2]、knut [KN3] | 每个汇率可追溯 |
| 手续费 / 点差单独成行 | tigerbeetle [T3] | 事后可还原真实汇率 |

**采纳**：
1. 分录行存 `amount`（原币）+ `base_amount`（本位币，过账时冻结）+ `fx_rate`/`fx_rate_id`；
2. **每笔分录同时满足：各商品 Σamount = 0 且 Σbase_amount = 0**；跨商品交易由引擎自动生成“货币兑换（交易账户）”腿 [HK2][T2]；
3. 汇率表记录来源、类型、获取时间；缺失汇率不静默回退，按“同日 → 向前最多 N 天 → 经基准币种间接换算”的显式策略并在结果中标注 [GF2]；
4. 非法币商品（如“上游额度”）用商品表 + 价格规则表达固定换算约定 [GF1][LD3]；
5. 期末重估为可选的独立凭证 [EN8]。

## 3. 账本结构

| 做法 | 代表 | 评价 |
|---|---|---|
| 业务单据层与会计分录层分离，分录只由过账函数生成 | ekwo [EK1]、pyluca [PY1]、idempiere [ID2]、Xero [XA-3]、erpnext | 规则修正后可重过账；**采纳** |
| Posting 模型（每条腿自平衡）+ 边界账户 | formance [F2] | 模型简洁 |
| 交易组 → 日记账 → 两行分录 | firefly [FF2] | 两行限制表达力，不采纳 |
| 累计借贷 volumes | formance [F3]、tigerbeetle [T1] | 发生额免扫表；**采纳**（余额表） |
| 分录行内嵌“过账后余额”与版本 | sequence [SQ1]、midaz [M3]、pgledger [PG2]、envato [DE3] | 审计友好、O(1) 余额；**采纳**（按记录顺序） |
| 延迟约束触发器在提交时校验平衡 | hordak [HK1]、ekwo [EK2] | 数据库层兜底；**采纳** |
| 两阶段（pending → post/void） | tigerbeetle [T4]、blnk [B5] | 在途状态；用“草稿 + 未清项”表达 |

**采纳**：`transactions`（业务层：类型、模板参数、证据、状态）→ 过账引擎 → `journal_entries` / `journal_lines`（会计层：不可变、连续编号、哈希链）。已过账分录不可修改，只能冲正或追加调整。

## 4. 科目体系

| 要点 | 代表 |
|---|---|
| 科目角色（role）决定报表归属，而非靠名称或编码 | django-ledger [DL1]、bigcapital [BG1]、ofbiz 科目类型间接层 [OF1]、Apideck classification/type [AD-1] |
| 汇总科目不可记账、可设“禁止手工凭证” | fineract [FN1]、gnucash [GC5]、gooderp [GE4] |
| 科目性质决定正常余额方向，备抵科目反转 | plutus [PL1]、erpsaas [ES2]、tigerbeetle [T1] |
| 方向约束：禁止借 / 禁止贷 + 提示；余额不得为负 / 正 | gooderp [GE2]、pgledger [PG1]、tigerbeetle [T10] |
| 允许商品列表、开户/销户日期 | beancount [BC2]、hordak [HK3] |
| 维度必填 / 禁止规则挂在科目上 | erpnext [EN6]、gooderp [GE3] |
| 业务事件 → 科目映射表，不硬编码 | fineract [FN2]、midaz [M1]、ofbiz [OF1] |
| 国标编码参照 | 中国科目表 [CN-1][CN-2]、ofbiz XBRL [OF6] |

**采纳**：科目字段包括编码、层级、是否分组、分类（资产/负债/权益/收入/费用）、正常方向、**角色**、允许商品、开户/销户日期、余额约束、是否允许手工凭证、必填维度、国标代码、现金流活动、是否系统科目。模板只引用“角色”或参数，科目表可替换。默认科目表采用《小企业会计准则》编码。

## 5. 维度、往来与未清项

| 要点 | 代表 |
|---|---|
| 通用维度（部门、项目、渠道…）挂在分录行 | django-ledger [DL6]、LedgerSMB [LS4]、midaz [M4]、Apideck [AD-2] |
| 百分比分摊到多个维度值 | odoo [OD7]、idempiere [ID6] |
| 辅助账：主科目下按往来方明细 | dolibarr [DO1]、envato 账户作用域 [DE2] |
| 交易对手即账户 | firefly [FF1]（个人理财适用，不采纳为主模型） |
| 往来未清台账与总账分离 | erpnext [EN3] |
| 行级部分核销 + 未核销余额 + 汇兑差异凭证 | odoo [OD2][OD3]、ekwo [EK5]、python-accounting [PA4] |

**采纳**：分录行带 `counterparty_id` 与维度值（关联表，外键完整）；“未清项科目”（平台应收、预付兑换码、应付）上的行维护 `open_amount`，通过 `line_matches` 部分核销；分摊在模板中展开为多行，不用 JSON 分配。

## 6. 模板、过账规则与手续费

| 要点 | 代表 |
|---|---|
| 凭证模板 = 关键字 + 表达式行 | tryton [TR2]、fineract [FN4] |
| 可版本化的交易脚本 / 模板 | formance Numscript [F10]、ekwo 规则包 [EK8] |
| 手续费：固定 / 比例 / 取大者 + 基数 + 优先级 + 内扣 / 外加 | midaz [M2] |
| 拆分：百分比 / 固定 / 剩余 + 尾差 | blnk [B1]、actual [AT2] |
| 自动交易：按谓词追加分录（如按比例计手续费） | ledger [LD1]、hledger [HL6] |
| 单据类型 → 允许科目类型；转账类型白名单 | python-accounting [PA1]、envato [DE1] |
| 安全表达式 + Decimal + 按币种舍入 | tryton [TR4] |
| 尾差容差 + 自动尾差科目，超限报错 | erpnext [EN7]、frappe books [FB4] |

**采纳**：交易类型 → 版本化过账模板（输入 schema、计算字段、分录行定义、校验条件）；手续费规则独立成表（按渠道/往来方/类型、生效区间、方法、基数、内扣/外加、舍入、优先级、入账角色）；表达式使用白名单 AST 求值器；拆分用最大余数法分配尾差。

## 7. 更正与追溯

| 要点 | 代表 |
|---|---|
| 冲正生成反向交易，原交易只打标记，可选原日期 | formance [F5]、medici [MD5]、fineract [FN5] |
| 只追加更正 + 原因代码 + 关联 ID | tigerbeetle [T6] |
| 冲正翻转借贷而非写负数 | ekwo [EK4] |
| **规则变更后重放 + 差额调整** | pyluca [PY2] |
| 重过账（配置修正后重新生成分录），保存前后对比 | erpnext [EN9]、idempiere [ID7] |
| 生效时间与入账时间分离 + 任意时点查询 | formance [F4]、pgledger [PG3]、ledger [LD2] |
| `recorded_at` 不可回填 | midaz [M3] |
| 系统生成的凭证只能从源单据撤销 | gooderp [GE5] |

**采纳**：三种更正路径：冲正（reverse）、更正（reverse + 重新录入，互相引用）、重过账（规则/模板版本变化后，对受影响交易重新计算，生成差额调整或冲正重记，提交前给出差异报告）。双时间：`effective_date`（业务日）与 `recorded_at`（系统时间，服务器生成）；报表支持 `as_known_at`。

## 8. 期间与锁账

| 要点 | 代表 |
|---|---|
| 期间三态 open / closed / locked（锁定不可逆） | tryton [TR1]、python-accounting [PA2] |
| 多类锁账日期 + 硬锁 + 临时例外（用户、期限、原因） | odoo [OD4] |
| 按模块锁账 + 部分解锁区间 | bigcapital [BG5] |
| 按单据类型关闭期间 | erpnext [EN4]、idempiere [ID5] |
| 结账日只能向前推进 | fineract [FN3] |
| 余额检查点 = 结账日 + 各科目余额快照 | LedgerSMB [LS1]、django-ledger [DL4] |
| 锁定期内自动顺延日期 | odoo [OD5]（会掩盖错误，**不采纳**为默认） |

**采纳**：软锁日期（可由带原因的临时例外越过）+ 硬锁日期（数据库触发器强制、不可回退）；月度期间 open → closed → locked；关闭时生成余额检查点；关闭前跑结账检查清单。

## 9. 编号、哈希链与审计

| 要点 | 代表 |
|---|---|
| 草稿不占号，过账时按日记账/年度原子分配连续号；断号检测 | ekwo [EK3]、odoo [OD8][OD9]、python-accounting [PA7] |
| 凭证字 + 期间内连续号 + 附件张数 | gooderp [GE1] |
| 哈希链（含前一行哈希） | python-accounting [PA3]、odoo [OD8]、sequence [SQ2][SQ3] |
| 审计日志 JSON 差异 + IP + UA | dubbl [DB4] |
| 记录写入渠道（界面/API/导入/AI） | akaunting [AK1]、stripe [ST-6]、BeeCount-Cloud [BCC1] |
| 报表数据集指纹 | tackler [TK1][TK3]、rotki [RT4] |
| 字段级来源 + 人工修改锁定 | sure [SR1] |
| 归档文件 SHA-256 | accounted [AC7] |

**采纳**：凭证号 `{凭证字}-{YYYY}{MM}-{序号}`，过账分配；分录哈希链（按账套），每日校验；审计事件也形成哈希链；所有写入记录渠道、令牌、MCP 客户端、请求 ID、变更集；字段来源与锁定；报表输出数据集指纹。

## 10. 导入管道

| 要点 | 代表 |
|---|---|
| 解析器 → 中间表示 → 生成器，三段式插件化 | double-entry-generator [DEG1]、beangulp [BG-1]、hyperswitch [HS-4] |
| 标准化对账单：期初 + 明细 = 期末 硬校验 | ofxstatement [OS-1][OS-2] |
| 解析合计必须能在原文中找到，失败拒绝 | monopoly [MP-1] |
| 无源 ID 时稳定 ID = 内容哈希 + 同日序号 | ofxstatement [OS-3]、rustledger [RL2] |
| 外部 ID = 来源账户 + 来源交易号 | ledger-autosync [LA-1]、beancount-import [BI-4] |
| 增量水位线 + dry-run | hledger [HL5] |
| 原始文件归档并与分录互引 | beangulp [BG-2]、hledger [HL4] |
| 列角色 + 值映射 + 可保存导入配置 | firefly data-importer [DI-2]、paisa [PS4] |
| 逐行错误与警告报告 | data-importer [DI-4]、Beancount-Trans [BT2] |
| 国内账单（支付宝/微信/京东）字段语义 | ezbookkeeping [EZ1]、double-entry-generator [DEG2] |
| 跨多次上传的重叠去重 | Beancount-Trans [BT4] |
| 退款沿用原单科目、与原交易配对 | Beancount-Trans [BT3]、double-entry-generator [DEG5] |

**采纳**：上传文件（归档、哈希）→ 识别来源与解析器 → 解析为标准化来源记录（IR）→ 安全校验（合计、期初期末、期间覆盖）→ 去重 → 规则分类 → 匹配 → 预览 → 提交（生成草稿或直接过账）。来源记录永久保留并与交易互引。

## 11. 规则引擎

| 要点 | 代表 |
|---|---|
| 规则组 + strict / 非 strict + stop_processing + 丰富操作符 + 动作表达式 + 对历史执行 | firefly [FF4] |
| 搜索语法与规则条件同源 | firefly [FF5]、QuickBooks MCP 查询参数 [QB-1] |
| 分阶段（pre / normal / post）+ 按特异性排序 | actual [AT1] |
| 金额约等、区间条件；拆分动作 | actual [AT2] |
| 描述正则命名分组提取往来方/单号 | tryton [TR3]、OpenRec [OR-3] |
| 时段、金额区间、多关键字、忽略；后者覆盖前者 | double-entry-generator [DEG3] |
| 金额区间 + 优先级 | erpnext [EN11]、odoo [OD6] |
| 规则预览（dry-run 看命中样例）+ 命中统计 | norman [NM-2]、blnk [B2] |
| 两级：按类型默认 + 单条覆盖 | rotki [RT3] |
| 从人工修改生成规则建议 | actual [AT4]、midday [MY4] |

**采纳**：规则 = 阶段 + 优先级（同优先级按特异性）+ 条件 AST（与查询 DSL 同源）+ 动作列表 + stop_processing；动作不得覆盖锁定字段；规则可试运行、可对历史执行（生成变更集，可撤销）；记录每次命中。

## 12. 匹配与对账

| 要点 | 代表 |
|---|---|
| 外部唯一号精确 → 金额+日期窗口模糊 → 合并不覆盖人工字段，已核对受保护 | actual [AT3] |
| 四轮确定性匹配 + 方法 / 置信度记录 | accounted [AC1]；“参考号匹配必须带时间窗” [AC2] |
| 召回 + 精排两阶段，分项分数显式、可解释，建议 / 自动两级阈值 | midday [MY1][MY2][MY5] |
| 非对称日期窗口 | midday [MY3] |
| 从确认 / 拒绝中学习 | midday [MY4]、kmymoney [KM2] |
| 重复检测负面规则 + “不是重复”持久化 | kresus [KR1][KR2] |
| 权威来源约束：同一权威来源的两条不能互相合并；多来源合并为一笔 | beancount-import [BI-1][BI-2] |
| 预期-确认模型、规则 1:1 / 1:N / N:1 / N:N 策略 | hyperswitch [HS-1][HS-3]、blnk [B3] |
| 未匹配池跨批次持续参与 | OpenRec [OR-1] |
| 按键分组 + 约束（净额为零、容差） | OpenRec [OR-2] |
| 余额断言 + 容差；从对账单生成断言 | beancount [BC1]、hledger [HL4][HL7]、ledger-autosync [LA-2] |
| 对账会话：期末余额 + 勾选 + 差额为零才完成，报告留档 | akaunting [AK2]、LedgerSMB [LS3]、kmymoney [KM4] |
| 分录级对账状态（未清 / 已清 / 已对账） | gnucash [GC2]、LedgerSMB [LS2] |
| 暂挂科目：外部流水先入暂挂，核对 = 把暂挂余额转走 | OCA [OCA1][OCA3] |
| 余额锚点 / 外部报告余额作为核对点 | sure [SR2] |

**采纳的算法组合**：
1. 去重：`external_id` → 稳定指纹 → 模糊候选（负面规则 + 忽略对表过滤）；
2. 记录 ↔ 交易：确定性多轮（引用号+时间窗 / 金额+账户+对手+时间窗）→ 打分精排（金额、日期、名称、引用、币种分项）→ 双阈值（自动 / 建议），保存分项分数；
3. 记录 ↔ 记录（多来源互证，如订单列表 ↔ 兑换日志 ↔ 钱包账单）：按键分组（往来方 + 面值），**一维最小代价指派**（按时间排序后动态规划，允许跳过并计罚分），全局最优而非逐条贪心；
4. 余额断言与对账会话；
5. 暂挂科目 + 统一待办队列。

## 13. 待处理、复核与来源

| 要点 | 代表 |
|---|---|
| 未分类收入 / 费用科目 + reviewed 标记 | erpsaas [ES1] |
| 不平衡落入 Imbalance 科目，绝不静默丢弃 | gnucash [GC4] |
| 未匹配 → FIXME 科目 | double-entry-generator [DEG4] |
| 统一审核队列（跨来源） | Beancount-Trans [BT5] |
| “待跟进”“疑似重复”状态 | moneymanagerex [MX1] |
| 核验状态作为月结前置；缺票据清单 | norman [NM-7] |
| 已确认 / 未确认 与 计入 / 不计入统计 两个开关 | moneynote [MN2] |

**采纳**：`review_status`（unreviewed / reviewed）独立于过账状态；暂挂科目余额即未处理金额；统一待办（未处理来源记录、待定匹配、草稿、暂挂余额、失败断言、检查失败、缺凭证）。

## 14. 报表与查询

| 要点 | 代表 |
|---|---|
| 报表只有一个实现，API / MCP / 前端都调用它 | ekwo [EK6] |
| 角色驱动报表分类 | django-ledger [DL1]、hledger [HL8] |
| 活动类型推断 → 现金流量表 | django-ledger [DL2] |
| 多种估值口径（成本 / 期末 / 指定日）× 目标币种 | hledger [HL3]、fava [FV5]、beancount [BC7] |
| 收付实现制 / 权责发生制双视图 | Xero [XA-5] |
| 余额快照 = 最近快照 + 增量；每日余额物化 | medici [MD3]、sure [SR4]、fineract [FN6] |
| 报表附数据集指纹与计算设置快照 | tackler [TK1]、rotki [RT4] |
| 计算器可插拔 | ghostfolio [GF3]、knut [KN4] |
| 受限查询 + schema 资源 | beanquery-mcp [BQ-1]、Beancount-Trans [BT7] |

**采纳**：报表服务单一实现；每日余额物化 + 回溯写入时自某日起失效重算；报表参数含估值口径、目标币种、维度分组、`as_known_at`；输出指纹；对外提供受限聚合查询（白名单维度与度量）而非任意 SQL。

## 15. 健康检查与校验

| 要点 | 代表 |
|---|---|
| 分级校验（默认 / 严格 / 可选），可单独运行 | hledger [HL1] |
| 插件式不变量检查 | beancount [BC8] |
| 账务体检：方向异常、资产为负、缺汇率 | paisa [PS1] |
| 账本健康监控 + 二分定位差异区间 | erpnext [EN10] |
| 定期重算余额对比缓存，结果入库 | envato [DE4] |
| 只读完整性重放 | ledgerforge [LF6] |
| 试算平衡为零 | plutus [PL3] |
| 缺失购入记录作为报告中的显式问题 | rotki [RT2] |

**采纳**：内置约 20 项检查（见 07 号文档），可单独或整体运行，结果入库，结账前强制；提供“二分定位差异”工具。

## 16. API 设计

| 要点 | 代表 |
|---|---|
| `Idempotency-Key` + 输入哈希冲突检测，覆盖所有写操作 | formance [F6]、Xero [XA-1]、tigerbeetle [T7] |
| 批量写入：全成功或逐条报告 | Xero summarizeErrors [XA-1]、tigerbeetle [T5] |
| 增量同步：`updated_since` 与连续分录号 offset | Xero [XA-2] |
| 游标分页 + meta / links + 稀疏字段 | Apideck [AD-3] |
| 行版本乐观并发、非致命警告 | Apideck [AD-4]、fava [FV2]、hledger-mcp [HM-2] |
| 统一 History 与 Attachments 子资源 | Xero [XA-4]、Apideck [AD-5] |
| 每个接口声明权限 scope；审计失败写入 | formance [F9] |
| 带类型前缀的 ID | pgledger [PG4] |
| Webhook：触发 × 内容 × 投递记录与重试，签名 | firefly [FF8]、Xero [XA-6] |
| `on_duplicate=error` | firefly [FF6] |
| 编号化错误码 | midaz [M5]、ekwo [EK7] |
| 导入器作为独立客户端，主系统只暴露稳定写 API | data-importer [DI-1] |

## 17. MCP / 外部 AI 接入

| 要点 | 代表 |
|---|---|
| 默认只读；写能力需显式开启并按令牌 scope 鉴权 | ledgerforge [LF1]、mcp-odoo [MO-2]、hledger-mcp [HM-4]、actual-mcp [AB-3] |
| 任务型工具 + Resources + Prompts，而非 REST 1:1 映射 | ledgerforge [LF2]、norman [NM-1]、accounted [AC3] |
| 预览 → 校验 → 用令牌执行，令牌 = 规范化请求哈希，TTL | mcp-odoo [MO-1] |
| 写入流水线：副本 → 全量校验 → dry-run / 原子提交；修改须携带期望当前内容 | hledger-mcp [HM-1][HM-2][HM-3] |
| dry-run 与过账后余额反馈；名称解析 | ezbookkeeping [EZ3]、actual-mcp [AB-5] |
| 歧义返回候选而不是猜 | BeeCount-Cloud [BCC2] |
| 统一响应信封（ok / code / result / warnings / next_action）；严格拒绝未知参数 | rustledger [RL3][RL4]、accounted [AC3] |
| 工具注解（read-only / destructive / idempotent） | mcp-odoo [MO-3]、norman |
| 命名错误 + 下一步提示；不可重试错误明确说明 | ekwo [EK7]、norman [NM-3] |
| 服务端 instructions、上下文资源（期间、科目表、待办、能力） | ekwo [EK7]、accounted [AC5]、norman [NM-4] |
| 以用户身份执行、拒绝超级密钥；OAuth 远程接入；令牌只存哈希 | ekwo [EK7]、dubbl [DB5]、mcp-odoo [MO-7] |
| AI 写入自动加来源标记，可筛选、可批量撤回；MCP 调用日志 | BeeCount-Cloud [BCC1][BCC4]、ledgerforge [LF4] |
| MCP 与 REST 共用服务层；漂移检测测试 | dubbl [DB6]、BeeCount-Cloud [BCC3]、rustledger [RL4]、firefly-mcp [FM-1] |
| 工具预设控制暴露范围；连接级上下文绑定 | firefly-mcp [FM-2]、norman [NM-6]、stripe [ST-2]、accounted [AC6] |
| 字段级脱敏 + `redacted_fields`；按工具限流；写入不重试 | mcp-odoo [MO-4][MO-6] |
| 资源模板 `scheme://{type}/{id}`；默认精简返回 | erpnext-mcp [EM-1][EM-2] |
| 工作流剧本（月结、对账、补票据） | norman [NM-5]、ezbookkeeping [EZ7] |
| 写入默认草稿，返回深链接 | xero-mcp [XR-3] |
| 数据外发隐私提示 | beanquery-mcp [BQ-2] |
| Agent 任务基准与评分 | stripe [ST-5] |

## 18. 反面教材（明确不做）

| 反模式 | 出处 | 新系统做法 |
|---|---|---|
| 浮点金额 | 若干个人记账 App | 整数最小单位 |
| 直接修改 / 删除已过账历史 | beancount-mcp replace、erpnext-mcp delete | 冲正 + 重记，变更留痕 |
| 写入前不校验，写坏后才发现 | beancount-mcp submit | 先全量校验与 dry-run，再单事务提交 |
| 内容哈希作为交易 ID | beancount-mcp | 持久 ULID 主键 |
| MCP 暴露通用“执行任意方法 / 删除” | erpnext-mcp call_method | 只暴露领域工具，删除仅限草稿 |
| 锁账期内静默顺延日期 | odoo 可选行为 | 默认拒绝并提示 |
| 取消-修订生成 “-1/-2” 编号 | erpnext | 冲正 + 新交易互指 |
| 按描述做参考号匹配不带时间窗 | 多个导入器 | 参考号必须配合时间窗 [AC2] |
| 导入覆盖人工确认字段 | 多个同步器 | 字段锁 [SR1] |
| 余额“硬重置”修改账目 | sure 计算器 | 只生成差异与待办，调整须显式分录 |

## 19. 结论：新系统的设计原则

1. **正确性优先**：整数金额、双重平衡（各商品 + 本位币）、数据库层不变量、只追加。
2. **业务录入与会计事实分离**：用户 / AI 录入业务事实，系统按版本化模板与手续费规则生成标准分录；规则修正可重过账。
3. **一切可追溯**：来源文件 → 来源记录 → 交易 → 分录 → 报表，双向可查；双时间；哈希链；字段来源。
4. **导入即入账，异常进暂挂与待办**：不阻塞流水，但未处理事项可见、可量化。
5. **对账是一等公民**：去重、匹配、余额断言、对账会话、未清项核销、结账检查清单。
6. **对外接口与内部同源**：REST 与 MCP 共用服务层与校验；MCP 默认只读、作用域最小、预览后提交、全程留痕、可撤回。
7. **不内置 AI、审批、订阅**：系统内只有确定性规则与基于历史频次的推荐；智能能力由外部 AI 经 MCP 接入；没有审批流（预览 → 确认提交只是写入安全步骤）。
