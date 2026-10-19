# beancount/fava

- 分类：01 纯文本复式记账（Beancount 的 Web 界面）
- 语言 / 许可证 / 最近提交：Python (Flask) + Svelte/TypeScript / MIT / 2026-10-18
- 审查范围：`src/fava/{json_api.py,core/*.py}`、`core/{attributes,file,ingest,budgets,filters,conversion}.py`

## 定位

Beancount 的功能型 Web 前端：浏览账户树/日记账/报表、编辑源文件、导入、文档管理、预算、查询。

## 数据模型

沿用 Beancount 指令；用 **entry hash（内容哈希）** 作为条目标识（Beancount 本身没有 ID）。

## 记账逻辑与算法

- **按收付款方推荐科目**：`payee_accounts()` 用“指数衰减排序器”统计该收付款方历史交易涉及的科目，近期权重更高；`payee_transaction()` 返回该收付款方最近一笔交易作为模板；按摘要（narration）自动补全。
- 报表换算：`conversion` 支持 at_cost / at_value / units / 指定币种。
- 预算：`custom "budget"` 指令，按日历精确分摊。
- 过滤：时间过滤（年/季/月/自定义区间）、账户过滤、高级过滤语法（tag、link、payee、元数据）。

## 追溯与审计

- **编辑乐观并发**：读取源文件/片段时返回 `sha256sum`，写回必须带上该哈希，不一致则拒绝（文件已被他人修改）。
- `get_source_slice(entry_hash)`：从条目定位到源文件中的原文片段并可原位编辑/删除。
- `get_context(entry_hash)`：条目上下文（前后余额、相关条目）。
- `get_changed`：监测文件变化自动重载。

## 导入、分类与对账

- 集成 beangulp 导入器：上传文件 → 识别 → 抽取 → 在界面中逐条确认/修改 → 写入指定文件；文档自动归档到账户目录并可挂接到条目。

## API 与扩展

- 内部 JSON API（约 40 个端点）；扩展机制（Fava extensions，可加页面与钩子）。

## 可借鉴

- [FV1] 收付款方 → 科目推荐（指数衰减加权历史频次）+ 最近交易作为模板 —— 录入提效。
- [FV2] 修改操作携带“读取时的版本/哈希”做乐观并发控制。
- [FV3] 从任一条目跳转到来源原文（source slice）与上下文（前后余额）。
- [FV4] 导入流程：上传 → 识别导入器 → 预览抽取结果 → 逐条确认 → 写入 + 文档归档挂接。
- [FV5] 报表统一的换算参数（成本/市值/单位/目标币种）与时间过滤器。

## 不采用 / 风险

- 以文本文件为后端，写入即改文件；新系统用数据库，但“版本号乐观锁”理念相同。

## 对新系统的启示

- 交易录入接口提供“智能默认”：根据交易对手/摘要推荐交易类型、科目与上次金额；
- 所有更新接口要求 `expected_version`（或 ETag/If-Match）；
- 交易详情 API 返回：分录、来源凭证原文定位、前后余额、审计历史。
