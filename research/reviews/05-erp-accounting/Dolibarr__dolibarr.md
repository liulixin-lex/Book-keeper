# Dolibarr/dolibarr（htdocs/accountancy、htdocs/compta）

- 分类：05 ERP 会计模块
- 语言 / 许可证 / 最近提交：PHP / GPL-3.0 / 2026-10-18
- 审查范围（稀疏检出）：`htdocs/accountancy/class/{bookkeeping,lettering,accountingaccount,accountingjournal,bookkeepingtemplate,accountancyexport,accountancyimport}.class.php`、`htdocs/accountancy/{customer,supplier,journal,closure}`

## 定位

面向中小企业/协会的 ERP；会计采用“业务单据 → 科目绑定 → 记账 → 验证锁定 → 导出”的流水线，适配法国等地的会计导出格式。

## 数据模型

- **bookkeeping（总账行）**：`doc_date`、`doc_type` + `doc_ref` + `fk_doc` + `fk_docdet`（来源单据及明细行）、`thirdparty_code`、**`subledger_account`（辅助账/往来明细账号）**、`numero_compte`（科目）、`debit/credit/montant/sens`、`code_journal`、`piece_num`（凭证号）、**`lettering_code` + `date_lettering`（核销字母码）**、**`date_validated`（验证即锁定）**、`date_export`（已导出标记）、`import_key`；
- 科目表（多套科目体系可切换）、日记账（销售/采购/银行/杂项/存货…）、**会计分组/报表类别**；
- 记账模板（bookkeepingtemplate + lines）。

## 记账逻辑与算法

- **两步法**：业务单据的每一行先“绑定（binding）”到会计科目（系统按产品、往来方、默认设置自动建议，人工可批量修改），绑定完成后再“转入总账”生成分录——**分类与过账分离**；
- **核销字母码**：同一组相互核销的分录共用一个码，大写为完全核销、小写为部分核销；可按往来方自动核销；
- **验证 = 锁定**：对某期间的分录执行验证后写入 `date_validated`，之后不可修改/删除；
- **期间结账**：校验 → 生成结转分录（可分开辅助账）→ 开立新期间，并可生成期初冲回分录；
- 导出格式插件（多种会计软件/税务格式）与导入（含 import_key 追踪导入批次）。

## 可借鉴

- [DO1] **辅助账（subledger）**：主科目“应付账款”下按往来方的明细账号——总账科目保持精简，往来明细独立。
- [DO2] 分类（科目绑定）与过账分离，绑定阶段可批量建议与修改。
- [DO3] 核销码（完全/部分）。
- [DO4] 验证即锁定（按日期范围批量写入验证时间）；导出时间标记。
- [DO5] import_key 追踪导入批次；来源单据 + 明细行引用。

## 不采用 / 风险

- 单币种为主；PHP 老代码；GPL。

## 对新系统的启示

- 科目保持少而稳定（如“上游采购成本”），供应商/站点、渠道作为辅助核算（subledger / 维度），报表可按辅助核算展开；
- 导入流程：解析 → 分类建议（绑定）→ 人工/规则确认 → 过账；
- 分录行级 `locked_at`（验证锁定）与期间锁并存。
