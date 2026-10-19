/**
 * Capture a screenshot of every page for the README.
 *
 *   node tools/screenshots.mjs [baseUrl] [outDir]
 *
 * Expects the app to already be running (`python run.py --headless`). Drives it
 * through a demo scramble + solve first so the analytics and solution pages are
 * populated rather than empty.
 */
import { mkdir } from "node:fs/promises";
import { join } from "node:path";
import puppeteer from "puppeteer";

const BASE = process.argv[2] ?? "http://127.0.0.1:8000";
const OUT = process.argv[3] ?? "docs/screenshots";

const PAGES = [
  ["dashboard", "01-dashboard"],
  ["camera", "02-camera"],
  ["scanner", "03-scanner"],
  ["viewer", "04-cube-viewer"],
  ["solution", "05-solution"],
  ["analytics", "06-analytics"],
  ["calibration", "07-calibration"],
  ["logs", "08-logs"],
  ["settings", "09-settings"],
];

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

await mkdir(OUT, { recursive: true });

const browser = await puppeteer.launch({
  headless: "new",
  args: ["--no-sandbox", "--disable-dev-shm-usage", "--force-color-profile=srgb"],
});
const page = await browser.newPage();
await page.setViewport({ width: 1560, height: 980, deviceScaleFactor: 2 });

const errors = [];
page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
page.on("console", (message) => {
  if (message.type() === "error") errors.push(`console: ${message.text()}`);
});

await page.goto(`${BASE}/#/dashboard`, { waitUntil: "networkidle2", timeout: 60000 });
await sleep(2500);

/** Populate the app so the solution/analytics pages have real content. */
async function command(name, payload = {}) {
  await page.evaluate(
    (cmd, data) => {
      // The store owns the only socket; reach it through a fresh emit.
      const socket = window.__cubeSocket;
      if (socket) socket.emit("command", { command: cmd, payload: data });
    },
    name,
    payload,
  );
  await sleep(700);
}

// Pin the theme so the documented pages are always shot in dark, whatever the
// running instance happened to be left on.
await command("settings.update", { theme: "dark" });
await command("cube.scramble", { length: 22 });
await command("solve.run");
await sleep(2500);
await command("playback.seek", { index: 4 });
await sleep(800);

for (const [hash, name] of PAGES) {
  await page.goto(`${BASE}/#/${hash}`, { waitUntil: "domcontentloaded" });
  await page.evaluate(() => window.scrollTo(0, 0));
  await sleep(1600); // let entry animations settle
  await page.screenshot({ path: join(OUT, `${name}.png`), captureBeyondViewport: false });
  console.log(`captured ${name}.png`);
}

/** The two alternate themes, shot on the dashboard. */
await page.goto(`${BASE}/#/dashboard`, { waitUntil: "domcontentloaded" });
for (const [theme, name] of [
  ["light", "10-light-theme"],
  ["midnight", "11-midnight-theme"],
]) {
  await command("settings.update", { theme });
  await sleep(1600);
  await page.screenshot({ path: join(OUT, `${name}.png`) });
  console.log(`captured ${name}.png`);
}
await command("settings.update", { theme: "dark" });

if (errors.length) {
  console.error(`\n${errors.length} browser error(s):`);
  for (const error of errors.slice(0, 20)) console.error("  " + error);
}

await browser.close();
console.log(`\nScreenshots written to ${OUT}`);
process.exit(errors.length ? 1 : 0);
