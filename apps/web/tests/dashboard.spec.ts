import { test, expect } from "@playwright/test";

test("real submission, approval, completion and inspection", async ({
  page,
}) => {
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Overview", exact: true }),
  ).toBeVisible();
  await expect(page.getByText("Connecting…")).toHaveCount(0);
  await page.getByRole("button", { name: "Tasks", exact: true }).click();
  await page
    .getByLabel("Task description")
    .fill(`browser evidence ${Date.now()}`);
  await page.getByLabel("Model adapter").selectOption("scripted");
  const script = await page
    .getByLabel("Prescribed responses (no inference)")
    .inputValue();
  expect(JSON.parse(script)).toHaveLength(3);
  await page.getByRole("button", { name: "Queue task", exact: true }).click();
  await expect(page.getByRole("heading", { name: /Execution / })).toBeVisible();
  const id = new URL(page.url()).hash.split("=")[1];
  await page
    .getByRole("button", { name: /Approvals/ })
    .first()
    .click();
  const approval = page
    .locator("article.approval")
    .filter({
      has: page.getByRole("button", {
        name: `Run ${id.slice(0, 8)}`,
        exact: true,
      }),
    });
  await expect(
    approval.getByRole("button", { name: "Approve action" }),
  ).toBeVisible();
  await page
    .getByLabel("Decision reason")
    .fill("Browser test reviewed this exact hello.txt write");
  await approval.getByRole("button", { name: "Approve action" }).click();
  await page
    .getByRole("button", { name: "Run inspector", exact: true })
    .click();
  await expect(page.locator(".panel-heading .status")).toHaveText("COMPLETED", {
    timeout: 15000,
  });
  await page.getByRole("button", { name: "Tools", exact: true }).click();
  await expect(page.locator(".inspection")).toContainText("hello Kairo");
  await page.getByRole("button", { name: "Checkpoints", exact: true }).click();
  await expect(page.locator(".inspection")).toContainText(
    "workspace_reference",
  );
  await page.getByRole("button", { name: "Trace", exact: true }).click();
  await expect(page.locator(".inspection")).toContainText("tool_calls");
  await page.screenshot({
    path: "/private/tmp/kairo-m11-inspector.png",
    fullPage: true,
  });
});

test("mobile layout and real overview", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Recent executions" }),
  ).toBeVisible();
  await expect
    .poll(() =>
      page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    )
    .toBe(true);
  await page.screenshot({
    path: "/private/tmp/kairo-m11-mobile.png",
    fullPage: true,
  });
});
