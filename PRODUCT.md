# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

React 19 + Vite + TypeScript, Tailwind v4, GSAP (`@gsap/react`) for motion, Phosphor icons. Built to static files and served by the v2 API (or nginx) on the same origin as the API (`bill.example.com`), so the session cookie and `X-CSRF-Token` work without CORS. Confirmed by the owner (2026-10-19).

## Users

One owner-operator of an API relay station (中转站): they buy API credit from upstream sites and resell it through card-shop and payment channels (链动, 云猫, Stripe…). The books are for their own use. At a desktop browser they record sales, purchases and expenses, drop in statement files, and read how the business is doing; on a phone they check balances and this month's numbers and occasionally record something. External AI agents also write through REST and MCP, and the owner glances at what landed.

## Product Purpose

Bookkeeper v2 tracks the relay station's operating numbers: revenue by channel, credit purchases by upstream site, fees and expenses, profit over time, and balances per currency. Every write takes effect at once and can be edited, deleted or undone; the ledger underneath keeps the full history. Success: recording takes seconds, this period's profit and where it came from are clear at a glance, and every figure leads to its transactions.

## Positioning

A personal operating ledger for one operator plus their AI agents: the system holds the rules (business types, fee rules, multi-currency, a hash-chained append-only ledger), the AI does much of the typing, and the UI is where the owner reads the numbers and fixes anything in a click. There is no built-in AI, no approval or review workflow, no period closing and no subscription management.

## Operating Context

- Transaction types: 销售收入, 销售退款, 额度采购, 费用支出, 采购退款, 资金划转, 期初余额, 手工凭证.
- One funds account (资金账户) holds all money, multi-currency (CNY, USD, GBP, HKD, credit unit UCR).
- Imports: statement files and records go through sources, rules and classification straight into transactions.
- Transactions have two states: 已入账 and 已删除. Edits keep the transaction number; deletes and edits are undoable.
- Book timezone Asia/Shanghai; business date is the natural day.

## Capabilities and Constraints

- All book APIs live under `/api/v1/books/{book_id}`; transaction types expose `input_schema`, defaults and examples, so entry forms are schema-driven; every write supports `?dry_run=true`, which the entry form uses for its live fee preview.
- Reports: summary, income statement, operations (daily / weekly / monthly), sales by channel, fees, credit purchases by site, trial balance, and a generic query; every row carries a drilldown to transactions. Exports: CSV, XLSX, Beancount, JSON.
- Copy follows docs/14-taxonomy-and-copy.md: status labels (§10.1), field names (§10.2), report names (§10.3), error format `{做什么}失败：{原因}。{怎么办}` (§10.4). Amounts carry the currency symbol and thousands separators; dates use `YYYY-MM-DD` or Chinese short dates in lists.
- UI language: Simplified Chinese.

## Brand Commitments

- 2026-10-19 the owner asked for a warm consumer-app style: simple, clear, premium, modular, a harmonious and comfortable palette, clear charts, efficient components, lively interaction. Named references: Apple and Wise. Fewer elements on screen; no safety-net ceremony (posting, review, confirmations).
- Earlier ask, still valid: clear modules, fast response, sensible data classification, rigorous logic, aligned visuals. Motion via GSAP.
- The previous looks (v1 "Aurora Ledger Glass"; the 2026-10-19 split-flap board) are replaced, not polished.

## Evidence on Hand

- Real taxonomy, account chart, channels and counterparty naming: docs/14-taxonomy-and-copy.md.
- Migrated real data from v1 (dev database only; never committed). No testimonials, customers or marketing claims exist and none are needed.

## Product Principles

1. Numbers first: this period's profit, where it came from, and the balances are readable at a glance.
2. Every number is traceable: a figure leads to its transactions, a transaction to its ledger history.
3. No ceremony: record, edit and delete directly; undo replaces confirmation dialogs.
4. The UI never invents accounting: forms are driven by the API's schemas, fee rules and dry runs.
5. Lean: only what the owner uses; AI-facing depth stays in the API.

## Accessibility & Inclusion

WCAG AA contrast in both themes, full keyboard operation for recording, editing and importing, `prefers-reduced-motion` honoured for all GSAP motion.
