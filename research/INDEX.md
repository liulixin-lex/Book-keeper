# 记账项目调研索引

共 81 个项目，按 9 个类别存放于 `repos/<类别>/<owner>__<repo>`，逐个审查结果在 `reviews/<类别>/<owner>__<repo>.md`。

仓库只读审查，未执行其中任何脚本。

## 01-plaintext-accounting 纯文本复式记账（8）

| 项目 | 语言 / 许可证 / 最近提交 | 关注点 | 审查 |
|---|---|---|---|
| [ledger/ledger](https://github.com/ledger/ledger) | C++ / BSD-3-Clause / 2026-09-22 | C++ 经典纯文本复式记账引擎：自动平衡、价格历史、报表查询语言 | [review](reviews/01-plaintext-accounting/ledger__ledger.md) |
| [hledgerorg/hledger](https://github.com/hledgerorg/hledger) | Haskell / GPL-3.0 / 2026-10-18（非常活跃） | Haskell 纯文本记账：严格校验、CSV 规则导入、多币种成本/市值、Web API | [review](reviews/01-plaintext-accounting/hledgerorg__hledger.md) |
| [beancount/beancount](https://github.com/beancount/beancount) | Python（C++ 解析器）/ GPL-2.0 / 2026-08-23 | Python 复式记账语言：插件、余额断言、lot 成本、BQL 查询 | [review](reviews/01-plaintext-accounting/beancount__beancount.md) |
| [beancount/fava](https://github.com/beancount/fava) | Python (Flask) + Svelte/TypeScript / MIT / 2026-10-18 | Beancount Web 界面：编辑、报表、导入 | [review](reviews/01-plaintext-accounting/beancount__fava.md) |
| [rustledger/rustledger](https://github.com/rustledger/rustledger) | Rust / GPL-3.0 / 2026-10-18 | Rust 实现的 Beancount 兼容引擎 | [review](reviews/01-plaintext-accounting/rustledger__rustledger.md) |
| [tackler-ng/tackler](https://github.com/tackler-ng/tackler) | Rust / Apache-2.0 / 2026-10-17 | Rust 记账引擎：原生 Git 存储、审计追溯 | [review](reviews/01-plaintext-accounting/tackler-ng__tackler.md) |
| [ananthakumaran/paisa](https://github.com/ananthakumaran/paisa) | Go + Svelte / AGPL-3.0 / 2026-10-18 | 基于 ledger/hledger/beancount 的个人财务看板 | [review](reviews/01-plaintext-accounting/ananthakumaran__paisa.md) |
| [sboehler/knut](https://github.com/sboehler/knut) | Go / Apache-2.0 / 2026-09 | Go 纯文本记账：多币种估值 | [review](reviews/01-plaintext-accounting/sboehler__knut.md) |

## 02-ledger-engines 账本引擎 / 核心库（10）

| 项目 | 语言 / 许可证 / 最近提交 | 关注点 | 审查 |
|---|---|---|---|
| [formancehq/ledger](https://github.com/formancehq/ledger) | Go / MIT（核心）+ 企业版 / 2026-10-16 | 可编程核心账本：Numscript、幂等、不可变日志、多币种 | [review](reviews/02-ledger-engines/formancehq__ledger.md) |
| [tigerbeetle/tigerbeetle](https://github.com/tigerbeetle/tigerbeetle) | Zig / Apache-2.0 / 2026-10-14 | 高性能复式记账数据库：转账/账户模型、两阶段转账、强一致 | [review](reviews/02-ledger-engines/tigerbeetle__tigerbeetle.md) |
| [blnkfinance/blnk](https://github.com/blnkfinance/blnk) | Go + PostgreSQL + Redis 队列 / Apache-2.0 / 2026-10-05 | 开源金融核心账本：余额监控、对账引擎、inflight 交易 | [review](reviews/02-ledger-engines/blnkfinance__blnk.md) |
| [LerianStudio/midaz](https://github.com/LerianStudio/midaz) | Go（PostgreSQL + MongoDB + RabbitMQ + Valkey）/ Elastic License 2.0（源码可见，非 OSI 开源）/ 2026-10-18 | 云原生账本平台：多资产、组合/科目、交易 DSL | [review](reviews/02-ledger-engines/LerianStudio__midaz.md) |
| [devaccuracy/ledgerforge](https://github.com/devaccuracy/ledgerforge) | Go + PostgreSQL + Redis / Apache-2.0（开源核心 + 企业版）/ 2026-10-10 | 面向 AI 资金流转的复式账本 | [review](reviews/02-ledger-engines/devaccuracy__ledgerforge.md) |
| [hoophq/sequence](https://github.com/hoophq/sequence) | Clojure + DynamoDB / Apache-2.0 / 2026-07（代码基本停更，CI 维护） | 不可变账本服务 | [review](reviews/02-ledger-engines/hoophq__sequence.md) |
| [pgr0ss/pgledger](https://github.com/pgr0ss/pgledger) | PL/pgSQL / MIT / 2026-10-16 | 纯 PostgreSQL 复式账本实现 | [review](reviews/02-ledger-engines/pgr0ss__pgledger.md) |
| [flash-oss/medici](https://github.com/flash-oss/medici) | TypeScript / MIT / 2026-07-29 | Node/Mongo 复式记账库：日记账/分录/余额快照 | [review](reviews/02-ledger-engines/flash-oss__medici.md) |
| [apache/fineract](https://github.com/apache/fineract) | Java (Spring) / Apache-2.0 / 2026-10-17 | 核心银行系统：总账、会计规则映射、期末结账 | [review](reviews/02-ledger-engines/apache__fineract.md) |
| [Ekwo-ai/ekwo-os](https://github.com/Ekwo-ai/ekwo-os) | SQL (Postgres/Supabase) + TypeScript / AGPL-3.0（格式库 MIT）/ 2026-10-18 | Postgres/Supabase 复式会计内核 | [review](reviews/02-ledger-engines/Ekwo-ai__ekwo-os.md) |

## 03-accounting-libraries 会计库 / 框架（6）

| 项目 | 语言 / 许可证 / 最近提交 | 关注点 | 审查 |
|---|---|---|---|
| [envato/double_entry](https://github.com/envato/double_entry) | Ruby / MIT / 2026-01 | Ruby 复式记账：账户/转账白名单、锁、余额缓存 | [review](reviews/03-accounting-libraries/envato__double_entry.md) |
| [mbulat/plutus](https://github.com/mbulat/plutus) | Ruby / MIT / 2025-03 | Ruby 复式记账：科目类型、分录借贷校验 | [review](reviews/03-accounting-libraries/mbulat__plutus.md) |
| [adamcharnock/django-hordak](https://github.com/adamcharnock/django-hordak) | Python / MIT / 2026-04 | Django 复式记账模型层：多币种腿、数据库约束 | [review](reviews/03-accounting-libraries/adamcharnock__django-hordak.md) |
| [arrobalytics/django-ledger](https://github.com/arrobalytics/django-ledger) | Python / GPL-3.0 / 2026-10-09 | Django 复式会计与财务分析引擎：实体/科目表/账簿 | [review](reviews/03-accounting-libraries/arrobalytics__django-ledger.md) |
| [ekmungai/python-accounting](https://github.com/ekmungai/python-accounting) | Python / MIT / 2026-10-16 | Python IFRS/GAAP 会计库：报表、税、对账 | [review](reviews/03-accounting-libraries/ekmungai__python-accounting.md) |
| [datasignstech/pyluca](https://github.com/datasignstech/pyluca) | Python / MIT / 2026-07 | Python 复式记账库：规则配置化 | [review](reviews/03-accounting-libraries/datasignstech__pyluca.md) |

## 04-smb-accounting 中小企业记账（9）

| 项目 | 语言 / 许可证 / 最近提交 | 关注点 | 审查 |
|---|---|---|---|
| [bigcapitalhq/bigcapital](https://github.com/bigcapitalhq/bigcapital) | TypeScript（NestJS + Knex/Objection，多租户 MySQL）+ React / AGPL-3.0 / 2026-10-16 | 中小企业会计：科目表、手工凭证、报表、库存、API | [review](reviews/04-smb-accounting/bigcapitalhq__bigcapital.md) |
| [akaunting/akaunting](https://github.com/akaunting/akaunting) | PHP (Laravel) + Vue / **Business Source License**（源码可见，非 OSI 开源；早期为 GPL）/ 2026-10-08 | Laravel 在线会计：多币种、交易、对账、模块化 | [review](reviews/04-smb-accounting/akaunting__akaunting.md) |
| [frappe/books](https://github.com/frappe/books) | TypeScript + Vue / AGPL-3.0 / 2026-10（仓库已归档） | 桌面会计：Schema 驱动、复式过账、报表 | [review](reviews/04-smb-accounting/frappe__books.md) |
| [ledgersmb/LedgerSMB](https://github.com/ledgersmb/LedgerSMB) | Perl + PostgreSQL（大量逻辑在存储过程中）/ GPL-2.0 / 2026-10-18 | Web 复式会计/ERP：期间关闭、对账、审批工作流 | [review](reviews/04-smb-accounting/ledgersmb__LedgerSMB.md) |
| [andrewdwallo/erpsaas](https://github.com/andrewdwallo/erpsaas) | PHP / MIT / 2026-03 | Laravel/Filament 复式权责发生制会计平台 | [review](reviews/04-smb-accounting/andrewdwallo__erpsaas.md) |
| [dubbl-org/dubbl](https://github.com/dubbl-org/dubbl) | TypeScript（Next.js + Drizzle + PostgreSQL）/ Apache-2.0 / 2026-10-11 | API-first 的 Xero/QuickBooks 开源替代 | [review](reviews/04-smb-accounting/dubbl-org__dubbl.md) |
| [crater-invoice-inc/crater](https://github.com/crater-invoice-inc/crater) | PHP (Laravel) + Vue / AGPL-3.0 / 2024-08（基本停更） | 开票与支出管理 | [review](reviews/04-smb-accounting/crater-invoice-inc__crater.md) |
| [midday-ai/midday](https://github.com/midday-ai/midday) | TypeScript（Bun、Next.js、Supabase/Postgres、Drizzle、Trigger.dev 任务）/ AGPL-3.0 / 2026-06 | 小企业财务：银行同步、交易匹配、发票、收件箱 | [review](reviews/04-smb-accounting/midday-ai__midday.md) |
| [erp-mafia/accounted](https://github.com/erp-mafia/accounted) | TypeScript（Next.js 16 + Supabase/Postgres）/ AGPL-3.0 / 2026-10-18 | 为 Agent 构建的开源 ERP | [review](reviews/04-smb-accounting/erp-mafia__accounted.md) |

## 05-erp-accounting ERP 会计模块（8）

| 项目 | 语言 / 许可证 / 最近提交 | 关注点 | 审查 |
|---|---|---|---|
| [frappe/erpnext](https://github.com/frappe/erpnext) | Python (Frappe) + JS / GPL-3.0 / 2026-10-18 | ERPNext 会计模块：总账、会计维度、期间关闭、银行对账 | [review](reviews/05-erp-accounting/frappe__erpnext.md) |
| [odoo/odoo](https://github.com/odoo/odoo) | Python / LGPL-3.0（社区版）/ 2026-10-18 | Odoo 会计：科目、凭证、对账模型、税、锁账日期 | [review](reviews/05-erp-accounting/odoo__odoo.md) |
| [OCA/account-reconcile](https://github.com/OCA/account-reconcile) | Python (Odoo 19) / AGPL-3.0 / 2026-10-16 | Odoo 社区对账模块 | [review](reviews/05-erp-accounting/OCA__account-reconcile.md) |
| [tryton/tryton](https://github.com/tryton/tryton) | Python / GPL-3.0 / 2026-10-15 | Tryton 会计：期间/年度、对账、银行流水规则 | [review](reviews/05-erp-accounting/tryton__tryton.md) |
| [Dolibarr/dolibarr](https://github.com/Dolibarr/dolibarr) | PHP / GPL-3.0 / 2026-10-18 | Dolibarr 会计：日记账绑定、导出 | [review](reviews/05-erp-accounting/Dolibarr__dolibarr.md) |
| [apache/ofbiz-framework](https://github.com/apache/ofbiz-framework) | Java（实体引擎 + 服务引擎 + XML 定义）/ Apache-2.0 / 2026-10-18 | OFBiz 会计：GL 账户、会计交易、过账规则 | [review](reviews/05-erp-accounting/apache__ofbiz-framework.md) |
| [idempiere/idempiere](https://github.com/idempiere/idempiere) | Java (OSGi) / GPL-2.0 / 2026-10-14 | iDempiere 会计引擎：Doc/Fact 过账、多会计架构 | [review](reviews/05-erp-accounting/idempiere__idempiere.md) |
| [osbzr/gooderp_addons](https://github.com/osbzr/gooderp_addons) | Python（Odoo 10/12 框架）/ AGPL-3.0（历史版本）/ GitHub 主干现仅剩 README（2019 年后源码转为捐赠获取）；本次从历史提交 `a5ae08e`（2019-08）读取 `finance` 模块 | GoodERP（中国）财务：凭证、科目、期间 | [review](reviews/05-erp-accounting/osbzr__gooderp_addons.md) |

## 06-personal-finance 个人 / 家庭财务（15）

| 项目 | 语言 / 许可证 / 最近提交 | 关注点 | 审查 |
|---|---|---|---|
| [firefly-iii/firefly-iii](https://github.com/firefly-iii/firefly-iii) | PHP (Laravel) / AGPL-3.0 / 2026-10-18（2.5 万星，非常活跃） | 个人财务（复式）：规则引擎、预算、多币种、REST API | [review](reviews/06-personal-finance/firefly-iii__firefly-iii.md) |
| [actualbudget/actual](https://github.com/actualbudget/actual) | TypeScript（React + Node，SQLite，本地优先 + 同步服务器）/ MIT / 2026-10-18（近 3 万星） | 本地优先预算：CRDT 同步、规则、对账 | [review](reviews/06-personal-finance/actualbudget__actual.md) |
| [we-promise/sure](https://github.com/we-promise/sure) | Ruby on Rails + PostgreSQL / AGPL-3.0 / 2026-10-18（原 maybe-finance/maybe 已归档，本仓库为社区延续） | Maybe Finance 社区续作：账户、交易、同步 | [review](reviews/06-personal-finance/we-promise__sure.md) |
| [Gnucash/gnucash](https://github.com/Gnucash/gnucash) | C / C++ / GPL-2.0+ / 2026-10-18 | GnuCash 引擎：Split/Transaction/Lot、调度事务、价格库 | [review](reviews/06-personal-finance/Gnucash__gnucash.md) |
| [KDE/kmymoney](https://github.com/KDE/kmymoney) | C++ (Qt/KDE) / GPL-2.0+ / 2026-10-18 | KMyMoney：对账、计划交易、导入匹配 | [review](reviews/06-personal-finance/KDE__kmymoney.md) |
| [moneymanagerex/moneymanagerex](https://github.com/moneymanagerex/moneymanagerex) | C++ (wxWidgets) + SQLite / GPL-2.0 / 2026-10-17 | Money Manager Ex：账户、计划交易、资产 | [review](reviews/06-personal-finance/moneymanagerex__moneymanagerex.md) |
| [ghostfolio/ghostfolio](https://github.com/ghostfolio/ghostfolio) | TypeScript（Angular + NestJS + Prisma + PostgreSQL + Redis）/ AGPL-3.0 / 2026-10-18 | 财富管理：投资组合计算、汇率、数据源 | [review](reviews/06-personal-finance/ghostfolio__ghostfolio.md) |
| [mayswind/ezbookkeeping](https://github.com/mayswind/ezbookkeeping) | Go + Vue / MIT / 2026-10-15（近 6 千星） | 自托管个人记账（Go+Vue）：多币种、导入、MCP | [review](reviews/06-personal-finance/mayswind__ezbookkeeping.md) |
| [TNT-Likely/BeeCount](https://github.com/TNT-Likely/BeeCount) | Dart (Flutter) / **Business Source License**（源码可见）/ 2026-10-18 | 本地优先记账 App（Flutter） | [review](reviews/06-personal-finance/TNT-Likely__BeeCount.md) |
| [TNT-Likely/BeeCount-Cloud](https://github.com/TNT-Likely/BeeCount-Cloud) | Python（FastAPI + SQLAlchemy + Alembic，SQLite/Postgres）+ React / **BSL** / 2026-10-18 | BeeCount 自托管同步服务端 | [review](reviews/06-personal-finance/TNT-Likely__BeeCount-Cloud.md) |
| [getmoneynote/moneynote-api](https://github.com/getmoneynote/moneynote-api) | Java (Spring Boot + JPA) / MIT / 2026-03 | 九快记账后端（Java）：账本/账户/分类 | [review](reviews/06-personal-finance/getmoneynote__moneynote-api.md) |
| [glink25/Cent](https://github.com/glink25/Cent) | TypeScript (React, pnpm monorepo) / CC BY-NC-SA 4.0（非商业）/ 2026-09-22 | 多人协作记账 Web App | [review](reviews/06-personal-finance/glink25__Cent.md) |
| [dingdangdog/cashbook](https://github.com/dingdangdog/cashbook) | TypeScript（Nuxt + Prisma + PostgreSQL）/ MIT / 2026-06（仅维护，作者在做新项目） | 家庭私人记账本 | [review](reviews/06-personal-finance/dingdangdog__cashbook.md) |
| [kresusapp/kresus](https://github.com/kresusapp/kresus) | TypeScript (Node + TypeORM) / AGPL-3.0 / 2026-10-17 | 个人财务：银行同步、自动分类 | [review](reviews/06-personal-finance/kresusapp__kresus.md) |
| [rotki/rotki](https://github.com/rotki/rotki) | Python (gevent/Flask) + Vue / AGPL-3.0 / 2026-10-16 | 加密资产会计：成本基础、盈亏计算、事件建模 | [review](reviews/06-personal-finance/rotki__rotki.md) |

## 07-import-reconciliation 导入、分类与对账（11）

| 项目 | 语言 / 许可证 / 最近提交 | 关注点 | 审查 |
|---|---|---|---|
| [beancount/beangulp](https://github.com/beancount/beangulp) | Python / GPL-2.0 / 2026-05 | Beancount 导入框架：识别/提取/归档 | [review](reviews/07-import-reconciliation/beancount__beangulp.md) |
| [beancount/smart_importer](https://github.com/beancount/smart_importer) | Python (scikit-learn) / MIT / 2026-07 | 机器学习自动分类与去重 | [review](reviews/07-import-reconciliation/beancount__smart_importer.md) |
| [jbms/beancount-import](https://github.com/jbms/beancount-import) | Python + TypeScript（Web UI）/ GPL-2.0 / 2026-10-14 | 交互式导入与匹配（Web UI） | [review](reviews/07-import-reconciliation/jbms__beancount-import.md) |
| [deb-sig/double-entry-generator](https://github.com/deb-sig/double-entry-generator) | Go / Apache-2.0 / 2026-10-04（730 星，国内纯文本记账圈最常用的导入器） | 规则驱动导入：支付宝/微信/火币 → Beancount/Ledger | [review](reviews/07-import-reconciliation/deb-sig__double-entry-generator.md) |
| [dhr2333/Beancount-Trans](https://github.com/dhr2333/Beancount-Trans) | Python (Django) 后端 + Vue 前端 + Flutter 移动端（子模块）/ MIT / 2026-10-17 | 中国账单上传自动转换为 Beancount | [review](reviews/07-import-reconciliation/dhr2333__Beancount-Trans.md) |
| [firefly-iii/data-importer](https://github.com/firefly-iii/data-importer) | PHP (Laravel) / AGPL-3.0 / 2026-10-18 | Firefly III 导入器：CSV/银行接口、映射与去重 | [review](reviews/07-import-reconciliation/firefly-iii__data-importer.md) |
| [egh/ledger-autosync](https://github.com/egh/ledger-autosync) | Python / GPL-3.0 / 2026-04 | 银行同步与去重（OFX） | [review](reviews/07-import-reconciliation/egh__ledger-autosync.md) |
| [GrandmasterTash/OpenRec](https://github.com/GrandmasterTash/OpenRec) | Rust（+ Lua 规则）/ MIT / 2022-01（停更，但设计完整） | Rust 对账引擎：规则匹配、分组 | [review](reviews/07-import-reconciliation/GrandmasterTash__OpenRec.md) |
| [juspay/hyperswitch-reconciliation](https://github.com/juspay/hyperswitch-reconciliation) | Rust (Actix + Diesel + PostgreSQL) / Apache-2.0 / 2026-10-16 | 支付对账引擎（Rust） | [review](reviews/07-import-reconciliation/juspay__hyperswitch-reconciliation.md) |
| [benjamin-awd/monopoly](https://github.com/benjamin-awd/monopoly) | Python / AGPL-3.0 / 2026-10-12 | 银行对账单 PDF → CSV | [review](reviews/07-import-reconciliation/benjamin-awd__monopoly.md) |
| [kedder/ofxstatement](https://github.com/kedder/ofxstatement) | Python / GPL-3.0 / 2026-08 | 银行对账单 → OFX 转换框架 | [review](reviews/07-import-reconciliation/kedder__ofxstatement.md) |

## 08-mcp-ai-access MCP / 外部 AI 接入（11）

| 项目 | 语言 / 许可证 / 最近提交 | 关注点 | 审查 |
|---|---|---|---|
| [XeroAPI/xero-mcp-server](https://github.com/XeroAPI/xero-mcp-server) | TypeScript (MCP SDK + xero-node) / MIT / 2026-06 | Xero 官方 MCP：会计对象读写工具设计 | [review](reviews/08-mcp-ai-access/XeroAPI__xero-mcp-server.md) |
| [intuit/quickbooks-online-mcp-server](https://github.com/intuit/quickbooks-online-mcp-server) | TypeScript / Apache-2.0 / 2026-09 | QuickBooks 官方 MCP | [review](reviews/08-mcp-ai-access/intuit__quickbooks-online-mcp-server.md) |
| [stripe/ai](https://github.com/stripe/ai) | TypeScript / Python / MIT / 2026-10-18 | Stripe 官方 Agent Toolkit 与 MCP | [review](reviews/08-mcp-ai-access/stripe__ai.md) |
| [etnperlong/firefly-iii-mcp](https://github.com/etnperlong/firefly-iii-mcp) | TypeScript（Turborepo：core / local / server / cloudflare-worker）/ MIT / 2025-06 | Firefly III MCP | [review](reviews/08-mcp-ai-access/etnperlong__firefly-iii-mcp.md) |
| [henfrydls/actual-budget-mcp](https://github.com/henfrydls/actual-budget-mcp) | TypeScript（@actual-app/api）/ MIT / 2026-10-18 | Actual Budget MCP | [review](reviews/08-mcp-ai-access/henfrydls__actual-budget-mcp.md) |
| [vanto/beanquery-mcp](https://github.com/vanto/beanquery-mcp) | Python (FastMCP) / MIT / 2025-04（实验性） | Beancount 查询 MCP | [review](reviews/08-mcp-ai-access/vanto__beanquery-mcp.md) |
| [StdioA/beancount-mcp](https://github.com/StdioA/beancount-mcp) | Python (FastMCP, watchdog) / MIT / 2025-05 | Beancount 查询+提交交易 MCP | [review](reviews/08-mcp-ai-access/StdioA__beancount-mcp.md) |
| [iiAtlas/hledger-mcp](https://github.com/iiAtlas/hledger-mcp) | TypeScript (Node, MCP SDK, zod) / MIT / 2025（npm `@iiatlas/hledger-mcp`，有 .mcpb 安装包） | hledger MCP | [review](reviews/08-mcp-ai-access/iiAtlas__hledger-mcp.md) |
| [erpipe-org/mcp-odoo](https://github.com/erpipe-org/mcp-odoo) | Python (FastMCP) / MPL-2.0 / 2026（活跃，带托管版） | Odoo MCP：受控写入、多实例 | [review](reviews/08-mcp-ai-access/erpipe-org__mcp-odoo.md) |
| [rakeshgangwar/erpnext-mcp-server](https://github.com/rakeshgangwar/erpnext-mcp-server) | TypeScript (MCP SDK, axios) / MIT / 2026-04 | ERPNext MCP | [review](reviews/08-mcp-ai-access/rakeshgangwar__erpnext-mcp-server.md) |
| [norman-finance/norman-mcp-server](https://github.com/norman-finance/norman-mcp-server) | Python (FastMCP) / MIT / 2026-10-16（活跃） | 欧洲记账/开票/税务 MCP | [review](reviews/08-mcp-ai-access/norman-finance__norman-mcp-server.md) |

## 09-api-specs-standards API 规范与标准（3）

| 项目 | 语言 / 许可证 / 最近提交 | 关注点 | 审查 |
|---|---|---|---|
| [XeroAPI/Xero-OpenAPI](https://github.com/XeroAPI/Xero-OpenAPI) | OpenAPI 3.0 YAML / MIT / 2026（官方维护，xero_accounting.yaml 约 93 万字节、138 个路径） | Xero 会计 API OpenAPI 规范 | [review](reviews/09-api-specs-standards/XeroAPI__Xero-OpenAPI.md) |
| [apideck-libraries/openapi-specs](https://github.com/apideck-libraries/openapi-specs) | OpenAPI 3.x YAML / Apache-2.0 / 2026（accounting.yml 约 5 万行） | Apideck 统一会计 API 规范 | [review](reviews/09-api-specs-standards/apideck-libraries__openapi-specs.md) |
| [r3f/china-chart-of-accounts](https://github.com/r3f/china-chart-of-accounts) | CSV / GPL-3.0 / 2020 | 中国会计科目表模板 | [review](reviews/09-api-specs-standards/r3f__china-chart-of-accounts.md) |
