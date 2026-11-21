// Record an inspection of actual persisted evidence, not a simulation of live execution.
import { chromium } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
const id = process.argv[2];
if (!id || !/^[a-f0-9-]{36}$/.test(id))
  throw new Error("Pass the actual coding run UUID");
const destination = path.resolve("../../docs/demo");
await mkdir(destination, { recursive: true });
const browser = await chromium.launch({
  channel: process.env.KAIRO_BROWSER_CHANNEL || "chrome",
});
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  recordVideo: {
    dir: "/private/tmp/kairo-demo-video",
    size: { width: 1440, height: 1000 },
  },
});
try {
  const page = await context.newPage();
  await page.goto(`http://127.0.0.1:3000/#run=${id}`);
  await page
    .locator(".panel-heading .status")
    .filter({ hasText: "COMPLETED" })
    .waitFor();
  await page.screenshot({
    path: path.join(destination, "dashboard.png"),
    fullPage: true,
  });
  await page.waitForTimeout(1800);
  const recovered = page
    .locator("details.event")
    .filter({ has: page.locator("summary", { hasText: "attempt recovered" }) });
  await recovered.first().locator("summary").click();
  await recovered.first().scrollIntoViewIfNeeded();
  await page.waitForTimeout(1800);
  await page.getByRole("button", { name: "Tools", exact: true }).click();
  await page
    .locator(".inspection")
    .getByText(/write_file/)
    .waitFor();
  await page.waitForTimeout(1800);
  await page.getByRole("button", { name: "Checkpoints", exact: true }).click();
  await page
    .locator(".inspection")
    .getByText(/workspace_reference/)
    .waitFor();
  await page.waitForTimeout(1800);
  await page.getByRole("button", { name: "Trace", exact: true }).click();
  await page
    .locator(".inspection")
    .getByText(/retries/)
    .waitFor();
  await page.waitForTimeout(1800);
  await context.close();
  await page.video().saveAs(path.join(destination, "coding-demo.webm"));
} finally {
  await context.close();
  await browser.close();
}
console.log(
  "Recorded persisted-run walkthrough; not a replayed live model session.",
);
