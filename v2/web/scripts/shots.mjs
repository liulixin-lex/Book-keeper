// Batch screenshots for review: node scripts/shots.mjs <outdir> <width> <height> <theme> path...
import { chromium } from "playwright-core";

const [, , outDir = "/tmp/shots", width = "1440", height = "900", theme = "light", ...paths] = process.argv;
const base = process.env.BK_WEB ?? "http://127.0.0.1:5173";
const browser = await chromium.launch({ channel: "chrome", headless: true });
const context = await browser.newContext({
  viewport: { width: +width, height: +height },
  deviceScaleFactor: 2,
  colorScheme: theme === "dark" ? "dark" : "light",
  reducedMotion: "reduce",
  locale: "zh-CN",
});
const page = await context.newPage();
page.on("pageerror", (e) => console.error("pageerror:", e.message));
page.on("response", (r) => r.status() >= 400 && console.error("http", r.status(), r.url().replace(base, "")));
await page.goto(`${base}/login`);
await page.evaluate((t) => localStorage.setItem("bk.theme", t), theme);
await page.fill('input[type="email"]', "dev@local.test");
await page.fill('input[type="password"]', "dev-password-2026");
await page.click('button[type="submit"]');
await page.waitForURL("**/overview");
for (const p of paths) {
  await page.goto(`${base}${p}`);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(500);
  const name = p.replace(/^\//, "").replace(/[/?=&]/g, "_") || "root";
  await page.screenshot({ path: `${outDir}/${name}-${width}-${theme}.png` });
}
await browser.close();
