import process from "node:process";
import { pathToFileURL } from "node:url";

const playwrightPath = process.env.CODEX_PLAYWRIGHT_PATH;
if (!playwrightPath) throw new Error("CODEX_PLAYWRIGHT_PATH is not set");
const { chromium } = await import(pathToFileURL(playwrightPath).href);

const baseUrl = process.argv[2] || "http://127.0.0.1:8000";
const launchOptions = { headless: true };
if (process.env.CODEX_CHROMIUM_PATH) launchOptions.executablePath = process.env.CODEX_CHROMIUM_PATH;
const browser = await chromium.launch(launchOptions);
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [];
page.on("pageerror", error => errors.push(error.message));
page.on("console", message => {
  if (message.type() === "error" && !message.text().includes("Failed to load resource")) errors.push(message.text());
});
page.on("response", response => {
  const expectedEmpty = response.status() === 404 && response.url().endsWith("/grid-plan");
  if (response.status() >= 400 && !response.url().includes("/favicon.ico") && !expectedEmpty) errors.push(`${response.status()} ${response.url()}`);
});
try {
  const response = await page.goto(baseUrl, { waitUntil: "networkidle", timeout: 30000 });
  if (!response || response.status() !== 200) throw new Error(`page status ${response?.status()}`);
  await page.waitForSelector("#runtimeMode", { timeout: 10000 });
  const mode = await page.locator("#runtimeMode").textContent();
  if (!mode?.startsWith("API ·")) throw new Error(`unexpected runtime mode: ${mode}`);
  const body = await page.locator("body").innerText();
  if (!body.includes("蚊媒风险识别")) throw new Error("workbench title was not rendered");
  await page.locator(".task-add").click();
  const taskName = `M6 browser ${Date.now()}`;
  await page.locator("#taskNameInput").fill(taskName);
  await page.locator("#taskAreaInput").fill("M6 browser validation area");
  await Promise.all([
    page.waitForLoadState("networkidle"),
    page.locator("#taskModal .modal-actions .primary").click(),
  ]);
  await page.waitForSelector("#runtimeMode", { timeout: 10000 });
  const card = page.locator(".task-card", { hasText: taskName });
  await card.waitFor({ timeout: 10000 });
  const taskId = await card.getAttribute("data-task-id");
  if (!taskId) throw new Error("created task card has no UUID");
  const cleanupStatus = await page.evaluate(async id => {
    const response = await fetch(`/api/v1/tasks/${id}`, { method: "DELETE" });
    return response.status;
  }, taskId);
  if (cleanupStatus !== 204) throw new Error(`task cleanup failed: ${cleanupStatus}`);
  if (errors.length) throw new Error(`browser errors: ${errors.join(" | ")}`);
  console.log("M6 browser check passed: API mode, real task creation, UUID card, cleanup, no JavaScript errors");
} finally {
  await browser.close();
}
