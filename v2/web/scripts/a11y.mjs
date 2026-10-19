// Accessibility scan (axe-core) of the main screens: node scripts/a11y.mjs [theme] [extra path…]
import { chromium } from "playwright-core";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const axe = readFileSync(require.resolve("axe-core/axe.min.js"), "utf8");
const base = process.env.BK_WEB ?? "http://127.0.0.1:5173";
const theme = process.argv[2] ?? "light";
const paths = [
  "/overview",
  "/transactions",
  "/transactions?tx=T2026-000765",
  "/stats",
  "/stats?tab=channels",
  "/stats?tab=sites",
  "/imports",
  "/ai",
  "/settings/counterparties",
  "/settings/fee-rules",
  "/settings/rules",
  "/settings/sources",
  "/settings/ai",
  "/settings/ai-models",
  "/settings/activity",
  "/settings/data",
  "/more",
  ...process.argv.slice(3),
];
const browser = await chromium.launch({ channel: "chrome", headless: true });
// bypassCSP: axe is injected inline, which the production build's CSP (rightly) refuses
const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "zh-CN", reducedMotion: "reduce", bypassCSP: true })).newPage();
await page.goto(`${base}/login`);
await page.evaluate((t) => localStorage.setItem("bk.theme", t), theme);
const loginIssues = await (async () => {
  await page.addScriptTag({ content: axe });
  return page.evaluate(async () => (await window.axe.run(document, { resultTypes: ["violations"] })).violations);
})();
const report = { "/login": loginIssues };
await page.fill('input[type="email"]', "dev@local.test");
await page.fill('input[type="password"]', "dev-password-2026");
await page.click('button[type="submit"]');
await page.waitForURL("**/overview");
for (const p of paths) {
  await page.goto(`${base}${p}`);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(300);
  await page.addScriptTag({ content: axe });
  report[p] = await page.evaluate(async () => (await window.axe.run(document, { resultTypes: ["violations"] })).violations);
}
// The 记一笔 sheet, open over 概览.
await page.goto(`${base}/overview`);
await page.waitForLoadState("networkidle");
await page.keyboard.press("n");
await page.locator("#entry-hero-amount").fill("100");
await page.waitForTimeout(800);
await page.addScriptTag({ content: axe });
report["记一笔"] = await page.evaluate(async () => (await window.axe.run(document, { resultTypes: ["violations"] })).violations);
for (const [p, v] of Object.entries(report)) {
  for (const x of v)
    console.log(
      `${p}  [${x.impact}] ${x.id}: ${x.help} (${x.nodes.length}) e.g. ${x.nodes[0]?.target.join(" ")}${x.nodes[0]?.any?.[0]?.message ? " :: " + x.nodes[0].any[0].message.slice(0, 140) : ""}`,
    );
}
console.log(
  "total",
  Object.values(report).reduce((n, v) => n + v.length, 0),
);
await browser.close();
