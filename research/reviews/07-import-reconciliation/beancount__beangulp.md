# beancount/beangulp

- 分类：07 导入框架
- 语言 / 许可证 / 最近提交：Python / GPL-2.0 / 2026-05
- 审查范围：`beangulp/{importer,identify,extract,archive,similar,cache,file_type,testing}.py`、`examples/`

## 定位

Beancount 官方导入框架（beancount.ingest 的继任者）：识别文件 → 抽取分录 → 去重 → 归档原始文件。

## 设计要点

- **Importer 接口**：`name()`、`identify(filepath)`（这个文件归我处理吗）、`account(filepath)`（文件对应哪个账户）、`date(filepath)`（文件日期）、`filename(filepath)`（归档文件名）、`extract(filepath, existing)`（抽取分录，可参考已有账本）、`deduplicate(entries, existing)`、`sort()`；
- **三条命令**：identify（列出每个文件被哪个导入器认领）、extract（抽取）、archive（按 `账户目录/日期.原名` 归档原始文件到文档树）；
- **相似条目去重**：在 ±N 天窗口内查找已有条目；启发式比较器：日期差上限 + 同一账户的 posting 金额相差在 epsilon（默认 5%）内即视为重复，抽取结果标记为疑似重复；
- **文件类型识别**（MIME/扩展名）、转换结果缓存（如 PDF 转文本只做一次）；
- **测试工具（testing）**：每个导入器配样例文件与期望输出，回归测试比对。

## 可借鉴

- [BG-1] 导入器统一接口：识别、归属账户、文件日期、抽取、去重、归档命名。
- [BG-2] 原始文件按账户/日期归档，与分录互相引用。
- [BG-3] 相似度去重窗口 + 金额容差。
- [BG-4] 导入器样例文件 + 期望输出的回归测试。

## 不采用 / 风险

- GPL；文本账本目标。

## 对新系统的启示

- `SourceAdapter` 接口：`detect(file) → confidence`、`parse(file) → StatementLines`、`statement_period()`、`account_hint()`；每个适配器带样例与期望输出测试；
- 原始文件存储（内容哈希命名）+ 元数据（来源、账户、期间、上传人）。
