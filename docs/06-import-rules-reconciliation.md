# 06 导入、规则与匹配

## 0. 当前实现（2026-10-19，精简后）

| 环节 | 实现 |
|---|---|
| 来源 | `import_sources`：kind = `wechat_bill`、`alipay_bill`、`stripe_balance`、`card_shop_orders`、`upstream_usage_log`、`generic_tabular`、`records`、`redeem_page`（中转站兑换码页面的打印 PDF）、`ai_extract`（截图 / PDF 由 Claude 读取）；config：`defaults`（按方向 in / out / neutral 给出 type、channel、category、counterparty 等输入，或 `ignore`）、`unclassified_policy`（leave / suspense）、`match`（日期窗口、容差、是否自动接受）、`credit_rate`（额度 → 本位币，默认 1）、表格列映射（`columns` / `wide`）、`shop`、`counterparty` |
| 输入方式 | 上传文件（CSV / XLSX / JSON / PDF / 截图，原件存入 files 并关联批次；`redeem_page` 与 `ai_extract` 一次可传多个文件，合成一个批次），或直接提交结构化 `records`（外部 AI 从截图 / PDF 读出的流水、订单、兑换记录，走同一管道）。设置新来源时可先用样例文件试读（`import-sources:preview`），边改列映射边看读出的记录，不保存任何东西 |
| 解析器 | 微信（状态过滤，“已全额退款”与其退款行默认忽略）、支付宝、Stripe（UTC → 账套日期，payout 为内部划转）、通用表格（长表：列角色、方向值映射、状态包含 / 排除、正则提取、面值提取、敏感列脱敏；宽表：一行一天、一列一渠道、可带手续费列）、卡网订单（默认列名识别，表头取前 40 行里认得的列最多的一行，表头前的标题、汇总行自动跳过；面值提取 `100R` / `余额+50` / `20刀` / `$20`、已退款订单跳过）、上游兑换记录、兑换码页面 PDF（§0.1）、结构化记录（拒绝浮点金额与未知字段） |
| 标准化 | 金额精度超出商品精度为行错误；业务日期 = 账套时区自然日；指纹含同文件重复序号；兑换码只存 SHA-256 与末 4 位 |
| 安全校验 | `totals_match`（警告）、`balance_continuity`（错误）、`row_errors`（错误，可 `accept_row_errors` 跳过）、`period_gap`（警告）、`all_duplicates`（提示）；未来日期与未知商品记为行错误 |
| 去重 | 同来源外部 ID 或指纹 → `duplicate`；已撤销批次的记录释放身份，可重新导入 |
| 分类 | 来源默认值 → 规则三阶段（normalize / classify / enrich，优先级小者先、具体度低者先，越具体越晚执行越优先）→ 金额自动填入该类型输入（销售 gross / fee，额度采购 face / total / credit_quantity，支出 amount / fee…）；人工设置的字段锁定，规则不覆盖；`missing` 列出缺失字段 |
| 规则动作 | `set_transaction_type`、`set_counterparty`、`set_input`、`unset_input`、`set_channel`、`set_category`、`set_fee`、`set_description`、`ignore`、`add_tag`；值支持模板 `{amount}`、`{captures.face}`、`{extracted.channel}`；试运行不写入；`apply` 只重分类未入账记录（已入账的直接修改对应交易） |
| 匹配 | 记录 ↔ 交易：先找“已经记过”的（§0.2：同类型、同往来方、同一天，单条相等或当天几条之和等于已记的合计），再走外部单号 / 订单号 / 金额 + 往来方 + 日期三个确定性轮次与加权打分；≥ 0.92 且领先 ≥ 0.08 自动接受，≥ 0.60 待确认；**有待确认建议的记录不会入账**（防重复）；拒绝写入排除表，已自动关联的也能拒绝（同时删掉凭证关联） |
| 配对 | 记录 ↔ 记录（如卡网订单 ↔ 上游兑换）：按 `left_keys` / `right_keys` 分组，DP 求窗口内总时间差最小的非交叉配对（全局最优，有性质测试对照穷举）；时间差 ≤ `auto_accept_max_gap_minutes` 自动接受；配对优先于交易匹配；右侧若已按估算入账，提交时删除估算交易并改为订单交易的证据 |
| 完成 / 撤销 | 完成导入时已分类的记录直接入账（逐条保存点，失败记录写 `error` 并汇总，可先 `dry_run`）；交易 `external_ref = 来源代码:外部 ID`；生成的交易写 `transaction_sources`（primary / evidence），交易详情显示来源证据；撤销批次 = 删除其入账的交易、解除关联、释放外部单号；`undo_change_set` 对导入执行同样的撤销 |
| 待处理 | 待补全的导入记录、待确认匹配、未完成的导入 |
| 手续费依据 | 记录（识别结果）与交易详情都标出手续费的来历：按实际填写、按哪条手续费规则（名称、代码@版本、费率），或“无手续费规则（按 0）”；规则按记录日期当天生效的版本选，与入账时同一套选择 |

余额断言、对账会话与往来核销已于 2026-10-19 去掉（17 号文档）。

分类的叠加顺序：来源默认值 → 往来方默认值（默认交易类型须与资金方向相符：支出方向只用采购 / 支出 / 销售退款，收入方向只用销售 / 采购退款；默认渠道补在未给渠道时）→ 分类规则 → 人工锁定字段。

动作 `add_tag`（M6）：给生成的交易加标签，值可用模板（如 `广告-{weekday}`），多条规则的标签累加。Beancount 导出见 07 号文档 §7。

未实现（按需）：拆分动作、指定手续费规则动作、规则建议、匹配阈值自动校准。N:1 子集求和已用于“当天合计”（§0.2）。

## 0.1 兑换码页面与 AI 识别（2026-10-19）

**兑换码页面 `redeem_page`**：中转站“兑换码 / 余额充值”页面用浏览器打印成的 PDF，用 pypdf 读文字层，不调用任何外部服务。

- 每条 `余额充值（…）` 读出时间、额度与兑换码；兑换码只存前缀（外部 ID = `站点:时间:额度:码前缀`），同一页打印两次、两份 PDF 有重叠都只记一次。
- 站点取页脚的网址（优先含 `redeem` 的那条，其次页码旁的），读不到才用文件名。页面网址与来源配置的 `counterparty` 都按原样精确使用；只有从文件名推断时，若推断出的主机名对不上已知站点、而恰好只有一个已知站点的主机名以它开头（文件名被截断，如 `relay-b.exa（2）.pdf` → `relay-b.example`），才用那个站点，有多个候选或一个也没有时按原样。外部单号与往来方都用解析后的站点，所以与带网址的同站 PDF 照常去重。没有文字层的 PDF（如“Microsoft: Print To PDF”打印成图片的页面）这里读不了，要走 AI 识别；AI 读到的页面没写站点、行上也没有往来方时，同样按文件名兜底，但只认已知站点（原样或唯一补全），认不出就留空。记录写 `extracted.site`、`credits`、`unit`、`entry_kind`、`code_prefix`。
- 商品默认 `UCR`（额度），按来源的 `credit_rate` 折合本位币。
- 没有文字层的 PDF（扫描件、图片另存）报错并建议改用 AI 识别；不是 PDF 的文件直接拒绝。

**AI 识别 `ai_extract`**：截图（PNG / JPEG / WebP / GIF）和 PDF 由 设置 → AI 模型 给“识别”分配的模型（默认 `BK_AI_*`）读成结构化记录，之后与其他导入完全一样：去重、规则分类、匹配已有交易、补全、完成导入。页面类型、按类型抽取、确定性检查、规则后的 AI 分类建议与低把握待确认见 19 号 §4（2026-10-19 起）。

| 方面 | 做法 |
|---|---|
| 开关 | 给“识别”分配了提供商，或服务器配置了 `BK_AI_API_KEY`（或 `ANTHROPIC_API_KEY`）才可用；`GET /books/{id}/ai/status` 告诉前端，未配置时“截图（AI）”来源不可选、上传返回 503 `AI_UNAVAILABLE` |
| 后台执行 | 上传只存文件、建批次（状态 `extracting` 识别中）并排一个 `imports.ai_extract` 任务，立即返回；worker 在事务外调用 Claude（每个文件一次请求、最多 4 个并行、单次请求超时 240 秒），读完写入记录、批次转 `parsed`；失败转 `failed`（识别失败），错误写在批次摘要上。前端每 3 秒轮询，识别中可离开页面。**10 分钟没有结果**（通常是 worker 没在运行）时，读取批次时把它标为识别失败“识别超时”，前端随之停止轮询，用“再读一次”重试；每次读取（首次与每次重试）有自己的编号，旧任务不会再读一次，超时后才读完的结果仍会写入 |
| 重试与去重 | 同一次选择的文件重传沿用同一个幂等键；同一来源、同一组文件（内容哈希相同）直接返回已有批次（200），不再调用 AI；识别失败的批次可 `:retry`（同样的文件再读一次）或撤销 |
| 只转写 | 按页面类型区分的 JSON schema 输出，遵照账套的识别规则手册；看不清的行写入 `unreadable` 并在批次上提示，不猜；页面没写年份按上传日期推断；多个文件之间重叠的行（时间、方向、金额、订单号、说明都相同）只留一条 |
| 合计核对 | 页面上的“共 N 条 / 合计 ¥X”（AI 原样抄下）与读出的条数、金额比对，对不上在批次上显示警告（`checks` 里的 `ai_totals`），**只警告，不阻止完成导入** |
| 成本 | `BK_AI_EFFORT` 默认 `medium`；截图按原分辨率发送，只有长边超过 2576 px（模型的上限）才缩到 2576 px——缩小会让数字变糊，读错一个金额的代价远大于识别费用（整批截图原分辨率约 1 美元）；单张仍超过约 3.5 MB 的转成同尺寸 JPEG；`BK_AI_MAX_FILES` 每次最多文件数（默认 12）；`BK_AI_DAILY_FILES` 每个账套每天最多文件数（默认 200，0 = 不限），超出返回 429 `RATE_LIMITED` |
| 隐私 | 文件从**服务器**发给所分配的提供商（不经浏览器直连）；上传卡片上有说明。不上传含完整卡密、密码的截图 |
| MCP | 外部 AI 自己读截图，用 `import_records` 直接提交 `records`；`ai_extract` 来源的文件只走上传接口 |

## 0.2 对上已经记过的交易（2026-10-19）

账本里有些交易是先手工记的（例如某站当天的额度采购记成一笔合计），之后再导入该站的明细。导入时先判断每条记录是否已经记过，避免重复入账；对不上的不打扰。

1. **拟入账交易**：记录分类后的交易类型、主金额（销售 gross、额度采购 face、支出 amount…）、往来方或渠道。额度记录（UCR）先比额度数：账上交易记了 `credit_quantity` 时按“额度数 = credit_quantity”比对（¥100 可能换到 $103，面值对不上），没记时仍按面值；按日合计与子集求和同样适用。导入入账时额度记录会写入 `credit_quantity`，以后重复导入能直接对上。
   - 记录写了往来方文字、却解析不到已知往来方 → 不可能是账上某笔交易，**直接按新记录处理**；
   - 只按渠道比对，仅限完全没写往来方的记录（如每日收入表的一列）；
   - 往来方和渠道都没有 → 留给后面的打分匹配。
2. **剩余额度**：账上同类型、同一方、同一天的交易，主金额减去**同一来源**已关联记录的金额，就是还能被这个来源解释的部分。一份 PDF 关联了当天合计的一部分，下一份 PDF 还能接着关联剩下的。
3. **第一轮（精确）**：同一天、同一方的记录在剩余额度内做子集求和（最多 20 条；优先解释更多条），恰好相等就**自动关联**为该交易的凭证。单条相等记 `same_day`，多条合计记 `daily_total`；超过 20 条只试“全部之和”或“单条相等”。
4. **第二轮（不确定）**：仍对不上、但当天或次日有同一方且还有剩余额度的交易 → 生成一条待确认建议 `same_day_party`。有待确认建议的记录不会入账。
5. **整组确认**：待确认按“可能是哪一笔交易”分组，每组只问一次——“是同一笔（N 条）”或“不是，单独入账”（`POST /import-batches/{id}:decide-matches`，可带 `record_ids` 只答一组）。不是的记录写入排除表并回到可入账。
6. **改判已自动关联的**：在“已对上”里点“不是这笔”，记录回到可入账，排除表记下这对，**同时删掉交易上的凭证关联**（`transaction_sources`）。

同一笔交易的配对说明（记录 ↔ 记录配对已解释的交易）不参与这里的判断。分类变化（补全、重分类、应用规则）后对该记录重新判断。

**手续费规则不写死**：各渠道、各站点的费率与忽略名单都是会变的数据，只放在“设置 → 手续费规则 / 分类规则”里（REST `/fee-rules`、`/rules`，MCP `manage_fee_rule`、`manage_rule`），代码与迁移里不写任何站点费率或忽略名单。手续费规则按往来方或渠道、带生效日期，导入与入账都用记录日期当天生效的那条；改了规则后用 `POST /transactions:repost`（MCP `repost_transactions`）重算，只有变化的交易冲销重记。

**真实文件复测**（临时库，跑完已删；具体条数不写入文档）：每日收入表全部按当天自动关联；兑换码 PDF 绝大部分按当天合计或单笔相等自动关联，其余进待确认并按交易分组，每组问一次；赠送额度不同比例的站点（如 ¥100 换 $103）在交易没记额度数时进待确认，只指向本站的交易；订单汇总表全部按外部单号去重、表头自动识别；没有任何记录关联到别的站点的交易。

## 1. 导入管道

```
上传文件 ──▶ files（SHA-256 归档，同内容只存一份）
   │
   ├─ 1 识别：按来源指定解析器；未指定时各解析器 sniff() 打分，取最高且 ≥ 0.8
   ├─ 2 解析：Parser.parse() → ParsedRecord[] + FileSummary + RowError[]（纯函数，无数据库访问）
   ├─ 3 标准化：时区换算、业务日期、金额转最小单位、外部 ID / 指纹、敏感字段脱敏
   ├─ 4 安全校验：合计、余额连续、期间覆盖、行错误、时间合理性
   ├─ 5 去重：external_id → 指纹 → 模糊候选（负面规则过滤）
   ├─ 6 规则：normalize → classify → enrich 三阶段
   ├─ 7 匹配：记录 ↔ 交易、记录 ↔ 记录
   ├─ 8 确认：逐行识别结果与统计（import_batches.status = parsed，尚未入账）
   └─ 9 完成：关联已有交易 / 入账 / 留在待办；更新水位线；一个变更集
```

大文件（> 2000 行）解析与提交转后台任务；识别结果分页返回。

## 2. 来源与解析器

### 2.1 解析器接口

```python
class Parser(Protocol):
    code: str          # 如 "wechat_bill"
    version: str       # 语义化版本；解析逻辑变化必须升版本
    def sniff(self, meta: FileMeta, head: bytes) -> float: ...
    def parse(self, data: BinaryIO, config: Mapping, tz: ZoneInfo) -> ParseResult: ...

@dataclass(frozen=True)
class ParsedRecord:
    row_no: int
    external_id: str | None
    occurred_at: datetime            # 带时区
    direction: Literal["in", "out", "neutral"]
    amount: Decimal                  # 正数，主单位
    commodity: str
    fee_amount: Decimal | None
    balance_after: Decimal | None
    counterparty_text: str | None
    description: str | None
    order_no: str | None
    reference: str | None
    status_text: str | None
    extracted: Mapping[str, Any]     # 面值、站点、账号标识、商品名…
    raw: Mapping[str, Any]

@dataclass(frozen=True)
class FileSummary:
    period_from: date | None; period_to: date | None
    declared_totals: Mapping[str, Decimal]    # 如 {"in_count": 12, "in_amount": 1234.56, …}
    opening_balance: Decimal | None; closing_balance: Decimal | None
    account_identifier: str | None
```

每个解析器必须附带样例文件与期望输出（`tests/importers/fixtures/<parser>/`），回归测试逐字段比对。

### 2.2 内置解析器

| 代码 | 来源 | 外部 ID | 关键语义 |
|---|---|---|---|
| `wechat_bill` | 微信支付账单（CSV / XLSX） | 交易单号 | 收/支（“/”为不计收支 → neutral）；当前状态过滤（支付成功、已存入零钱、已转账、对方已收钱为有效；已全额退款 / 对方已退还 → 退款，按商户单号关联原交易）；表头汇总笔数与金额用于合计校验 |
| `alipay_bill` | 支付宝账单 | 交易订单号 | 收/支 / 不计收支；交易状态（交易成功、退款成功、交易关闭）；交易对方、对方账号、商品说明 |
| `stripe_balance` | Stripe 余额流水导出 | balance transaction id | type（charge / refund / payout / adjustment / stripe_fee）；amount、fee、net 分列；UTC 时间；币种；payout 生成结汇 / 资金划转候选 |
| `card_shop_orders` | 卡网店铺订单列表（按店铺配置列映射） | `{店铺代码}:{订单号}` | 商品名 → 面值（配置正则，如 `(?P<face>\d+)R`、`余额\+(?P<face>\d+)`）与站点（商品 → 往来方映射）；单价、数量、总价；下单 / 支付时间；兑换码只存 SHA-256 与末 4 位 |
| `upstream_usage_log` | 上游站点兑换 / 充值记录（按站点预设） | 站点给出的记录号，否则指纹 | 时间、额度、账号标识、兑换码摘要、余额（如有） |
| `generic_tabular` | 任意 CSV / XLSX / JSON | 配置的列或指纹 | 列角色映射（日期、时间、金额、收入 / 支出分列、方向、币种、对方、描述、订单号、外部 ID、手续费、余额）、值映射、日期格式、小数分隔、跳过行、符号约定；配置保存在来源上 |

### 2.3 敏感数据
- 兑换码、卡密、完整账号：只存 SHA-256 摘要与末 4 位（`extracted.code_sha256`、`extracted.code_last4`）；
- 原始行 `raw` 写入前同样脱敏；原始文件作为附件保存（访问需 `files:read`），MCP 默认不返回原始文件内容。

## 3. 标准化与稳定 ID

- `occurred_at`：按来源时区解析，存 UTC 与原始偏移；`effective_date` = 转到账套时区后的日期；
- 金额：`Decimal` → 最小单位整数；小数位超过商品精度 → 行错误（不静默舍入）；
- `external_id`：来源唯一号，规范化（去空白、统一大小写）后加来源前缀；
- `fingerprint`（无外部 ID 时）：

```
fingerprint = SHA-256( source_id | occurred_at(UTC, 秒) | direction | amount_minor | commodity
                       | norm(counterparty_text) | norm(description) | norm(order_no) | "#" + k )
```
`norm` = 去空白、全角转半角、小写；`k` 为同一文件中前面各字段完全相同的行的出现序号（从 1 开始）。同一文件重复导入得到相同指纹 → 去重；同一秒内完全相同的两行仍能各自保留。

## 4. 安全校验（阻止提交的条件）

| 检查 | 规则 | 失败级别 |
|---|---|---|
| `totals_match` | 文件声明的笔数 / 金额合计 = 解析结果合计（按方向） | error |
| `balance_continuity` | 有余额列时：每行 上一余额 ± 金额 = 本行余额；期初 + Σ = 期末 | error |
| `row_errors` | 存在解析错误行 | error（可选择排除错误行后提交，排除行记入报告） |
| `future_dates` | 发生时间晚于当前时间 + 1 天 | error |
| `commodity_known` | 商品代码已定义 | error |
| `period_gap` | 与同来源上次水位线之间存在未覆盖的日期 | warning |
| `all_duplicates` | 全部为重复 | info（无新内容） |
| `parser_low_confidence` | sniff 得分 < 0.95 | warning |

## 5. 去重

1. **精确**：同来源 `external_id` 已存在 → `duplicate`（指向已有记录）；
2. **指纹**：同来源指纹已存在 → `duplicate`；
3. **模糊候选**（同来源、不同 ID，例如同一账单两种导出格式）：金额相同、时间差 ≤ 120 秒、对方文本相似度 ≥ 0.8 → 生成 `duplicate` 类建议，不自动判定。负面规则（满足任一即**不是重复**）：
   - 两条来自同一批次；
   - 其中一条已被人工分类为不同交易类型或往来方；
   - 两条的外部 ID 都存在且不同、且来源声明外部 ID 可靠；
   - 该对已在 `match_exclusions`（用户判定“不是重复”，持久化，不再提示）。
4. **跨来源的同一笔业务不是重复**（如微信付款与卡网订单），走 §7 的记录 ↔ 记录匹配，作为互证证据合并到同一交易。

## 6. 规则引擎

### 6.1 条件 AST（与查询 DSL 同源）

```jsonc
{ "all": [
    { "field": "source_kind", "op": "eq", "value": "card_shop_orders" },
    { "field": "description", "op": "regex", "value": "(?P<face>\\d+)R\\s*兑换码" },
    { "any": [
        { "field": "amount", "op": "between", "value": ["10.00", "500.00"] },
        { "not": { "field": "counterparty_text", "op": "contains", "value": "测试" } }
    ] }
] }
```

| 操作符 | 说明 | 具体度 |
|---|---|---|
| `eq` / `ne` | 相等 / 不等 | 10 |
| `in` / `not_in` | 属于集合 | 9 |
| `approx` | 金额约等：`{"value": "50.00", "tolerance": "0.5", "mode": "abs" | "pct"}` | 5 |
| `between` / `date_between` / `time_between` | 区间（含端点）；`time_between` 为一天内时段（账套时区） | 5 |
| `gt` / `gte` / `lt` / `lte` | 比较 | 1 |
| `weekday_in` | 星期 | 1 |
| `contains` / `not_contains` / `starts_with` / `ends_with` | 文本（规范化后） | 0 |
| `regex` | 正则；命名分组写入 `captures`，供动作引用 | 0 |
| `is_null` / `not_null` | 空值 | 1 |
| `has_tag` | 标签 | 5 |
| `alias_of` | 对方文本命中某往来方的别名 | 9 |

可用字段：来源记录 —— `source`、`source_kind`、`direction`、`amount`、`commodity`、`fee_amount`、`occurred_at`、`effective_date`、`time_of_day`、`weekday`、`counterparty_text`、`counterparty`、`description`、`order_no`、`reference`、`status_text`、`extracted.<key>`、`batch`；交易 —— `type`、`status`、`effective_date`、`counterparty`、`dimension.<type>`、`account`、`amount.<role>`、`review_status`、`is_estimate`、`tag`、`created_channel`、`external_ref`、`order_no`、`text`、`metadata.<key>`。

**文本语法**（API `q` 参数与规则编辑共用，编译为同一 AST）：`type:sale channel:链动 amount:>100 amount:50..100 date:2026-10 -status:discarded "关键词" (counterparty:relay-b.example OR counterparty:relay-c.example)`。

### 6.2 动作

| 动作 | 参数 | 说明 |
|---|---|---|
| `set_counterparty` | id 或 `from_alias` | |
| `set_transaction_type` | code | |
| `set_input` | name, expr | 设置模板输入，表达式可引用 `captures`、记录字段，如 `money(captures.face, 'CNY')` |
| `set_dimension` | type, value | |
| `set_counterparty_account` | id 或 `from_extracted: key` | |
| `set_fee_rule` | code | 强制使用指定手续费规则 |
| `add_tag` | name | |
| `set_description` | expr | |
| `split` | parts[{percent | fixed | remainder, overrides}] | 一条记录拆成多笔交易（尾差按 05 号 §6） |
| `ignore` | reason（如 `gift`、`internal_noise`） | 记录 → `ignored` |
| `request_pairing` | pairing_rule | 指定参与某个记录 ↔ 记录配对规则 |

### 6.3 执行语义

- 阶段顺序：`normalize`（清洗文本、解析往来方、提取字段）→ `classify`（交易类型、科目参数、维度）→ `enrich`（标签、描述）。
- 阶段内执行顺序：`priority` 从小到大；同 priority 按具体度（条件具体度之和）从低到高。后执行的动作覆盖先执行的同一字段——即“越具体、优先级越高的规则越晚执行、最终生效”。`stop_processing` 结束当前阶段。
- **字段锁**：`provenance[field].locked = true`（人工修改过）的字段，规则动作跳过并记录 `skipped_locked`。
- 每次命中写 `rule_runs`（规则版本、目标、字段变化），更新 `hit_count`、`last_hit_at`；字段来源记为 `rule:<rule_id>@<version>`。
- **试运行**：`POST /rules/{id}/test` 或 MCP `test_rule` 对指定范围（来源、日期区间、最多 N 条）计算命中与字段变化，不写入。
- **对历史执行**：`POST /rules:apply`：只重新分类尚未入账的来源记录（已入账的直接修改对应交易），整体一个变更集，可撤销。
- **规则建议**（P2）：当用户对同一往来方文本连续 3 次做出相同人工修正时，生成待确认的规则，不自动启用。

## 7. 匹配

### 7.1 记录 ↔ 交易（把导入的流水对应到已录入的交易）

**召回**：同账套；方向一致；商品一致；金额窗口 `|Δ| ≤ max(tol_abs, tol_pct × amount)`；日期窗口 `[d − back, d + fwd]`（按来源类型配置，非对称，如钱包账单 −3/+3 天，支付处理商提现 −7/+7 天）；排除：已与同一权威来源的另一条记录关联的交易、`match_exclusions` 中的对、已删除的交易。

**确定性轮次**（命中即停）：

| 轮次 | 条件 | 分数 | method |
|---|---|---|---|
| 1 | 交易 `external_ref` = 记录外部 ID | 1.00 | `external_id` |
| 2 | 订单号 / 引用号相等 **且** 在日期窗口内 | 0.98 | `reference_window` |
| 3 | 金额完全相等 + 资金科目相同 + 往来方相同 + 日期差 ≤ 1 天 | 0.95 | `amount_window` |

**打分轮**（前三轮未命中）：

```
score = 0.45·S_amount + 0.25·S_date + 0.20·S_name + 0.10·S_ref
S_amount = 1                       (完全相等)
         = max(0, 1 − |Δ| / tol)    (否则)
S_date   = exp(−|Δdays| / 2)
S_name   = 1（已解析往来方一致）否则 trigram 相似度(对方文本, 往来方名称及别名)
S_ref    = 1（引用号部分包含）否则 0
```

**决策**：最佳分 ≥ 0.92 且领先第二名 ≥ 0.08 且来源允许自动 → `auto_accepted`；≥ 0.60 → `pending` 建议；否则不建议，记录留在**未匹配池**，之后每次导入或新交易创建时重新参与匹配。

所有建议保存 `components`（分项分数、窗口、候选数），便于解释；接受后写 `transaction_sources`，记录 → `matched`；拒绝写入 `match_exclusions`。合并时以人工字段为准，导入只补充空字段与证据，已对账（reconciled）的分录行不受影响。

### 7.2 记录 ↔ 记录（多来源互证，如采购订单 ↔ 兑换日志 ↔ 钱包账单）

由**配对规则**定义（存于 `pairing_rules` 表）：

```jsonc
{
  "code": "orders_vs_redemptions",
  "left":  { "source_kinds": ["card_shop_orders"], "time_field": "extracted.paid_at" },
  "right": { "source_kinds": ["upstream_usage_log"], "time_field": "occurred_at" },
  "group_by": ["counterparty", "extracted.face_value", "commodity"],
  "window_minutes": { "before": 10, "after": 4320 },   // 右侧相对左侧：允许 −10 分钟到 +3 天
  "unmatched_penalty_minutes": 4320,
  "expand_quantity": "extracted.quantity",            // 一单多码：按数量展开为多个单位
  "auto_accept_max_gap_minutes": 30,
  "on_accept": "link_same_transaction"                 // 或 "create_transaction"
}
```

**算法**（每个分组独立）：

1. 左右两侧各按时间排序（一单多码先按数量展开）；
2. 代价：`cost(i, j) = |t_j − t_i|`（分钟），超出窗口为 ∞；未匹配罚分 P；
3. 动态规划求最小总代价的**非交叉**匹配：

```
f[0][0] = 0
f[i][j] = min( f[i−1][j−1] + cost(i, j),   // 配对
               f[i−1][j]   + P,            // 左 i 不配对
               f[i][j−1]   + P )           // 右 j 不配对
```
   时间复杂度 O(n·m)；对“一维上的绝对差代价”，存在非交叉的最优匹配，因此结果是全局最优，优于逐条就近的贪心匹配；
4. 回溯得到配对；`gap ≤ auto_accept_max_gap_minutes` 且该分组内无并列解时自动接受，其余作为建议；
5. 接受后：两条记录挂到同一交易（`transaction_sources`：订单为 `primary`，兑换为 `evidence`），或按模板由配对创建交易（面值取订单商品、实付取订单金额、日期按账套口径取付款或兑换时间）；
6. 超过窗口仍未配对的记录：按往来方的兜底手续费规则（`is_fallback`）生成估算交易，标记 `is_estimate`，进入待办。

N:1（多笔付款对应一单）在同一窗口内用 ≤ 6 条候选的子集求和穷举，总额相等即建议。

### 7.3 匹配质量

- 指标：自动接受后被撤销的比例、建议接受率、平均分差，按来源与配对规则统计（`GET /matching/metrics`）；
- 阈值与权重在来源配置中可调；P2 提供基于历史决策的有界自动校准（每次调整 ≤ 0.02，阈值范围 [0.85, 0.98]）。

## 8. 完成与撤销

| 记录状态（识别后） | 完成导入时 |
|---|---|
| `duplicate` / `ignored` | 不生成交易 |
| `matched`（已有交易） | 写 `transaction_sources`，补充交易空字段与证据 |
| 已分类且输入完整 | 直接入账 |
| 未分类 | 按来源 `unclassified_policy`：`leave`（默认，留在待办）或 `suspense`（资金账户 ↔ 1999 待核对款项 入账，之后把这笔交易改成正确的类型） |

完成后更新来源水位线；`import_batches.status = committed`。

**撤销批次**：同一变更集内——删除该批次入账的交易（冲销，账本保留历史）；解除匹配链接；记录状态置 `ignored`（原因 `batch_reverted`），记录本身保留以备审计，并释放外部单号以便重新导入。

## 9. 对账（已去掉）

余额断言、对账会话、往来核销与账龄已于 2026-10-19 去掉（17 号文档）。资金是否对得上，看概览中各币种余额与平台余额是否一致；不一致时用 `query_ledger` 按日汇总定位。

## 10. 待核对款项与待办

**待核对款项**（1999）：未分类流水、无法确定去向的款项进入此科目；其余额 = 未处理金额，应尽快归类清零。

**统一待办**（`GET /work-items`，MCP `list_pending_work`）：

| 类型 | 来源 | 处理方式 |
|---|---|---|
| `unprocessed_records` | 已完成批次中未入账的来源记录（缺少入账所需字段，或等待匹配决定） | 补全分类即入账（有 `ledger:write` 时；否则保持已分类），或忽略 |
| `pending_matches` | 待确认的匹配建议 | 接受 / 拒绝 |
| `uncommitted_batches` | 尚未完成的导入批次 | 确认后完成导入 |
| `estimated` | `is_estimate = true` 的交易 | 填入实际手续费，或修正规则后按新规则重算 |
| `suspense` | 待核对款项余额 ≠ 0 | 找到这些款项，改成正确的交易类型 |
| `failed_checks` | 最近一次健康检查的失败项 | 按检查说明处理 |

每项包含：类型、对象 ID、摘要、金额、日期、建议工具与参数。
