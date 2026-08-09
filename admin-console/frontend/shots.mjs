import { chromium } from "playwright";

const OUT = process.argv[2] || "/tmp/shots";
const BASE = "http://localhost:5173/#";
const routes = [
  ["login", "/login", false],
  ["scenarios", "/scenarios", true],
  ["scenario-fall", "/scenarios/fall", true],
  ["actions", "/actions", true],
  ["contacts", "/contacts", true],
  ["deploy", "/deploy", true],
];

const browser = await chromium.launch();
for (const [w, h, tag] of [[1280, 800, "desktop"], [768, 900, "tablet"], [390, 844, "mobile"]]) {
  const ctx = await browser.newContext({ viewport: { width: w, height: h } });
  await ctx.addInitScript(() => localStorage.setItem("donghaeng-authed", "1"));
  const page = await ctx.newPage();
  const errors = [];
  page.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
  page.on("pageerror", (e) => errors.push(String(e)));
  for (const [name, path, authed] of routes) {
    if (!authed && tag === "tablet") continue;
    if (!authed && tag === "mobile" && name !== "login") continue;
    await page.goto(BASE + path, { waitUntil: "networkidle" });
    await page.waitForTimeout(300);
    await page.screenshot({ path: `${OUT}/${name}-${tag}.png`, fullPage: true });
  }
  if (errors.length) console.log(`[${tag}] console errors:`, errors.slice(0, 5));
  await ctx.close();
}
await browser.close();
console.log("DONE");
