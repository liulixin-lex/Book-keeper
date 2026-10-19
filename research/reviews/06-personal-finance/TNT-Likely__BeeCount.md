# TNT-Likely/BeeCount（蜜蜂记账，Flutter 客户端）

- 分类：06 个人记账（本地优先移动应用）
- 语言 / 许可证 / 最近提交：Dart (Flutter) / **Business Source License**（源码可见）/ 2026-10-18
- 审查范围：`README.md`、`lib/`（数据层与同步）、发布说明

## 定位

国内用户量较大的开源记账 App：本地 SQLite（Drift），可选五种同步（自建 BeeCount Cloud / iCloud / Supabase / WebDAV / S3），支持 AI/OCR/语音记账、多账本、多币种、预算、周期记账。

## 可借鉴

- [BC-A1] “本地优先 + 多种同步后端可选”：数据可随时导出带走（SQLite + 附件）。
- [BC-A2] 多种快捷记账入口（截图 OCR、语音、文本 → AI 解析成草稿 → 用户确认）。
- [BC-A3] 中文/繁体/英文完整本地化。

## 不采用 / 风险

- BSL 许可；单式个人记账。

## 对新系统的启示

- 后续前端阶段可参考其移动端快捷录入与 AI 草稿确认交互；本次后端只需保证 API 支持“草稿（dry-run）→ 确认提交”。
