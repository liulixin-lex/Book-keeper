# rustledger/rustledger

- 分类：01 纯文本复式记账（Beancount 的 Rust 实现）
- 语言 / 许可证 / 最近提交：Rust / GPL-3.0 / 2026-10-18
- 审查范围：`README.md`、`crates/`（core/parser/booking/validate/query/importer/plugin/returns/budget/lsp/wasm）、`crates/rustledger-importer/src/lib.rs`、`crates/rustledger-ops/src/fingerprint.rs`、`src/bin/ag-rledger.rs`、`CHANGELOG.md`

## 定位

与 Beancount 完全兼容、快 10–30 倍的实现，额外提供 LSP、WASM、MCP、面向 Agent 的 CLI、银行导入、投资收益、预算、资本利得。

## 数据模型 / 记账逻辑

- 同 Beancount（指令、批次 booking、容差、BQL 100% 兼容）；31 个内置插件 + 通过 WASI 沙箱运行 Python 插件。
- 投资收益：资金加权 XIRR 与时间加权收益；资本利得按税批次计算。

## 导入、分类与对账（重点）

- CSV/OFX 自动识别格式（`csv_inference`）、去重、分类；
- **EnrichedImportResult**：每条导入结果附带“如何分类的（方法）、置信度、备选项、稳定指纹”——导入结果可解释；
- **结构指纹**：对日期、flag、payee、narration、tags/links（排序去重）、全部 posting 字段（作为多重集合，顺序无关）计算结构哈希，**排除元数据**，用于判重。

## API 与扩展（重点：面向 Agent）

- **`ag-rledger`**：与人类 CLI 一一对应，但每次调用只输出一个 JSON 信封：`ok`、类型化 `exit_code`、`result`、`warnings`、**`next_action`（HATEOAS 式下一步提示）**；
- **拒绝未知参数**（`UNKNOWN_FLAG`），避免 Agent 传了被静默忽略的参数还收到 ok；
- **漂移守卫测试**：自动比对人类 CLI 与 Agent CLI 的命令与参数，新增命令未接入 Agent 接口时测试失败；不支持的命令在根信封列出并以 `UNSUPPORTED` 拒绝；
- MCP 服务、LSP（编辑器实时校验）、WASM（浏览器端校验）。

## 可借鉴

- [RL1] 导入结果附带分类方法、置信度、备选、指纹 —— 自动分类可解释、可复核。
- [RL2] 结构指纹去重：顺序无关、排除元数据。
- [RL3] Agent 接口统一响应信封（ok / code / result / warnings / next_action）。
- [RL4] 严格拒绝未知参数；人类接口与 Agent 接口之间的漂移检测测试。
- [RL5] 插件沙箱（WASI）运行用户规则代码。

## 不采用 / 风险

- 仍是文本文件后端；GPL-3.0 只参考。

## 对新系统的启示

1. REST/MCP 响应统一信封：`{ok, data, warnings[], errors[{code,message,hint,field}], next_actions[]}`；
2. 请求体严格校验，未知字段直接 422（Pydantic `extra="forbid"`）；
3. 导入候选记录带 `categorization: {method, rule_id, confidence, alternatives}` 与 `fingerprint`；
4. 测试保证 REST 与 MCP 工具覆盖一致（契约漂移测试）。
