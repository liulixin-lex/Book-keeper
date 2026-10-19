# iiAtlas/hledger-mcp

- 分类：08 MCP（hledger 全功能读写）
- 语言 / 许可证 / 最近提交：TypeScript (Node, MCP SDK, zod) / MIT / 2025（npm `@iiatlas/hledger-mcp`，有 .mcpb 安装包）
- 审查范围：`src/{index,base-tool,executor,journal-writer}.ts`、`src/tools/{add,remove-entry,replace-entry,find-entry,import,close,rewrite}.ts`、README

## 定位

把 hledger CLI 的几乎所有命令（accounts / balance / register / print / bs / is / cf / stats / payees / tags…）包装为 MCP 工具，另外提供**安全写入**：新增、查找、删除、替换、导入、结账、批量改写；启动参数 `--read-only`、`--skip-backup`。

## 写入安全设计（本类最好的实现）

1. **工作副本**：复制账本到 `<file>.tmp-<uuid>`，所有修改先作用于副本；
2. **校验**：对副本执行 `hledger check`（语法、平衡、断言），失败则丢弃副本并报错；
3. **dryRun**：所有写工具都有 `dryRun`，只校验并返回结果，不落盘；只读模式下仍允许 dryRun；
4. **备份 + 原子替换**：落盘前把原文件复制为 `.bak-<时间戳>`，再 `rename` 副本覆盖原文件（原子）；
5. **乐观并发**：删除/替换要求同时提供 **原条目全文 + 文件位置（file、startLine、endLine）**，与当前内容规范化比较一致才执行——防止 AI 基于过期数据修改；
6. `find_entry`：用 hledger 查询语法定位完整交易，返回文件与行号，供后续删除/替换使用（先查后改）；
7. 只读模式：写工具直接拒绝；Web UI 只读模式下以 view 权限启动。
8. 所有包含文件也注册为 MCP Resource，客户端可以浏览原始账本。

## 可借鉴

- [HM-1] **写入流水线：工作副本 → 全量校验 → dryRun 返回 / 备份 + 原子提交**。
- [HM-2] **修改/删除必须携带“期望的当前内容”**（乐观并发前置条件，相当于 If-Match/ETag）。
- [HM-3] 先查后改：find 返回稳定定位信息，修改工具只接受该定位信息。
- [HM-4] 服务器级只读开关 + 每个写工具的 dryRun；只读下允许 dryRun。
- [HM-5] 报表工具齐全（资产负债、损益、现金流、统计），参数与 CLI 一致。

## 不采用 / 风险

- 文件账本与行号定位不适用于数据库系统；删除历史条目在会计上不可取（应冲正）。

## 对新系统的启示

1. MCP/REST 写操作统一：`validate`（全量规则校验，含借贷平衡、科目、期间、去重）→ `dry_run` 返回将生成的分录与影响余额 → 提交（单事务）；
2. 修改类操作要求 `expected_version`（行版本号/ETag），不一致返回 `409 VERSION_CONFLICT` 并附当前版本；
3. 提供 `find_transactions` 返回 ID + version，修改工具只接受 ID + version；
4. 令牌级 `read_only`；写工具都支持 `dry_run`，只读令牌也可执行 dry_run（便于 AI 预演）。
