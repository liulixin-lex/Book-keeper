---
name: 账本 Bookkeeper v2
description: 一个人的经营账本，读起来像一款温暖的个人理财 app：本期利润、每日走势、钱从哪来，每个数字一点就到交易。
colors:
  # Light (:root) — canonical values are OKLCH in v2/web/src/styles/index.css
  ground: "oklch(0.972 0.011 75)"
  card: "oklch(1 0 0)"
  well: "oklch(0.955 0.012 75)"
  well-2: "oklch(0.935 0.014 75)"
  line: "oklch(0.925 0.012 75)"
  line-strong: "oklch(0.87 0.016 75)"
  ink: "oklch(0.255 0.012 55)"
  ink-2: "oklch(0.47 0.02 55)"
  ink-3: "oklch(0.52 0.018 60)"
  lime: "oklch(0.87 0.18 132)"
  lime-hover: "oklch(0.84 0.18 132)"
  lime-ink: "oklch(0.3 0.08 135)"
  lime-wash: "oklch(0.87 0.18 132 / 0.28)"
  pos: "oklch(0.5 0.11 148)"
  pos-wash: "oklch(0.5 0.11 148 / 0.1)"
  neg: "oklch(0.53 0.17 30)"
  neg-wash: "oklch(0.53 0.17 30 / 0.09)"
  warn: "oklch(0.72 0.15 62)"
  warn-text: "oklch(0.52 0.12 60)"
  warn-wash: "oklch(0.72 0.15 62 / 0.14)"
  series-in: "oklch(0.72 0.12 150)"
  series-cost: "oklch(0.85 0.042 72)"
  series-profit: "oklch(0.38 0.09 145)"
  ring: "oklch(0.5 0.11 148)"
  mark: "oklch(0.42 0.1 148)"
  scrim: "oklch(0.28 0.02 60 / 0.26)"
  toast: "oklch(0.255 0.012 55)"
  toast-ink: "oklch(0.97 0.008 75)"
  frost: "oklch(0.995 0.004 75 / 0.68)"
  frost-ink: "oklch(0.255 0.012 55 / 0.8)"
  frost-edge: "oklch(1 0 0 / 0.75)"
  # Dark ([data-theme="dark"]) — lime, lime-hover, lime-ink and mark are shared with light
  ground-dark: "oklch(0.18 0.008 60)"
  card-dark: "oklch(0.225 0.009 60)"
  well-dark: "oklch(0.26 0.01 60)"
  well-2-dark: "oklch(0.3 0.01 60)"
  line-dark: "oklch(0.29 0.01 60)"
  line-strong-dark: "oklch(0.36 0.012 60)"
  ink-dark: "oklch(0.95 0.008 75)"
  ink-2-dark: "oklch(0.78 0.012 70)"
  ink-3-dark: "oklch(0.68 0.012 70)"
  pos-dark: "oklch(0.8 0.15 138)"
  neg-dark: "oklch(0.72 0.15 30)"
  warn-dark: "oklch(0.8 0.14 70)"
  warn-text-dark: "oklch(0.82 0.12 70)"
  series-in-dark: "oklch(0.6 0.12 150)"
  series-cost-dark: "oklch(0.45 0.03 70)"
  series-profit-dark: "oklch(0.92 0.1 130)"
  ring-dark: "oklch(0.87 0.18 132)"
  toast-dark: "oklch(0.95 0.008 75)"
  toast-ink-dark: "oklch(0.255 0.012 55)"
  frost-dark: "oklch(0.24 0.009 60 / 0.68)"
  frost-ink-dark: "oklch(0.95 0.008 75 / 0.82)"
  frost-edge-dark: "oklch(1 0 0 / 0.09)"
typography:
  figure-hero:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, PingFang SC, Hiragino Sans GB, Microsoft YaHei, Noto Sans SC, sans-serif"
    fontSize: "2.875rem"
    fontWeight: 600
    lineHeight: "3.25rem"
    letterSpacing: "-0.025em"
    fontFeature: "tnum, lnum"
  figure:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, PingFang SC, Hiragino Sans GB, Microsoft YaHei, Noto Sans SC, sans-serif"
    fontSize: "2.125rem"
    fontWeight: 600
    lineHeight: "2.5rem"
    letterSpacing: "-0.025em"
    fontFeature: "tnum, lnum"
  headline:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, PingFang SC, Hiragino Sans GB, Microsoft YaHei, Noto Sans SC, sans-serif"
    fontSize: "1.75rem"
    fontWeight: 600
    lineHeight: "2.125rem"
    letterSpacing: "-0.02em"
  title-sheet:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, PingFang SC, Hiragino Sans GB, Microsoft YaHei, Noto Sans SC, sans-serif"
    fontSize: "1.25rem"
    fontWeight: 600
    lineHeight: "1.625rem"
    letterSpacing: "-0.01em"
  title:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, PingFang SC, Hiragino Sans GB, Microsoft YaHei, Noto Sans SC, sans-serif"
    fontSize: "1.0625rem"
    fontWeight: 600
    lineHeight: "1.5rem"
  body:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, PingFang SC, Hiragino Sans GB, Microsoft YaHei, Noto Sans SC, sans-serif"
    fontSize: "0.9375rem"
    fontWeight: 400
    lineHeight: "1.375rem"
  label:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, PingFang SC, Hiragino Sans GB, Microsoft YaHei, Noto Sans SC, sans-serif"
    fontSize: "0.8125rem"
    fontWeight: 500
    lineHeight: "1.125rem"
  caption:
    fontFamily: "system-ui, -apple-system, BlinkMacSystemFont, PingFang SC, Hiragino Sans GB, Microsoft YaHei, Noto Sans SC, sans-serif"
    fontSize: "0.75rem"
    fontWeight: 400
    lineHeight: "1rem"
rounded:
  field: "12px"
  card: "20px"
  sheet-phone: "24px"
  capsule: "9999px"
spacing:
  1: "4px"
  2: "8px"
  3: "12px"
  4: "16px"
  5: "20px"
  6: "24px"
  10: "40px"
  sidebar: "232px"
  content-max: "1200px"
components:
  button-primary:
    backgroundColor: "{colors.lime}"
    textColor: "{colors.lime-ink}"
    rounded: "{rounded.capsule}"
    padding: "0 18px"
    height: "40px"
    typography: "{typography.body}"
  button-primary-hover:
    backgroundColor: "{colors.lime-hover}"
  button-secondary:
    backgroundColor: "{colors.well}"
    textColor: "{colors.ink}"
    rounded: "{rounded.capsule}"
    padding: "0 18px"
    height: "40px"
  button-secondary-hover:
    backgroundColor: "{colors.well-2}"
  button-ghost:
    backgroundColor: "transparent"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.capsule}"
    padding: "0 18px"
    height: "40px"
  button-ghost-hover:
    backgroundColor: "{colors.well}"
    textColor: "{colors.ink}"
  button-danger:
    backgroundColor: "transparent"
    textColor: "{colors.neg}"
    rounded: "{rounded.capsule}"
    padding: "0 18px"
    height: "40px"
  button-danger-hover:
    backgroundColor: "{colors.neg-wash}"
  chip:
    backgroundColor: "{colors.well}"
    textColor: "{colors.ink-2}"
    rounded: "{rounded.capsule}"
    padding: "0 14px"
    height: "32px"
    typography: "{typography.label}"
  chip-on:
    backgroundColor: "{colors.lime}"
    textColor: "{colors.lime-ink}"
  badge-pos:
    backgroundColor: "{colors.pos-wash}"
    textColor: "{colors.pos}"
    rounded: "{rounded.capsule}"
    padding: "0 8px"
    height: "22px"
    typography: "{typography.caption}"
  badge-warn:
    backgroundColor: "{colors.warn-wash}"
    textColor: "{colors.warn-text}"
    rounded: "{rounded.capsule}"
    padding: "0 8px"
    height: "22px"
  input:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.field}"
    padding: "0 14px"
    height: "40px"
    typography: "{typography.body}"
  card:
    backgroundColor: "{colors.card}"
    rounded: "{rounded.card}"
    padding: "24px"
  segmented:
    backgroundColor: "{colors.well}"
    rounded: "{rounded.capsule}"
    padding: "4px"
  segmented-thumb:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
    rounded: "{rounded.capsule}"
  nav-item:
    textColor: "{colors.ink-2}"
    rounded: "{rounded.capsule}"
    padding: "0 16px"
    height: "40px"
  nav-item-active:
    backgroundColor: "{colors.card}"
    textColor: "{colors.ink}"
  toast:
    backgroundColor: "{colors.frost-ink}"
    textColor: "{colors.toast-ink}"
    rounded: "{rounded.capsule}"
    height: "48px"
---

# Design System: 账本 Bookkeeper v2

## Overview

**Creative North Star: "The Warm Pocket Ledger"**

The books read like a calm personal-finance app rather than an accounting tool. A warm, faintly tinted ground carries solid white cards with soft 20px corners, each lifted by one low warm shadow. Inside the cards, the money does the talking: big semibold figures in tabular numerals, a daily bar chart in green and sand, short bar lists for channels and upstream sites. Each figure links to its transactions. Density is generous but not airy. Every module fits in one card, and a screen shows few elements.

There is one saturated colour, a Wise-like lime with forest ink. It appears only where the owner acts (记一笔, the primary submit, the selected chip, a toggle that is on) or on the toast's undo. Money in and profit belong to one green family, from the lime through to forest. Costs sit in sand, red is kept for errors and losses, and amber marks what is waiting. Type is Apple's platform face (SF Pro with PingFang SC on the owner's Mac and iPhone) at a fixed rem scale.

The material is frosted glass for anything that floats above content (the phone tab bar, toasts, chart read-outs, the page behind a sheet). Content dissolves into a progressive blur at every scroll edge instead of being cut off. Motion is quick and exponential. The signature is the rolling figure: when a period changes or a write lands, every money figure rolls digit by digit to its new value.

**Key Characteristics:**
- Warm tinted ground, solid white 20px cards, one low warm shadow per card.
- One lime action colour; green for money in and profit, sand for costs, red only for errors and losses.
- Apple platform type, tabular numerals for every number, semibold hero figures with negative tracking.
- Capsule controls, 12px fields, 20px cards and sheets.
- Frosted glass with matte grain for anything floating; a progressive blur at scroll edges.
- Rolling figures and a self-drawing check after 记一笔.
- Light and dark themes share one token set; dark is a warm charcoal, not neutral grey.

## Colors

The palette is a warm cream-and-ink neutral range with one lime voice and a single green family for money, so action and income never compete.

### Primary
- **Wise Lime** (lime): the only saturated fill. It appears on the 记一笔 capsule, the primary submit button, a selected chip, a toggle that is on, the toast's undo button and the selection highlight (as lime-wash). Hover darkens it slightly (lime-hover).
- **Forest Ink** (lime-ink): the text and icon colour on lime. Never put lime under ink or white text.

### Secondary
- **Ledger Green** (pos): marks money in. Used for the + flow amounts, a positive delta, the icon chip for income (on pos-wash), the input caret, and the focus ring in light theme. In dark theme the focus ring switches to lime.
- **Signet Green** (mark): fills the app mark's rounded square only.

### Tertiary
- **Loss Red** (neg): errors, required-field asterisks, danger actions, and a negative profit figure. ErrorNote uses it on neg-wash.
- **Waiting Amber** (warn, with warn-text and warn-wash): the import backlog count, the 待处理 dots and the waiting pill.

### Chart series
- **Revenue Green** (series-in): revenue bars and the income bar list.
- **Cost Sand** (series-cost): cost bars (drawn below zero) and the upstream-purchase bar list.
- **Profit Forest** (series-profit): the profit line drawn over the bars. In dark theme it lightens to a pale lime-green.

### Neutral
- **Warm Ground** (ground): the page, and the sidebar, which sits on the ground with no panel of its own.
- **Card White** (card): every card, sheet and field background, plus the selected nav pill and the segmented-control thumb.
- **Well** / **Well Deep** (well, well-2): quiet fills for secondary buttons, unselected chips, segmented tracks, icon chips, bar-list tracks, hover rows and skeletons.
- **Hairline** / **Strong Hairline** (line, line-strong): dividers and chart gridlines. line-strong is used for field borders, the chart zero line, the sheet grabber and scrollbars.
- **Warm Ink** (ink, ink-2, ink-3): primary text, then secondary labels, then tertiary captions and axis text. All are warm brown-blacks, never neutral grey.
- **Scrim** (scrim): the tint behind sheets and dialogs. The blur is applied together with it.

### Named Rules
**The One Lime Rule.** Lime marks where the owner acts or what is currently selected, and nothing else. It is never used for decoration, headings, chart series or status.

**The One Green Family Rule.** Action, income and profit all use one green family, running from lime through ledger green to forest. Costs are sand, not red. Red means an error or a loss.

## Typography

**Display Font:** the platform UI face, SF Pro + PingFang SC on Apple (system-ui stack; falls back to Hiragino Sans GB, Microsoft YaHei, Noto Sans SC)
**Body Font:** the same face
**Label/Mono Font:** none; numbers use the same face with tabular lining figures

**Character:** Apple-native and quiet. The figures carry the hierarchy, with semibold weights and slight negative tracking on money; everything else is regular or medium.

### Hierarchy
- **Figure hero** (600, 46px / 52px, −0.025em, tabular): the period's profit, the base-currency balance, and the amount field in 记一笔.
- **Figure** (600, 34px / 40px, −0.025em, tabular): secondary headline figures.
- **Headline** (600, 28px / 34px, −0.02em): page titles (概览, 交易 …), one per page.
- **Title, sheet** (600, 20px / 26px, −0.01em): sheet and dialog titles.
- **Title** (600, 17px / 24px): card titles and the wordmark.
- **Body** (400–500, 15px / 22px): rows, nav items, fields and buttons.
- **Label** (500, 13px / 18px): field labels, chips, legends, card actions and small buttons.
- **Caption** (400–600, 12px / 16px): axis ticks, badges, counts and tab-bar labels.

### Named Rules
**The Tabular Rule.** Every amount, count, date and number is set in tabular lining figures (`num`), so columns and rolling digits line up. Headline money uses `figure`: semibold, −0.025em.

**The True Minus Rule.** Outflows use a true minus (−), never a hyphen. Income carries an explicit + and reads green, while money out reads in ink.

## Layout

The desktop layout is two columns: a 232px sidebar on the ground and a main column capped at 1200px, with 40px side padding. The sidebar holds the wordmark, the 44px lime 记一笔 capsule with its N shortcut, the five modules as 40px pills, and the theme switch and account at the foot. Pages open with a header (title on the left, controls such as the period segmented switch on the right, 24px below). Content sits on a 12-column grid with 20px gaps, and cards pair 7/12 with 5/12.

Below 1024px the layout becomes one column with 16px (phone) or 24px side padding. A fixed frosted tab bar runs across the bottom (概览 / 交易 / ＋ / 统计 / 更多), with a raised 56px lime ＋ in the middle. The main column reserves 112px plus the safe-area inset beneath it. Breakpoints are Tailwind's sm 640px and lg 1024px.

Spacing follows a 4px rhythm. The common steps are 4, 8, 12, 16, 20, 24 and 40px.

### Named Rules
**The One Inset Rule.** Card content is inset 24px (20px on phone). Card headers and rows align to that inset. Hover rows bleed out by 12px on each side (−mx-3 px-3) so their hover fill extends past the inset while the text stays on it.

**The No-Overflow Grid Rule.** A grid with no explicit columns is a single `minmax(0, 1fr)` column. Long text truncates instead of pushing the page sideways.

## Elevation & Depth

The model is a hybrid of two materials. Solid surfaces (cards, sheets) are white and lifted by soft warm shadows. Anything that floats over scrolling content is frosted glass. The page itself is flat ground. In dark theme the shadows turn near-black and the cards step up in lightness from the ground.

### Shadow Vocabulary
- **Card** (`0 1px 2px oklch(0.4 0.03 60 / 0.06), 0 8px 24px -12px oklch(0.4 0.04 60 / 0.16)`): every card at rest. It is the only shadow a card gets.
- **Lift** (`0 1px 2px oklch(0.4 0.03 60 / 0.08), 0 2px 8px -2px oklch(0.4 0.04 60 / 0.12)`): small raised pieces such as the active nav pill, the segmented thumb, the toggle knob and the frost tab bar.
- **Pop** (`0 4px 12px -4px oklch(0.3 0.03 60 / 0.12), 0 28px 64px -24px oklch(0.3 0.04 60 / 0.38)`): sheets, the raised phone ＋ and ink toasts.

### Frosted glass
- **Frost** (light material): frost fill, `backdrop-filter: blur(22px) saturate(1.6)`, an 80px tile of matte grain (`/grain.png`, a procedurally generated speckle that carries its provenance in its PNG text chunk), a 1px inset top light (frost-edge) and the lift shadow. It is used for the phone tab bar and chart read-outs.
- **Frost ink** (dark material): frost-ink fill with the same blur and grain, a faint inset top light and the pop shadow. It is used for toasts.
- **Sheet backdrop:** scrim plus `blur(10px) saturate(1.25)`, which fades in over 360ms.
- **Progressive blur:** five stacked backdrop layers blur at 1, 2, 4, 8 and 16px. Each is masked to a shorter band so the blur deepens toward the edge, with a ground tint on top (card tint inside sheets). It sits at the page top (shown only once scrolled), above the phone tab bar, and at both ends of a sheet body.
- With `prefers-reduced-transparency`, frost becomes solid card or toast fill and progressive blur is removed.

### Named Rules
**The Solid Cards Rule.** Cards and sheets stay solid. Glass is only for surfaces that float over moving content.

**The Dissolving Edge Rule.** Scrolling content never hits a hard cut at a fixed edge; it dissolves into the progressive blur.

## Shapes

There are three radii and no others. Every control is a full capsule: buttons, chips, segmented controls, icon buttons, nav pills, badges, toggles, the tab-bar ＋ and toasts. Fields, inner tiles, hover rows and chart read-outs use 12px. Cards and the desktop sheet use 20px. A phone bottom sheet uses 24px on its top corners. Circles are reserved for icon chips (type glyphs, currency marks, the avatar). The app mark is a rounded square (10/32) holding three rounded bars. Borders appear only on fields (line-strong) and on the sheet footer divider.

## Components

### Buttons
Soft, tactile capsules that press down slightly.
- **Shape:** full capsule. Heights are 32 / 40 / 48px (sm / md / lg), with 14 / 18 / 24px horizontal padding.
- **Primary:** lime fill, forest-ink semibold text. At most one per view.
- **Secondary:** well fill with ink text. Hover moves to well-2.
- **Ghost:** transparent with ink-2 text. Hover adds a well fill and ink text.
- **Danger:** transparent with red text. Hover adds a neg-wash fill.
- **States:** 150ms colour transitions, scale(0.97) when pressed, 45% opacity when disabled, and a spinner replacing the icon while loading. An optional kbd hint sits inside the capsule.
- **Submit in 记一笔:** after a successful write, the label gives way to a check that draws itself (420ms, power3.out).

### Chips
- **Style:** 32px capsules with label type. Unselected chips are well fill with ink-2 text. Selected chips are lime with forest-ink semibold text.
- **Use:** filters, and the transaction-type capsules in 记一笔 (36px there).

### Segmented control
A well track with a 4px inset. A card-white thumb with the lift shadow slides under the selected option (300ms, expo ease-out). It is used for period switches (本月 / 上月 / 近 30 天 / 今年) and the theme switch.

### Cards / Containers
- **Corner Style:** 20px.
- **Background:** card white.
- **Shadow Strategy:** the card shadow only (see Elevation).
- **Border:** none.
- **Internal Padding:** 24px (20px on phone). The title row (17px semibold) has an optional right-aligned action, either a muted caption or a "查看全部 ›" link.

### Inputs / Fields
- **Style:** card fill, 1px line-strong border, 12px radius, 40px tall, 14px side padding. Labels sit above in 13px medium ink-2 and notes sit below in 13px ink-3.
- **Focus:** the border turns ledger green, with a 3px lime-wash halo.
- **Error:** the note turns red. Missing fields only turn red after the owner tries to save, never while typing.

### Navigation
- **Desktop sidebar:** 40px capsule items with 20px Phosphor icons. Active items are a card-white pill with the lift shadow, semibold ink and a filled icon. Inactive items are medium ink-2, with a well fill on hover. The 导入 backlog count is an amber capsule badge.
- **Phone tab bar:** a frosted bar with 56px-tall tabs, 24px icons and 12px labels. The active tab is semibold ink with a filled icon; inactive tabs are ink-3. The centre ＋ is a raised lime circle with the pop shadow.

### Toasts
A frost-ink capsule, at least 48px tall, centred above the bottom edge (above the tab bar on phone). It shows a check (toast-accent) or a warning icon plus the message, and may carry a lime 撤销 capsule. It rises in over 320ms, stays 3.2s (6.5s when it has undo), and at most two show at once. Undo replaces confirmation dialogs.

### Sheets
A native `<dialog>`. On desktop it is a 20px-radius panel inset 12px from the top, right and bottom. On phone it is a bottom sheet up to 94dvh tall with a 24px top radius and a grabber. The header has a 20px title and a round close button on a well fill. The body scrolls between progressive-blur edges, and the action footer sits on a hairline. GSAP moves the panel, and CSS fades and frosts the backdrop.

### Charts
- **Flow chart:** daily revenue bars (series-in) above zero and cost bars (series-cost) below it, with fully rounded bar ends and a 2px profit line (series-profit) on top. Gridlines are dashed hairlines with right-aligned tabular captions. Hover shows a 12px well column and a frosted read-out, and a click drills down to that day's transactions. Below the chart sits a legend of dots and a line swatch. A screen-reader table mirrors the data.
- **Bar list:** a name and a rolling amount, then an 8px capsule track (well) with a fill in series-in or series-cost that grows from the left over 700ms, then a muted count on the right. Each row links to its transactions.

### Rolling Figure (signature)
Each digit is a vertical strip from 0 to 9 clipped to 1.12em. When the value changes, the strips roll to the new digit (620ms, expo.out, 30ms stagger from the leading digit). On first arrival they roll up from 0 (900ms). Columns are keyed from the right, so the cents stay put and new leading digits slide in. Screen readers get the plain text, and reduced motion sets the value without animating.

### Icon chips
A 40px circle (32 or 48px also used) leads every transaction row, holding a Phosphor glyph for the business type. Income uses pos-wash with a bold pos glyph; everything else uses well with an ink-2 glyph. Currency marks use the same circle with the currency symbol.

## Do's and Don'ts

### Do:
- **Do** keep lime for the primary action, the current selection and undo only, always with forest-ink text.
- **Do** set every number in tabular figures and every headline amount in semibold with −0.025em tracking, and roll money figures when they change.
- **Do** use capsules for controls, 12px for fields and inner tiles, and 20px for cards and sheets.
- **Do** inset card content 24px (20px on phone) and let hover rows bleed out 12px past it.
- **Do** use frost (blur 22px, saturate 1.6, grain, hairline top light) for anything that floats over content, and the progressive blur at every scroll edge.
- **Do** confirm writes with a toast that offers 撤销, not with a confirmation dialog.
- **Do** honour `prefers-reduced-motion` and `prefers-reduced-transparency` in every new animation and glass surface.
- **Do** keep the warm hue (55–75) in every neutral, in both themes.

### Don't:
- **Don't** put lime on headings, chart series, decoration or status.
- **Don't** render costs in red. Costs are sand; red is for errors and losses only.
- **Don't** make cards or sheets translucent, and don't add borders to cards.
- **Don't** stack more than one shadow role on an element, or give a card anything other than the card shadow.
- **Don't** use neutral or cool greys for ink, ground or dividers.
- **Don't** introduce radii outside 12 / 20 / 24px and the capsule.
- **Don't** build grey KPI-tile grids, journal-style ledgers or dense accounting tables.
