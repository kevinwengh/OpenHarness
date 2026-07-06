import { expect, test, type Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";

const auditRoot = process.env.WEB_AUDIT_OUTPUT ?? "/tmp/openharness-web-audit/screenshots";
const routes = [
  ["overview", "Overview", /Your agent workspace/],
  ["workbench", "Workbench", /^Workbench$/],
  ["sessions", "Sessions", /^Sessions$/],
  ["runtime", "Runtime", /^Runtime$/],
  ["capabilities", "Capabilities", /^Capabilities$/],
  ["work", "Work", /^Work$/],
  ["knowledge", "Knowledge", /^Knowledge$/],
  ["autopilot", "Autopilot", /^Autopilot$/],
] as const;

function collectDiagnostics(page: Page) {
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(`pageerror: ${error.message}`));
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(`console: ${message.text()}`);
  });
  return errors;
}

async function assertViewportFits(page: Page) {
  const dimensions = await page.evaluate(() => ({
    viewport: window.innerWidth,
    document: document.documentElement.scrollWidth,
    body: document.body.scrollWidth,
  }));
  expect(dimensions.document, JSON.stringify(dimensions)).toBeLessThanOrEqual(dimensions.viewport + 1);
  expect(dimensions.body, JSON.stringify(dimensions)).toBeLessThanOrEqual(dimensions.viewport + 1);
}

async function navigate(page: Page, label: string, layout: "desktop" | "tablet" | "mobile") {
  const mobile = layout === "mobile";
  if (mobile && !["Overview", "Workbench", "Sessions"].includes(label)) {
    await page.getByRole("button", { name: "More", exact: true }).click();
    const drawer = page.getByRole("dialog", { name: "Navigate" });
    await expect(drawer).toBeVisible();
    await drawer.getByRole("button", { name: label, exact: true }).click();
  } else {
    const navLabel = mobile ? "Mobile navigation" : "Primary navigation";
    const navigation = page.getByRole("navigation", { name: navLabel });
    await navigation.getByRole("button", { name: label, exact: true }).click();
  }
}

test("renders every main product area without browser or overflow errors", async ({ page }, testInfo) => {
  const errors = collectDiagnostics(page);
  const output = path.join(auditRoot, testInfo.project.name);
  await mkdir(output, { recursive: true });
  await page.goto("/#token=visual-audit-token");
  await expect(page.getByRole("heading", { level: 1, name: /Your agent workspace/ })).toBeVisible();

  for (const [id, label, heading] of routes) {
    if (id !== "overview") await navigate(page, label, testInfo.project.name as "desktop" | "tablet" | "mobile");
    await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
    await assertViewportFits(page);
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({ path: path.join(output, `${id}.png`) });
  }

  expect(errors).toEqual([]);
});

test("supports the command palette, runtime chooser, and permission review", async ({ page }, testInfo) => {
  test.skip(testInfo.project.name !== "desktop", "Interaction audit runs once at desktop size.");
  const errors = collectDiagnostics(page);
  const output = path.join(auditRoot, testInfo.project.name);
  await mkdir(output, { recursive: true });
  await page.goto("/workbench#token=visual-audit-token");
  await expect(page.getByRole("heading", { level: 1, name: "Workbench" })).toBeVisible();

  await page.keyboard.press("Control+k");
  const palette = page.getByRole("dialog", { name: "OpenHarness search" });
  await expect(palette).toBeVisible();
  await palette.getByRole("searchbox").fill("knowledge");
  await expect(palette.getByText("Knowledge", { exact: true })).toBeVisible();
  await page.screenshot({ path: path.join(output, "command-palette.png") });
  await page.keyboard.press("Escape");

  await page.getByRole("button", { name: /Effort Change/ }).click();
  const chooser = page.getByRole("dialog", { name: "Choose effort" });
  await expect(chooser).toBeVisible();
  await expect(chooser.getByRole("option")).toHaveCount(2);
  await page.screenshot({ path: path.join(output, "runtime-chooser.png") });
  await chooser.getByRole("option", { name: /Current setting/ }).click();

  const composer = page.getByRole("textbox", { name: "Message OpenHarness" });
  await composer.fill("Show a permission review");
  await page.getByRole("button", { name: "Send message" }).click();
  const permission = page.getByRole("dialog", { name: "Permission required" });
  await expect(permission).toBeVisible();
  await expect(permission.getByRole("button", { name: "Deny" })).toBeFocused();
  await page.screenshot({ path: path.join(output, "permission-review.png") });
  await permission.getByRole("button", { name: "Deny" }).click();
  await expect(permission).toBeHidden();
  await page.getByRole("button", { name: "Use light theme" }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await page.screenshot({ path: path.join(output, "workbench-light.png") });
  await assertViewportFits(page);
  expect(errors).toEqual([]);
});

test("renders resource details as a responsive bounded dialog", async ({ page }, testInfo) => {
  const errors = collectDiagnostics(page);
  const output = path.join(auditRoot, testInfo.project.name);
  await mkdir(output, { recursive: true });
  await page.goto("/capabilities#token=visual-audit-token");
  await expect(page.getByRole("heading", { level: 1, name: "Capabilities" })).toBeVisible();
  await page.getByRole("button", { name: "Details" }).first().click();
  const detail = page.getByRole("dialog", { name: "read_file" });
  await expect(detail).toBeVisible();
  await expect(detail.getByRole("button", { name: "Close details" })).toBeFocused();
  await assertViewportFits(page);
  await page.screenshot({ path: path.join(output, "resource-detail.png") });
  await page.keyboard.press("Escape");
  await expect(detail).toBeHidden();
  expect(errors).toEqual([]);
});
