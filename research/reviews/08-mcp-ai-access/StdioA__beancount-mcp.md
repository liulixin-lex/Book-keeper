# StdioA/beancount-mcp

- 分类：08 MCP（Beancount 查询 + 提交交易）
- 语言 / 许可证 / 最近提交：Python (FastMCP, watchdog) / MIT / 2025-05
- 审查范围：`beancount_mcp/{server,entry_editor}.py`、README

## 定位

Beancount MCP：BQL 查询、按 ID 获取交易、列出账户，以及**提交新交易 / 替换已有交易**；监听账本文件变化自动重载；支持 stdio 与 SSE。

## 设计要点

- 交易 ID = 条目内容哈希（hash_entry）；
- `submit_transaction`：把模型给出的 Beancount 文本**直接追加**到账本文件，然后重载；
- `replace_transaction`：按哈希找到条目，用新文本替换原文（entry_editor 定位源码行）；
- 文件监听（watchdog）保持内存账本与文件同步。

## 风险（反面教材）

- 写入前**不做校验**：追加后才重载，若文本有语法错误或不平衡，账本会进入错误状态；
- 替换 = 直接修改历史，无冲正、无审计、无幂等；
- 内容哈希作为 ID，任何修改都会改变 ID。

## 可借鉴

- [SB-1] 交易 ID 稳定可引用（但应是持久主键，不是内容哈希）。
- [SB-2] 外部修改（文件/数据库）后自动刷新缓存。

## 对新系统的启示

- 反例提醒：AI 写入必须先校验（借贷平衡、科目存在、期间开放、去重）再落库；修改必须走冲正 + 重记并留痕；ID 使用持久主键（ULID）。
