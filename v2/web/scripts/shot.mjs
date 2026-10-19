// Screenshot helper for design review: node scripts/shot.mjs <path> <out.png> [width] [height] [theme] [fullPage]
import { chromium } from "playwright-core";

const [, , path = "/overview", out = "/tmp/shot.png", width = "1440", height = "900", theme = "light", full = "0"] = process.argv;
const base = process.env.BK_WEB ?? "http://127.0.0.1:5173";
const browser = await chromium.launch({ channel: "chrome", headless: true });
const context = await browser.newContext({ viewport: { width: +width, height: +height }, deviceScaleFactor: 2, colorScheme: theme === "dark" ? "dark" : "light", reducedMotion: "reduce" });
const page = await context.newPage();
page.on("pageerror", (e) => console.error("pageerror:", e.message));
page.on("response", (r) => r.status() >= 400 && console.error("http", r.status(), r.url()));
await page.goto(`${base}/login`);
await page.evaluate((t) => localStorage.setItem("bk.theme", t), theme);
await page.fill('input[type="email"]', process.env.BK_EMAIL ?? "dev@local.test");
await page.fill('input[type="password"]', process.env.BK_PASSWORD ?? "dev-password-2026");
await page.click('button[type="submit"]');
await page.waitForURL("**/overview");
if (path !== "/overview") await page.goto(`${base}${path}`);
await page.waitForLoadState("networkidle");
await page.waitForTimeout(600);
await page.screenshot({ path: out, fullPage: full === "1" });
await browser.close();
console.log("saved", out);
