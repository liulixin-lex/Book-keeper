# vanto/beanquery-mcp

- 分类：08 MCP（Beancount 只读查询）
- 语言 / 许可证 / 最近提交：Python (FastMCP) / MIT / 2025-04（实验性）
- 审查范围：`server.py`、`server_test.py`、README

## 定位

最小化的只读 Beancount MCP：让 AI 用 BQL（类 SQL 查询语言）查询账本。

## 设计要点

- 工具：`set_ledger_file`（设置账本文件）、`run_query`（执行 BQL）；
- **Resources**：`beanquery://tables`（可查询的表及字段）、`beanquery://accounts`（账户列表）——先给模型 schema 与词表，再让它写查询；
- README 有**隐私警告**：账本数据会发送给模型提供方，建议脱敏或使用自托管模型。

## 可借鉴

- [BQ-1] 用 Resources 提供“查询 schema + 账户词表”，模型自行组合查询。
- [BQ-2] 明确的数据外发隐私提示。

## 不采用 / 风险

- 任意查询语言能力过强（对数据库不应开放任意 SQL）；单一工具缺少结构化输出。

## 对新系统的启示

- 提供受限的 `query_ledger`：只读、白名单字段/维度的聚合查询 DSL（类似报表参数化），并以 Resource 发布可用维度、科目表、交易类型；
- 在 MCP 接入文档与授权页提示数据外发风险，可配置字段脱敏。
