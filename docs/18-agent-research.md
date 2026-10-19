# 18 AI 助手与 MCP：借鉴了什么、为什么

> 2026-10-19 调研。资料来源都是各项目的官方文档：LangGraph（状态图、检查点、中断、流式）、LangChain（工具抽象）、OpenAI Agents SDK（guardrails、handoffs、human-in-the-loop）、Claude Agent SDK（权限、hooks、会话），以及 MCP 规范 2026-07-28 版（tools、annotations、prompts、resources）。实现见 19 号文档。

## 1. 结论：自研一个薄运行时，只借鉴概念

站内 AI 助手不引入 LangChain / LangGraph，原因有三：

1. **工具必须走现有的操作注册表**。记账、修改、导入等写入都要经过作用域校验、`dry_run`、幂等键与变更集（撤销），这一套已经同时服务 REST 与 MCP（`services/operations.py`、`mcp_api/server.py` 的 `Executor`）。框架自带的工具调用层会绕开这里，或者需要再包一层；直接复用 `Executor` 最短，也最不容易漏校验。
2. **依赖要少**。框架会带来一整组包与版本节奏；运行时本身只需要“调模型 → 执行工具 → 记一步 → 循环”，几百行就够。
3. **审计要完全可控**。每一步（模型回复、工具调用与结果、token、费用）都写进自己的表，和账本的变更集、审计链对得上；不依赖框架的检查点格式。

引入 LangChain / LangGraph 的条件是：写出明确理由，并确认兼容 Python 3.14。目前没有这样的理由，所以不引入。

## 2. 逐项借鉴

| 来源 | 概念 | 我们怎么用 | 为什么 |
|---|---|---|---|
| LangGraph | **检查点**（每个 super-step 存一份状态；`durability` 有 exit / async / sync 三档） | 每一步写入 `agent_steps` 后再执行下一步，相当于 `sync` 档；运行可从最后一步恢复 | 记账场景宁可慢一点，也不能丢步骤 |
| LangGraph | **中断 + 恢复**（`interrupt()` 暂停，`Command(resume=…)` 带回答继续；恢复时节点从头重跑，所以中断前的副作用要幂等） | `ask_user` 工具把运行置为“等待补充”，用户补完后从持久化的消息继续；每次工具调用带确定的幂等键（`agent:{run}:{step}`），重跑不会重复写入 | 同样的“重跑必须幂等”问题，用已有的幂等键解决 |
| LangGraph | **流式**（values / updates / custom 等模式） | 前端轮询运行与步骤列表；步骤即进度事件 | 自用场景步数少，轮询足够，省掉长连接 |
| LangChain | **工具 = 名称 + 描述 + 参数 schema（Pydantic）**；运行时参数（状态、上下文）对模型隐藏 | 工具定义沿用 MCP 工具的 Pydantic 模型；账套、身份、权限从 `RequestContext` 注入，不出现在参数里 | 同一份 schema 同时给 MCP 与站内 AI 助手 |
| LangChain | **每个工具调用都要有对应结果**（tool_call_id 对应） | 每个 `tool_use` 都写回一条结果（含错误），模型据此自行修正 | 模型能看到“为什么没成功” |
| OpenAI Agents SDK | **Guardrails**（输入、输出、工具三类；tripwire 触发即中止） | “阶段工具白名单”是工具级 guardrail：识别阶段只开放只读与暂存工具，越界调用直接拒绝并记一步；文件内容一律当数据 | 防提示注入，最有效的是“根本拿不到写工具” |
| OpenAI Agents SDK | **Handoffs = 一个特殊工具**；`max_turns` 超限即停 | 不做多 agent 交接；保留最大步数、单次预算与每日上限 | 自用场景一个助手足够；上限是成本与失控的护栏 |
| OpenAI Agents SDK | **RunState 可序列化，审批后恢复**；提示“序列化状态不带认证，存服务器端” | 运行状态只存在服务器数据库，恢复时重新按发起人权限校验 | 和我们的权限模型一致 |
| Claude Agent SDK | **权限按固定顺序判定**（hooks → deny → mode → allow → canUseTool）；最小权限用 `allowedTools` + `dontAsk` | 权限 = 发起人权限 ∩ 所选档位，再 ∩ 阶段白名单；不在白名单的工具不出现在模型的工具列表里（相当于 deny 规则直接移除工具） | 一个固定、可测试的判定顺序 |
| MCP 2026-07-28 | `tools/list` **可以按请求的授权变化**；返回顺序要确定 | 按令牌档位过滤工具，固定排序 | 规范明确允许，且利于缓存 |
| MCP | **annotations 只是提示**（readOnly / destructive / idempotent / openWorld），客户端不应信任 | 照常标注，但服务端自己校验权限，从不依赖客户端 | 安全不能放在提示上 |
| MCP | **两类错误**：协议错误与 `isError: true` 的执行错误；执行错误应给出可修正的说明 | 越权返回 403（执行错误，说明缺什么权限）；参数错误逐项说明 | 模型能据此自我修正 |
| MCP | **prompts 由用户选用、resources 由应用提供** | 场景 playbook 既是 MCP prompts，也是站内 AI 助手的起点（同一份数据）；规则快照与识别规则手册作为 resources | 一份来源，两处使用 |

## 3. 没有采用的

- **LangGraph 的图结构**：我们的流程是线性的“思考 → 工具 → 结果”循环，没有分支汇合，图带来的表达力用不上。
- **多 agent 交接（handoffs）**：场景都在一个账套、一个助手之内完成。
- **人工审批每个写操作**：项目原则是“写入立即生效，靠变更集撤销兜底”。AI 的一次运行共用一个变更集，界面上一键撤销本次全部写入，代替逐条审批。
