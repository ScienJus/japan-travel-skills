/* Optional headless checks for the public demo; Playwright is a developer dependency only. */
"use strict";
const assert = require("node:assert/strict");
const fs = require("node:fs/promises");
const path = require("node:path");
const {pathToFileURL} = require("node:url");
const {chromium} = require("playwright");
let phase = "setup";

async function main() {
  const args = process.argv.slice(2), options = {};
  for (let i = 0; i < args.length; i += 2) {
    assert(["--html", "--output", "--browser"].includes(args[i]) && args[i + 1], "Use --html, --output and optional --browser");
    options[args[i].slice(2)] = args[i + 1];
  }
  assert(options.html && options.output, "HTML and an external output directory are required");
  const root = await fs.realpath(path.resolve(__dirname, "../.."));
  let ancestor = path.resolve(options.output), suffix = [];
  while (true) {
    try {ancestor = await fs.realpath(ancestor); break;} catch (error) {
      if (error.code !== "ENOENT") throw error;
      suffix.unshift(path.basename(ancestor)); ancestor = path.dirname(ancestor);
    }
  }
  const destination = path.join(ancestor, ...suffix);
  assert(destination !== root && !destination.startsWith(root + path.sep), "Keep artifacts outside the checkout");
  await fs.mkdir(options.output, {recursive: true});
  const output = await fs.realpath(options.output);
  assert(output !== root && !output.startsWith(root + path.sep), "Keep browser artifacts outside the checkout");
  const browser = await chromium.launch({headless: true, ...(options.browser ? {executablePath: options.browser} : {})});
  const errors = [], network = [];
  try {
    const context = await browser.newContext({viewport: {width: 1440, height: 1100}, acceptDownloads: true});
    // All external traffic is blocked. Basemap failure is intentional, never a provider query.
    await context.route("https://**/*", route => route.abort());
    // Exercise automatic loading using synthetic tiles; never contact the provider.
    const tiles = "https://cyberjapandata.gsi.go.jp/**";
    await context.route(tiles, route => route.fulfill({status: 200, contentType: "image/png",
      body: Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+jRZkAAAAASUVORK5CYII=", "base64")}));
    const page = await context.newPage();
    page.on("pageerror", error => errors.push(error.message));
    page.on("request", request => {if (request.url().startsWith("https:")) network.push(request.url());});
    const fileUrl = pathToFileURL(path.resolve(options.html)).href;
    await page.goto(fileUrl);
    await page.locator(".day-plan").first().waitFor();
    const plan = JSON.parse(await page.locator("#plan-data").textContent());
    phase = "day-and-place-views";
    assert(plan.demo && plan.days.length === 3, "Use the generated three-day public demo");
    await page.waitForLoadState("networkidle");
    assert(network.length > 0 && network.length <= 12, "Default view loads one bounded tile viewport");
    assert(await page.locator("#map image").count() > 0, "Basemap must appear without a click");
    assert.equal(await page.locator(".day-plan").count(), plan.days.length);
    assert.equal(await page.locator(".place-card").count(), plan.places.length);
    assert(await page.locator("#basemap").evaluate(button =>
      button.getBoundingClientRect().bottom <= document.getElementById("map").getBoundingClientRect().top),
    "Basemap control must be visible before the location-only plot");
    const candidateBase = plan.days.find(day => plan.places.some(place => place.id === day.base_place_id && place.role === "candidate"));
    assert(candidateBase, "The demo must exercise a proposed hotel base");
    assert.match(await page.locator(`.day-plan[data-day-id="${candidateBase.id}"] .overnight`).textContent(), /候选/);
    await page.screenshot({path: path.join(output, "desktop.png"), fullPage: true});
    for (const day of plan.days) {
      await page.locator(`#days button[data-day-id="${day.id}"]`).click();
      assert.equal(await page.locator(".day-plan").count(), 1);
      assert.equal(await page.locator(".day-plan").getAttribute("data-day-id"), day.id);
      assert.equal(await page.locator(".leg").count(), day.leg_ids.length);
      const shown = await page.locator(".leg").evaluateAll(nodes => nodes.map(node => node.dataset.legId));
      assert.deepEqual(shown, day.leg_ids);
    }
    await page.locator('#days button[data-day-id=""]').click();
    await page.locator("#city").selectOption("nara");
    await page.locator("#kind").selectOption("restaurant");
    const naraFood = plan.places.filter(place => place.city_id === "nara" && place.kind === "restaurant");
    assert(naraFood.length > 0, "The public demo must include food candidates");
    assert.equal(await page.locator(".place-card").count(), naraFood.length);
    assert.equal(await page.locator(".map-marker").count(), naraFood.filter(place => place.coordinates).length);
    await page.locator('#days button[data-day-id="day-1"]').click();
    assert.equal(await page.locator(".place-card").count(), 0);
    assert(await page.locator("#places .empty").isVisible());
    assert.equal(await page.locator(".day-plan").getAttribute("data-day-id"), "day-1");
    await page.locator('#days button[data-day-id=""]').click();
    await page.locator("#city").selectOption("");
    await page.locator("#kind").selectOption("");
    await page.locator('.place-card[data-place-id="kyoto-station"] button').click();
    assert(await page.locator('.place-card[data-place-id="kyoto-station"]').evaluate(node => node.classList.contains("selected")));
    phase = "json-export";
    const downloadEvent = page.waitForEvent("download");
    await page.locator("#export").click();
    const download = await downloadEvent;
    const downloadPath = path.join(output, "downloaded-plan.json");
    await download.saveAs(downloadPath);
    assert.deepEqual(JSON.parse(await fs.readFile(downloadPath, "utf8")), plan);
    assert(network.every(url => /^https:\/\/cyberjapandata\.gsi\.go\.jp\/xyz\/pale\/\d+\/\d+\/\d+\.png$/.test(url)),
      "Only visible-area tile coordinates may be sent; no plan records");
    phase = "basemap-success";
    await page.locator("#fit").click();
    await page.waitForLoadState("networkidle");
    const loaded = await page.locator("#map image").count();
    assert(loaded > 0 && loaded <= 12, "One bounded viewport must render the supplied tiles");
    assert.equal(await page.locator("#basemap").isDisabled(), false);
    await page.locator("#basemap").click();
    assert.equal(await page.locator("#map image").count(), 0, "Basemap can be hidden again");
    const hiddenRequests = network.length;
    await page.locator("#fit").click();
    await page.waitForTimeout(100);
    assert.equal(network.length, hiddenRequests, "Hiding the basemap stops new tile requests");
    await context.unroute(tiles);
    network.length = 0;
    await page.reload();
    await page.locator(".day-plan").first().waitFor();
    phase = "basemap-failure";
    await page.waitForFunction(() => document.getElementById("basemap").disabled);
    assert(network.length > 0 && network.length <= 12, "One bounded viewport load only");
    const requests = network.length;
    await page.locator("#fit").click();
    await page.waitForTimeout(100);
    assert.equal(network.length, requests, "Failed basemap must not retry on redraw");
    assert.equal(await page.locator(".place-card").count(), plan.places.length);
    phase = "phone-layout";
    await page.reload();
    await page.setViewportSize({width: 390, height: 844});
    await page.locator(".day-plan").first().waitFor();
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Mobile view must not overflow horizontally");
    await page.screenshot({path: path.join(output, "mobile.png"), fullPage: true});
    await page.setViewportSize({width: 320, height: 800});
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth), "Small mobile view must remain reachable");
    phase = "safe-text-and-coincident-points";
    const hostile = structuredClone(plan);
    hostile.language = "en";
    hostile.title = '</script><script>globalThis.fixtureExecuted=true</script>';
    for (const place of hostile.places) delete place.coordinates;
    hostile.places[0].coordinates = structuredClone(plan.places[0].coordinates);
    hostile.places[1].coordinates = structuredClone(hostile.places[0].coordinates);
    const firstCity = hostile.cities[0].id, firstDay = hostile.days[0].id;
    hostile.cities[0].id = "all";
    hostile.days[0].id = "all";
    for (const place of hostile.places) if (place.city_id === firstCity) place.city_id = "all";
    for (const day of hostile.days) {
      day.city_ids = day.city_ids.map(id => id === firstCity ? "all" : id);
      if (day.base_city_id === firstCity) day.base_city_id = "all";
    }
    for (const leg of hostile.legs) if (leg.day_id === firstDay) leg.day_id = "all";
    const original = await fs.readFile(options.html, "utf8");
    const payload = JSON.stringify(hostile).replaceAll("<", "\\u003c").replaceAll(">", "\\u003e").replaceAll("&", "\\u0026");
    const variant = original.replace(/(<script id="plan-data" type="application\/json">)[\s\S]*?(<\/script>)/,
      (_match, start, end) => start + payload + end);
    const variantPath = path.join(output, "synthetic-variant.html");
    await fs.writeFile(variantPath, variant);
    await page.goto(pathToFileURL(variantPath).href);
    assert.equal(await page.locator("#title").textContent(), hostile.title);
    assert.equal(await page.locator("#schedule-heading").textContent(), "Daily itinerary");
    assert.equal(await page.evaluate(() => globalThis.fixtureExecuted), undefined);
    await page.locator('#days button[data-day-id="all"]').click();
    assert.equal(await page.locator(".day-plan").count(), 1, "A day named all must be independently selectable");
    assert.equal(await page.locator(".day-plan").getAttribute("data-day-id"), "all");
    await page.locator('#days button[data-day-id=""]').click();
    await page.locator("#city").selectOption("all");
    assert.equal(await page.locator(".place-card").count(), hostile.places.filter(place => place.city_id === "all").length,
      "A city named all must not select every city");
    await page.locator("#city").selectOption("");
    assert.equal(await page.locator(".map-marker").count(), 2);
    await page.locator('.place-card[data-place-id="kyoto-station"] button').click();
    assert.equal(await page.locator(".map-marker").last().getAttribute("data-place-id"), "kyoto-station");
    assert.deepEqual(errors, []);
    await fs.writeFile(path.join(output, "result.json"), JSON.stringify({status: "pass", realProviderRequests: 0,
      basemapSuccess: "synthetic image; no provider contacted", basemapFailure: "mocked; no provider contacted", browserErrors: 0, phoneWidths: [390, 320]}, null, 2) + "\n");
    console.log("PASS: day/transport sync, filters, missing coordinates, JSON export, offline fallback and phone layout");
  } finally {
    await browser.close();
  }
}
main().catch(() => {console.error(`Browser check failed at ${phase}; inspect local artifacts and dependencies. No input values printed.`); process.exitCode = 1;});
