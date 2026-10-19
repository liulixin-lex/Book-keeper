// End-to-end smoke of the main flows. It writes, so by default it never touches the books you look at:
//   node scripts/e2e.mjs                     copies the dev database (bookkeeper_web, or BK_E2E_FROM) into a throwaway
//                                            bookkeeper_e2e, builds the app and serves it from its own API on :8011
//                                            (the production path, CSP included), and drops the copy when it ends
//   BK_WEB=http://… node scripts/e2e.mjs     runs against a server that is already up; its books get the test writes
//                                            (that server needs BK_MASTER_KEY for the AI 模型 step)
import { execFileSync, spawn } from "node:child_process";
import { mkdtempSync, openSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright-core";

const base = process.env.BK_WEB ?? (await sandbox());
const browser = await chromium.launch({ channel: "chrome", headless: true });
const page = await (await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: "zh-CN" })).newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(`pageerror ${e.message}`));
page.on("console", (m) => m.type() === "error" && m.text().includes("Content Security Policy") && errors.push(`csp ${m.text()}`));
page.on("response", (r) => r.status() >= 500 && errors.push(`http ${r.status()} ${r.url()}`));
const step = (name) => console.log("·", name);
const toast = async (text) => page.getByRole("status").filter({ hasText: text }).first().waitFor({ timeout: 8000 });
const api = (path) => page.evaluate(async (p) => (await (await fetch(`/api/v1/books/${localStorage.getItem("bk.book")}${p}`)).json()).data, path);
const expect = (ok, message) => {
  if (!ok) throw new Error(message);
};

await page.goto(`${base}/login`);
await page.fill('input[type="email"]', "dev@local.test");
await page.fill('input[type="password"]', "dev-password-2026");
await page.click('button[type="submit"]');
await page.waitForURL("**/overview");

async function record({ type, amount, channel, counterparty, category, currency, orderNo }) {
  await page.keyboard.press("n");
  const sheet = page.locator("dialog[open]");
  await sheet.getByRole("radio", { name: type, exact: true }).click();
  await sheet.locator("#entry-hero-amount").fill(amount);
  if (currency) await sheet.getByLabel("币种", { exact: true }).selectOption(currency);
  if (counterparty) await sheet.getByLabel("往来方").fill(counterparty);
  if (channel) await sheet.getByRole("button", { name: channel, exact: true }).click();
  if (category) await sheet.getByLabel("收支分类").selectOption(category);
  await sheet.getByRole("button", { name: /^更多：/ }).click();
  const tried = page.waitForResponse((r) => r.request().method() === "POST" && r.url().includes("dry_run=true") && r.request().postData()?.includes(orderNo));
  await sheet.getByLabel("订单号").fill(orderNo);
  expect((await tried).status() === 200, `dry run for ${orderNo} failed`);
  await sheet.getByRole("button", { name: /^记一笔/ }).click();
  await toast("已记一笔");
  const [t] = await api(`/transactions?q=${orderNo}&limit=1`);
  expect(t, `no transaction with order ${orderNo}`);
  return t;
}

step("记一笔 (sale on 链动) with the live fee split, then undo from the toast");
await page.goto(`${base}/transactions`);
await page.waitForLoadState("networkidle");
const stamp = Date.now().toString(36).toUpperCase();
const sale = await record({ type: "销售", amount: "128", channel: "链动", orderNo: `LDE2E${stamp}` });
expect(sale.status === "posted", `sale ${sale.number} not posted`);
await page.getByRole("status").getByRole("button", { name: "撤销" }).click();
await toast(`已撤销 ${sale.number}`);
const undone = await api(`/transactions/${sale.number}`);
expect(undone.status === "reversed", `undo left ${sale.number} ${undone.status}`);
step(`recorded and undid ${sale.number}`);

step("记一笔 (expense), edit the amount in place, delete, restore");
const expense = await record({ type: "费用", amount: "12", currency: "USD", counterparty: "Vultr", category: "5401.04", orderNo: `VE2E${stamp}` });
await page.goto(`${base}/transactions?tx=${expense.number}`);
const sheet = page.locator("dialog[open]");
await sheet.getByRole("button", { name: "修改", exact: true }).click();
const tried = page.waitForResponse((r) => r.request().method() === "PATCH" && r.url().includes("dry_run=true"));
await sheet.locator("#entry-hero-amount").fill("15");
expect((await tried).status() === 200, "edit dry run failed");
await sheet.getByText("折合").first().waitFor();
await sheet.getByRole("button", { name: /^保存修改/ }).click();
await toast(`已修改 ${expense.number}`);
const edited = await api(`/transactions/${expense.number}`);
expect(edited.amount.minor === 1500 && edited.number === expense.number, `edit gave ${JSON.stringify(edited.amount)}`);
expect(edited.entries.length === 3, `edit should leave 3 entries, got ${edited.entries.length}`);

await sheet.getByRole("button", { name: "修改摘要" }).click();
await sheet.getByLabel("摘要", { exact: true }).fill("Vultr 东京节点");
await page.keyboard.press("Enter");
await toast("已更新摘要");

await sheet.getByRole("button", { name: "删除", exact: true }).click();
await toast(`已删除 ${expense.number}`);
expect((await api(`/transactions/${expense.number}`)).status === "reversed", "delete did not reverse");
await page.goto(`${base}/transactions?deleted=1&tx=${expense.number}`);
await page.locator("dialog[open]").getByRole("button", { name: "恢复", exact: true }).click();
await toast(`已恢复 ${expense.number}`);
const restored = await api(`/transactions/${expense.number}`);
expect(restored.status === "posted" && restored.amount.minor === 1500, "restore did not bring back the edited amount");
step(`edited, deleted and restored ${expense.number}`);

step("导入: upload a statement, complete what the rules left, finish, then undo from the toast");
const n = Date.now() % 100000000;
const csv = [
  "微信支付账单明细,,,,,,,,,,",
  "微信昵称：[测试],,,,,,,,,,",
  "起始时间：[2026-10-01 00:00:00] 终止时间：[2026-10-31 23:59:59],,,,,,,,,,",
  "共2笔记录,,,,,,,,,,",
  "收入：0笔 0.00元,,,,,,,,,,",
  "支出：2笔 92.00元,,,,,,,,,,",
  "----------------------微信支付账单明细列表--------------------,,,,,,,,,,",
  "交易时间,交易类型,交易对方,商品,收/支,金额(元),支付方式,当前状态,交易单号,商户单号,备注",
  `2026-10-05 12:00:00,商户消费,Vultr,服务器 ${stamp},支出,¥80.00,零钱,支付成功,42${n}1\t,M${n}\t,/`,
  `2026-10-06 09:30:00,扫二维码付款,某推广,推广 ${stamp},支出,¥12.00,零钱,支付成功,42${n}2\t,/,/`,
].join("\n");
await page.goto(`${base}/imports`);
await page.waitForLoadState("networkidle");
await page.getByRole("radio", { name: "微信账单" }).click();
await page.setInputFiles('input[type="file"]', { name: `wechat-e2e-${stamp}.csv`, mimeType: "text/csv", buffer: Buffer.from(csv) });
await page.getByRole("button", { name: "解析账单" }).click();
await page.waitForURL(/\/imports\/imb_/);
await page.getByRole("button", { name: "补全这条记录" }).first().waitFor();
for (let i = 0; i < 4; i++) {
  const open = page.getByRole("button", { name: "补全这条记录" });
  const before = await open.count();
  if (!before) break;
  await open.first().click();
  await page.getByLabel("收支分类").first().selectOption({ index: 1 });
  const saved = page.waitForResponse((r) => r.request().method() === "PATCH" && r.url().includes("/source-records/"));
  await page.getByRole("button", { name: "保存", exact: true }).click();
  expect((await saved).status() === 200, "classify failed");
  await page.waitForFunction((count) => document.querySelectorAll('button[aria-label="补全这条记录"]').length < count, before);
}
await page.getByRole("button", { name: /^完成导入/ }).click();
await toast("已入账");
await page.getByRole("status").getByRole("button", { name: "撤销" }).click();
await toast("已撤销这次导入");
step("uploaded, completed, finished and undid an import");

step("导入: two copies of a printed redeem page in one upload read once");
if (!(await api("/import-sources")).some((s) => s.kind === "redeem_page" && s.is_active)) {
  const made = await page.evaluate(async () => {
    const csrf = (await (await fetch("/api/v1/auth/me")).json()).data.csrf_token;
    const body = { code: "e2e_redeem", name: "兑换码页面", kind: "redeem_page", config: { defaults: { in: { type: "credit_purchase" } } } };
    const r = await fetch(`/api/v1/books/${localStorage.getItem("bk.book")}/import-sources`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf, "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify(body),
    });
    return r.status;
  });
  expect(made === 201, `creating the redeem source gave ${made}`);
}
await page.goto(`${base}/imports`);
await page.waitForLoadState("networkidle");
await page.getByRole("radio", { name: "兑换码页面" }).click();
const pdf = (await import("node:fs")).readFileSync(new URL("../../tests/fixtures/redeem_page.pdf", import.meta.url));
await page.setInputFiles('input[type="file"]', [
  { name: "a.pdf", mimeType: "application/pdf", buffer: pdf },
  { name: "b.pdf", mimeType: "application/pdf", buffer: pdf },
]);
await page.getByText("已选 2 个文件").waitFor();
await page.getByRole("button", { name: "解析账单" }).click();
await page.waitForURL(/\/imports\/imb_/);
const pdfBatch = await api(`/import-batches/${page.url().split("/").pop()}`);
expect(pdfBatch.summary.records === 8 && pdfBatch.summary.by_status.duplicate === 4, `redeem upload gave ${JSON.stringify(pdfBatch.summary.by_status)}`);
await page.getByRole("radio", { name: /待补全/ }).waitFor();
step("read 4 top-ups, 4 duplicates");

step("设置 → AI 模型: add a provider, route 识别 to it, the key never comes back, delete it");
await page.goto(`${base}/settings/ai-models`);
await page.waitForLoadState("networkidle");
await page.getByRole("button", { name: "添加", exact: true }).click();
const form = page.locator("dialog[open]");
const relay = `E2E 中转 ${stamp}`;
await form.getByLabel(/^名称/).fill(relay);
await form.getByLabel(/^Base URL/).fill("https://relay.example.com/v1");
await form.getByLabel(/^API 密钥/).fill("sk-e2e-0000000000000000wxyz");
await form.getByLabel(/^模型/).fill("model-a, model-b");
await form.getByRole("button", { name: "添加", exact: true }).click();
await toast(`已添加 ${relay}`);
await page.getByLabel("给识别添加提供商").selectOption({ label: relay });
await page.getByRole("button", { name: "保存分配" }).click();
await toast("已保存任务分配");
const listed = JSON.stringify(await api("/ai/providers"));
expect(listed.includes("••••wxyz") && !listed.includes("sk-e2e"), "the provider list leaks the key or lacks its hint");
expect(
  (await api("/ai/routes")).extract.some((r) => r.provider_name === relay && r.model === "model-a"),
  "识别 is not routed to the new provider",
);
await page.getByRole("button", { name: new RegExp(`^${relay}`) }).click();
await page.locator("dialog[open]").getByRole("button", { name: "删除" }).click();
await toast(`已删除 ${relay}`);
expect(!(await api("/ai/routes")).extract.some((r) => r.provider_name === relay), "the deleted provider is still routed");
step("added, routed and deleted a provider");

step("设置 → AI 接入: a 管理员只读 token reads management info and cannot write");
await page.goto(`${base}/settings/ai`);
await page.waitForLoadState("networkidle");
await page.getByRole("button", { name: "新令牌" }).click();
const tokenSheet = page.locator("dialog[open]");
await tokenSheet.getByLabel(/^名称/).fill(`E2E 只读 ${stamp}`);
await tokenSheet.getByRole("radio", { name: /^管理员只读/ }).click();
await tokenSheet.getByRole("button", { name: "生成令牌" }).click();
const secret = (await page.locator("dialog[open] code").textContent())?.trim() ?? "";
expect(secret.startsWith("bk_pat_"), "the new token was not shown");
const probe = await page.evaluate(async (t) => {
  const b = `/api/v1/books/${localStorage.getItem("bk.book")}`;
  const h = { Authorization: `Bearer ${t}` };
  const w = { ...h, "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() };
  return [(await fetch(`${b}/members`, { headers: h, credentials: "omit" })).status, (await fetch(`${b}/transactions`, { method: "POST", headers: w, body: "{}", credentials: "omit" })).status];
}, secret);
expect(probe[0] === 200 && probe[1] === 403, `admin_read token gave members ${probe[0]}, write ${probe[1]}`);
const made = (await api("/tokens")).find((t) => t.name === `E2E 只读 ${stamp}`);
expect(made?.tier === "admin_read", "the token list lacks the new tier");
const revoked = await page.evaluate(async (id) => {
  const csrf = (await (await fetch("/api/v1/auth/me")).json()).data.csrf_token;
  const r = await fetch(`/api/v1/books/${localStorage.getItem("bk.book")}/tokens/${id}:revoke`, {
    method: "POST",
    headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf, "Idempotency-Key": crypto.randomUUID() },
    body: "{}",
  });
  return r.status;
}, made.id);
expect(revoked === 200, `revoking gave ${revoked}`);
step("made, checked and revoked an admin_read token");

step("AI 助手: the page opens and says whether it is set up");
await page.goto(`${base}/ai`);
await page.waitForLoadState("networkidle");
const agentReady = (await api("/ai/status")).agent;
await (agentReady ? page.getByLabel("要做什么") : page.getByText("AI 助手还没配置")).waitFor();
step(agentReady ? "composer shown" : "not set up yet, pointing to 设置 → AI 模型");

if (errors.length) {
  console.error(errors.join("\n"));
  process.exitCode = 1;
} else console.log("ok");
await browser.close();

/** A private copy of the dev books behind the production build; torn down on exit, failures included. */
async function sandbox() {
  const v2 = fileURLToPath(new URL("../../", import.meta.url));
  const url = "http://127.0.0.1:8011";
  const db = "bookkeeper_e2e";
  const env = { ...process.env, PGHOST: join(v2, ".local"), PGPORT: "55432", PGUSER: "postgres" };
  const sh = (cmd) => execFileSync("sh", ["-c", cmd], { env, stdio: ["ignore", "ignore", "inherit"] });
  const up = () =>
    fetch(`${url}/readyz`).then(
      (r) => r.ok,
      () => false,
    );
  if (await up()) throw new Error(`${url} is already taken; stop that server or set BK_WEB`);

  console.log("· sandbox: copying the dev books and building the app");
  sh(`dropdb --if-exists --force ${db} && createdb ${db} && pg_dump -Fc ${process.env.BK_E2E_FROM ?? "bookkeeper_web"} | pg_restore --no-owner -d ${db}`);
  const dist = mkdtempSync(join(tmpdir(), "bk-e2e-web-"));
  sh(`cd "${join(v2, "web")}" && npx vite build --outDir "${dist}" --emptyOutDir --logLevel warn`);

  const logPath = join(tmpdir(), "bk-e2e-api.log");
  const log = openSync(logPath, "w");
  const api = spawn("uv", ["run", "bookkeeper", "serve", "--port", "8011"], {
    cwd: v2,
    detached: true,
    stdio: ["ignore", log, log],
    env: {
      ...process.env,
      BK_DATABASE_URL: `postgresql+psycopg://postgres@/${db}?host=${join(v2, ".local")}&port=55432`,
      BK_WEB_DIR: dist,
      BK_PUBLIC_URL: url,
      BK_MASTER_KEY: "e2e-master-key-not-a-secret-0000000000",
    },
  });
  api.unref(); // the exit handler below stops it; a live child must not keep the run from ending
  process.on("SIGINT", () => process.exit(130));
  process.on("exit", () => {
    try {
      process.kill(-api.pid, "SIGTERM");
    } catch {
      // already gone
    }
    sh(`dropdb --if-exists --force ${db}`);
  });
  for (let i = 0; i < 120; i++) {
    if (await up()) return url;
    await new Promise((r) => setTimeout(r, 250));
  }
  throw new Error(`the sandbox API did not come up; see ${logPath}`);
}
