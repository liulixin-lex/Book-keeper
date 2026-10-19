# erpipe-org/mcp-odoo

- 分类：08 MCP（ERP 通用读写，安全写入设计最完整）
- 语言 / 许可证 / 最近提交：Python (FastMCP) / MPL-2.0 / 2026（活跃，带托管版）
- 审查范围：`src/odoo_mcp/{server_core,tools_write,write_policy,agent_tools,audit,auth,field_policy,rate_limit,tools_read,tools_accounting}.py`、`odoo_mcp_policy.json.example`、README、docs 目录

## 定位

用用户现有凭据把 Odoo 16+ 暴露为 MCP：读取/搜索/聚合、schema 目录、诊断、往来账龄、未核销汇总，以及门禁严格的写入。

## 安全写入流水线

1. **默认禁止写**：进程级开关 `ODOO_MCP_ENABLE_WRITES`，未开启时所有写入拒绝；直接的 create / write / unlink 不暴露为工具；
2. **preview_write**（只读）：规范化请求（模型、操作、值、记录 ID、上下文、实例）→ 生成 **确定性审批令牌 = sha256(规范化 JSON)**；
3. **validate_write**（只读）：用**服务器实时拉取的字段元数据**（fields_get）校验类型、必填、只读字段；只有基于可信实时元数据的校验才在服务器端登记令牌，**TTL 10 分钟**；
4. **execute_approved_write**（破坏性）：只能执行已登记、未过期、与原请求哈希一致的令牌；可选 **MCP elicitation** 弹出原生确认表单（含差异摘要）；
5. 令牌绑定实例，跨实例无效；**写入从不重试**（读取有指数退避重试）；
6. 业务动作方法（如确认订单）走**白名单策略文件**（可提交 git，每条带 reviewed_by / date / reason），策略文件损坏时按“全部禁止”处理；
7. 大文件上传：客户端只持有 `sha256:<hex>:<长度>` 指纹，真实内容只存服务器端，令牌对指纹做哈希。

## 其他设计

- **工具注解**：READ_ONLY（readOnlyHint, idempotentHint）/ PREVIEW / DESTRUCTIVE（destructiveHint）三类，客户端据此决定是否需要确认；
- **字段级 ACL**（读路径）：按模型做 deny 或 allow 列表，被拒字段从所有读取、资源和索引中移除，并返回 `redacted_fields` 提示；对被拒字段的聚合直接拒绝；
- **审计**：每个写路径事件（preview / validate / execute / chatter）写一行 JSONL，令牌只存 sha256 前 16 位；
- **限流**：按 实例:工具 的滑动窗口，warn / block 两种模式，在 health_check 中可见；
- **认证**：OAuth 令牌内省（RFC 7662）+ 受众校验（RFC 8707）+ 必需 scopes；默认拒绝非本地 HTTP 绑定；
- 智能字段选择（未指定字段时去掉审计/消息/二进制噪声字段）；schema 目录工具；5 个工作流 prompt；health_check 检测 N+1 读取。

## 可借鉴

- [MO-1] **preview → validate（服务端实时校验 + 登记令牌，TTL）→ execute（只接受令牌）** 三段式写入；令牌是规范化请求的哈希，执行时内容不可更改。
- [MO-2] 写入默认关闭；业务动作白名单可版本化并附审核信息；配置错误时一律禁止。
- [MO-3] MCP 工具注解（read-only / destructive / idempotent）。
- [MO-4] 字段级读取 ACL + `redacted_fields` 提示。
- [MO-5] 写路径审计 JSONL（只存令牌摘要）。
- [MO-6] 按工具限流；写入不自动重试，读取指数退避。
- [MO-7] OAuth 内省 + audience + scopes。

## 不采用 / 风险

- 令牌登记存于进程内存，重启即失效（我们应存数据库并带幂等键）；通用 ORM 透传对账本而言过宽，应提供领域工具。
- 注：这里的“审批令牌”是写入前的确认步骤，不是业务审批流；新系统不设审批模块，只保留“预览 → 确认提交”。

## 对新系统的启示

1. MCP 写工具统一两段式：`*_preview` 返回 `preview_id`（请求规范化哈希、生成的分录、影响余额、校验警告，TTL 15 分钟，存数据库）→ `commit_preview(preview_id, idempotency_key)`；
2. 令牌粒度：读 / 写草稿 / 过账 / 冲正 / 管理五级 scope，默认只读；
3. 敏感字段（凭据、密钥、卡号、联系方式）字段级脱敏，返回 `redacted_fields`；
4. 每次 MCP 调用都记录（client、tool、参数摘要、结果、耗时），写入额外关联审计事件；
5. 工具标注 MCP annotations。
