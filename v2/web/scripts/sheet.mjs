// Contact sheet: node scripts/sheet.mjs out.png img1 img2 ... (2 columns)
import { chromium } from "playwright-core";
import { readFileSync } from "node:fs";
const [, , out, ...imgs] = process.argv;
const html = `<body style="margin:0;display:grid;grid-template-columns:1fr 1fr;gap:6px;background:#888">${imgs
  .map((p) => `<div style="position:relative"><img style="width:100%;display:block" src="data:image/png;base64,${readFileSync(p).toString("base64")}"><span style="position:absolute;left:4px;top:4px;background:#000;color:#fff;font:12px sans-serif;padding:2px 4px">${p.split("/").pop()}</span></div>`)
  .join("")}</body>`;
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await browser.newPage({ viewport: { width: 2000, height: 1000 } });
await page.setContent(html);
await page.screenshot({ path: out, fullPage: true });
await browser.close();
