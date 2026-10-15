// Run against the local stub: npm ci && npm run test:ui -- http://127.0.0.1:8090
// Uses installed Google Chrome; set CHROME for a different local executable.
import assert from "node:assert/strict";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { chromium } from "playwright-core";
const baseURL = process.argv[2] || "http://127.0.0.1:8090";
const output = path.resolve("docs/screenshots");
await mkdir(output, { recursive: true });
const browser = await chromium.launch({
  executablePath:
    process.env.CHROME ||
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
  headless: true,
});
const context = await browser.newContext({
  viewport: { width: 390, height: 844 },
  locale: "ja-JP",
  timezoneId: "Asia/Tokyo",
});
const page = await context.newPage();
// The deployed URL runs real Google Search, so a recommendation takes 1-3 minutes.
if (baseURL.includes("run.app")) page.setDefaultTimeout(240_000);
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));
const shot = (name) =>
  page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true });
const visible = (selector) =>
  page.locator(selector).waitFor({ state: "visible" });
const settled = () =>
  page.locator("html:not(.flow-moving)").waitFor({ state: "attached" });
const noOverflow = async () =>
  assert(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
    "page must not overflow horizontally",
  );
try {
  await page.goto(baseURL);
  await visible("#btn-preview");
  await noOverflow();
  await shot("01_mobile_home");
  await page.click("#btn-preview");
  await visible("#section-candidates:not(.hidden)");
  await settled();
  assert.match(
    await page.locator("#research-mode-banner").innerText(),
    /比較サンプル/,
  );
  assert(await page.locator(".featured-product img").count());
  await noOverflow();
  await shot("02_mobile_comparison");
  await page.click("#btn-priority-light");
  await visible("#rank-change-message:not(.hidden)");
  await page.locator(".featured-product .routine-button").click();
  await visible("#section-routines:not(.hidden)");
  await settled();
  await page.click("#btn-adopt");
  await visible("#routine-adopt-banner:not(.hidden)");
  await page.locator('[data-view="current"]').click();
  assert.match(
    await page.locator("#routines-container").innerText(),
    /配置できるアイテムはありません/,
  );
  await page.locator('[data-view="proposed"]').click();
  assert.equal(await page.locator("#journey").count(), 0);
  assert(await page.locator("#step-summary-intake").isVisible());
  assert.match(await page.locator("#step-status-intake").innerText(), /未入力/);
  assert(await page.locator("#step-summary-candidates").isVisible());
  await shot("03_mobile_routine");
  await page.reload();
  await page.click("#btn-direct-input");
  await page.fill("#cond-concern-label", "乾燥による小じわ");
  await page.fill("#cond-budget", "-1");
  await page.click("#btn-confirm-conditions");
  assert.match(await page.locator("#notice").innerText(), /1円以上/);
  await page.fill("#cond-budget", "3000");
  await page.click("#btn-confirm-conditions");
  await visible("#section-inventory:not(.hidden)");
  await settled();
  await page.click("#btn-sample-owned");
  await page.click("#btn-start-recommend");
  await visible("#section-progress:not(.hidden)");
  await page.click("#btn-cancel");
  await visible("#section-inventory:not(.hidden)");
  await settled();
  assert.equal(
    await page.locator("#owned-name-0").inputValue(),
    "化粧水 とてもしっとりタイプ",
  );
  // Stream termination without a result must recover to the intact input form.
  await page.route("**/api/recommend", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/x-ndjson",
      body: '{"type":"progress","node":"owned_research","status":"done"}\n',
    }),
  );
  await page.click("#btn-start-recommend");
  await visible("#section-inventory:not(.hidden)");
  await settled();
  assert.match(await page.locator("#notice").innerText(), /通信が切れました/);
  await page.unroute("**/api/recommend");
  await page.click("#btn-start-recommend");
  await visible("#section-candidates:not(.hidden)");
  await settled();
  await noOverflow();
  assert(await page.locator("#step-summary-intake").isVisible());
  assert(await page.locator("#step-summary-inventory").isVisible());
  assert.equal(
    await page.evaluate(() => document.activeElement.id),
    "research-stage",
  );
  await page.locator(".featured-product .routine-button").click();
  await page.click("#btn-adopt");
  await page.locator('#step-summary-intake [data-go="intake"]').click();
  assert(!(await page.locator("#section-candidates").isVisible()));
  await page.fill("#cond-budget", "1200");
  await page.click("#cancel-edit-intake");
  assert.match(
    await page.locator("#step-summary-text-intake").innerText(),
    /3,000/,
  );
  assert.match(await page.locator("#btn-adopt").innerText(), /選択中/);
  const unexpectedResearch = (request) => {
    if (request.url().endsWith("/api/recommend"))
      errors.push("Unchanged input must not trigger research");
  };
  page.on("request", unexpectedResearch);
  await page.locator('#step-summary-inventory [data-go="inventory"]').click();
  await page.click("#btn-start-recommend");
  assert(await page.locator("#section-routines").isVisible());
  await page.locator('#step-summary-intake [data-go="intake"]').click();
  await page.click("#btn-confirm-conditions");
  assert(await page.locator("#section-routines").isVisible());
  page.off("request", unexpectedResearch);
  await page.locator('#section-routines [data-go="candidates"]').click();
  // A failed rerank must preserve both the displayed order and the selected control.
  const oldName = await page
    .locator(".featured-product .product-name")
    .innerText();
  await page.route("**/api/rerank", (route) =>
    route.fulfill({
      status: 502,
      contentType: "application/json",
      body: '{"detail":"test failure"}',
    }),
  );
  await page.click("#btn-priority-light");
  await visible("#notice:not(.hidden)");
  assert.equal(
    await page.locator(".featured-product .product-name").innerText(),
    oldName,
  );
  assert.equal(
    await page.locator("#btn-priority-concern").getAttribute("aria-pressed"),
    "true",
  );
  await page.unroute("**/api/rerank");
  // Search text and product names are text, never executable markup.
  const fixture = await (
    await page.request.get(`${baseURL}/api/preview`)
  ).json();
  fixture.candidates[0].name = '<img src=x onerror="window.__injected=true">';
  await page.route("**/api/preview", (route) =>
    route.fulfill({
      status: 200,
      contentType: "application/json",
      body: JSON.stringify(fixture),
    }),
  );
  await page.reload();
  await page.click("#btn-preview");
  await visible(".featured-product");
  assert.equal(
    await page.locator(".featured-product .product-name img").count(),
    0,
  );
  assert.match(
    await page.locator(".featured-product .product-name").innerText(),
    /onerror/,
  );
  await page.unroute("**/api/preview");
  for (const width of [320, 390, 768, 1280]) {
    await page.setViewportSize({ width, height: 900 });
    await page.reload();
    await noOverflow();
    await shot(`home_${width}`);
    await page.click("#btn-preview");
    await visible(".featured-product");
    await noOverflow();
    await shot(`comparison_${width}`);
  }
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.reload();
  await page.click("#hero-start");
  assert.equal(
    await page.evaluate(
      () => getComputedStyle(document.documentElement).scrollBehavior,
    ),
    "auto",
  );
  assert.equal(
    await page.evaluate(() => document.activeElement.id),
    "step-heading-intake",
  );
  await page.keyboard.press("Tab");
  assert.equal(
    await page.evaluate(() => document.activeElement.id),
    "intake-text",
  );
  assert.deepEqual(errors, []);
  console.log(
    "SkinFit UI checks passed: preview, forms, cancellation, broken stream, rerank failure, text escaping, 4 responsive widths.",
  );
} finally {
  await browser.close();
}
