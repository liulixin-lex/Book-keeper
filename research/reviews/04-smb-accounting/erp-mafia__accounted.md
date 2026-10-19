# erp-mafia/accounted

- 分类：04 中小企业会计（瑞典法规，“为 Agent 构建”）
- 语言 / 许可证 / 最近提交：TypeScript（Next.js 16 + Supabase/Postgres）/ AGPL-3.0 / 2026-10-18
- 审查范围：`README.md`、`src/lib/reconciliation/bank-reconciliation.ts`、`src/extensions/general/mcp-server/{README.md,server.ts,tool-suggest.ts,tool-namespace.ts,recommended-tools.ts,unattended.ts,origin-guard.ts,tasks.ts,resources/}`、`docs/decisions/`

## 定位

符合瑞典会计法的复式记账系统：凭证不可变、连续凭证号、期间锁定、7 年留存；整个记账引擎以 150+ 个 MCP 工具对 AI 开放（API Key 或 OAuth 2.1），由 AI 完成分类、核对、凭证、增值税、年结。

## 数据模型（相关部分）

- BAS 科目表；凭证 draft → commit；连续凭证号；期间锁；文档归档带 SHA-256 完整性校验与留存期强制；
- 银行流水与总账行的核对关系（含 N:1：一笔流水对应多条总账行）；核对方法 `auto_exact / auto_reference / auto_date_range / auto_fuzzy / manual` 与置信度；低于阈值的候选保存为“建议”（`potential_journal_entry_id + method + confidence`）供复核。

## 对账算法：四轮匹配

1. 金额精确 + 日期相同 → 0.95；
2. 金额精确 + 参考号（OCR/付款参考）匹配且 ±90 天内 → 0.90（**绝不只凭描述匹配**，避免每月同额同描述的重复费用跨期误配）；
3. 金额精确 + 日期 ±3 天 → 0.85；
4. 金额 ±0.01 + 日期相同 → 0.75；
- 先检查借贷方向一致；币种不同不比较；取置信度最高者；支持 dry-run、阈值、仅报告不应用。

## MCP 设计（重点）

**工具编写契约（由测试强制）**：
1. 每个 inputSchema `additionalProperties: false`，幻觉字段直接拒绝；
2. 工具描述 ≤ 280 字符，使用 Agent 式提示（“先调用 X”“高风险”），参数说明放 JSON Schema；
3. 写工具返回统一的“暂存操作信封”（staged、risk_level、actor、message、preview、period_status、next）；
4. 涉及日期的写工具都带期间状态检查；
5. **每个工具必须在 scope 映射表中声明所需权限，缺失默认拒绝**；
6. 工具定义是静态字面量（无时间戳/随机数），保证 `tools/list` 稳定、可被客户端缓存；`tools/list` 有体积上限测试。

**其他机制**：
- Resources：`company/current`、`period/active`、`recent-activity`、`capabilities`、`attention`（需要处理的事项）、`chart-of-accounts` 等只读上下文；
- `get_agent_briefing`：返回按工作流推荐的工具组合（让支持批量加载的客户端一次加载所需工具）；`search_tools`、`list_skills`/`load_skill`（领域知识按需加载）；
- **未知工具“你是不是要找”**：按猜测名称中的词对工具目录排序返回（基于生产遥测的改进）；
- MCP Tasks：长耗时调用的持久句柄；
- Origin 头校验（防 DNS 重绑定）；连接级公司绑定（`?company=` 后拒绝访问其他公司）；
- **无人值守模式**：定时任务标记为 unattended 后只能读与暂存、不能提交，服务端强制（失败即关闭）；
- 暂存参数中的敏感个人信息守卫。

## 可借鉴

- [AC1] 四轮确定性匹配 + 方法/置信度记录 + 低置信度存为建议。
- [AC2] “参考号匹配必须带时间窗，绝不只凭描述”。
- [AC3] MCP 工具契约：严格 schema、短描述、统一写结果信封、scope 默认拒绝、静态定义、体积上限。
- [AC4] Agent briefing / 推荐工具组合 / 工具搜索 / “你是不是要找”。
- [AC5] 只读 Resources 提供上下文（当前期间、待办、科目表、能力）。
- [AC6] 无人值守模式服务端降权；连接级范围绑定。
- [AC7] 归档文件 SHA-256 完整性。

## 不采用 / 风险

- 暂存后需人工批准（approval）的流程 —— 用户要求去掉审批；新系统用“dry-run 预览 + 同参数提交 + 批次可整体冲正”代替。
- AGPL；瑞典税务与薪资功能无关。

## 对新系统的启示

1. 对账引擎内置“确定性多轮规则”（精确→参考号→时间窗→容差），再叠加“打分模型”（Midday）处理模糊场景；
2. MCP：严格 schema、统一结果信封（含 `next`）、scope 映射默认拒绝、静态定义、未知工具建议、briefing 资源、只读模式与 Token 级写权限；
3. 所有日期相关写入返回期间状态（开放/锁定）。
