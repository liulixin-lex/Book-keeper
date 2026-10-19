---
version: 1
slug: "v2-web-src-app-shell-tsx"
primary_target: "v2/web/src/app/Shell.tsx"
related_targets: ["v2/web/src/features"]
---

# Surface brief: bookkeeper web app (all modules)

Scope: the signed-in web app in v2/web — 概览, 交易, 统计, 导入, 设置, plus the 记一笔 sheet and sign-in. Visitor mode: Operate.
Audience and job: the owner-operator of an API relay station, mostly at a Mac desktop, phone for lookups. Jobs: record a sale / purchase / expense in seconds, read this period's profit and where it came from, fix any transaction directly (edit, delete, undo), drop in a statement file, read channel and upstream statistics.
Constraints: owner asks of 2026-10-19 (later the same day): add progressive blur and a frosted (磨砂) texture; modules, components and text must align visually. Copy follows docs/14; entry forms are schema-driven with a live dry run for fees; no posting / review / confirm dialogs — undo toasts instead; WCAG AA in both themes; reduced motion honoured; owner pinned the warm consumer-app world with Apple and Wise as references (2026-10-19).
Unresolved: none.

## Direction contract

THESIS: The ledger reads like a calm personal-finance app, not an accounting tool: this period's profit, its daily shape and where it came from, every figure one click from its transactions. Refuses the accounting dashboard of grey KPI tiles, journals and dense tables.

OWN-WORLD: Warm tinted ground (oklch 0.972 0.011 75), white soft-cornered cards (20px) lifted by one low warm shadow, warm ink (#2B241F family). One saturated action colour, a Wise-like lime (oklch 0.87 0.18 132) with forest ink, only on primary actions and current selection; money in and profit in forest green; costs in sand. Apple type: the platform face (SF Pro + PingFang SC on the owner's Mac and iPhone; each platform's UI face elsewhere), every figure in tabular numerals, headline figures in semibold with slight negative tracking. SF Pro Rounded was dropped on 2026-10-19: Chrome, the owner's browser, cannot reach it, and a substitute rounded face read foreign beside SF Pro. Capsule buttons, chips and segmented controls; 12px fields. Frosted glass is the material for whatever floats over content (phone tab bar, toasts, chart read-outs, the page behind a sheet): translucent warm fill, backdrop blur with extra saturation, a fine matte grain and a hairline top light; content dissolves into a progressive blur at every scroll edge (page top, above the phone tab bar, inside sheets). Cards stay solid white. One alignment grid: card content inset 24px (20px on phone), headers above cards on that inset, page titles on the wordmark's centre line, first content row on the 记一笔 capsule's top line. Translation named: the card's orange action becomes Wise lime (owner named Wise; one green family carries action, income and profit instead of orange competing with green).

STORY: The owner opens 概览, reads this month's profit and its daily bars, the balance per currency, the top channels and upstream sites; records with 记一笔 (big amount, type capsules, live fee split) and watches the figures roll to their new values; corrects anything in 交易 by editing in the detail sheet or deleting with an undo toast; drops a statement in 导入; reads trends in 统计.

FIRST VIEWPORT: Desktop: left sidebar 232px on the ground (wordmark, lime 记一笔 capsule with N shortcut, 概览 / 交易 / 统计 / 导入 / 设置, theme and account at the foot). Main column ≤1200px: title 概览 with the period capsule switcher on the right; row one, the profit card (7/12) with the rolling profit figure, change against the previous period, 收入 / 成本 / 手续费, and a daily revenue-vs-cost bar chart with a profit line; the balances card (5/12) with the base-currency total and one row per currency. Row two, 渠道 and 上游 bar lists; row three, 最近记录 and 待处理. Phone: single column, bottom tab bar 概览 / 交易 / ＋ / 统计 / 更多 with a raised lime ＋.

FORM: Challenger "digital-design-canon-warm-consumer-app-surface", pinned by the owner on 2026-10-19 over the assigned split-flap direction (seed key 2240521f). Signature move: rolling figures — every money figure rolls digit by digit to its new value (GSAP, about 600 ms, exponential ease-out, small per-digit stagger) when the period changes or after a write; 记一笔 closes with a drawn check.

FINISH: unreviewed and undocumented is unfinished; this build ends with the finish review, the verdict, DESIGN.md, and every shipping raster carrying its provenance
