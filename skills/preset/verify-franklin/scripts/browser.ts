// Helpers for recipes run through scripts/run.sh, which supplies the test env.
import { chmodSync, mkdirSync, rmSync, writeFileSync } from "node:fs"
import { createRequire } from "node:module"
import { join } from "node:path"
import type { Page } from "@playwright/test"

// The skill lives outside the checkout, so load the checkout's Playwright from apps/web,
// where run.sh starts. Next to this file, Bun finds none, or a different cached version.
// Not "playwright": apps/web's tsconfig paths map that name to its own playwright/ folder.
const { chromium, expect }: typeof import("@playwright/test") = await import(
  createRequire(join(process.cwd(), "package.json")).resolve("@playwright/test")
)

export { expect }

const BASE_URL = "http://localhost:3000"
export const USER = "dev+local@hifranklin.com"
const OTP = "123456" // matches TEST_OTP_CREDENTIALS in launch.sh

// Opens a browser session for one feature. Evidence goes to <run>/evidence/<feature>/,
// replacing an earlier attempt's, so the folder only ever holds one attempt.
export async function open(feature: string) {
  const run = process.env.VERIFY_RUN
  if (!run) throw new Error("VERIFY_RUN is unset; run recipes through scripts/run.sh")
  const dir = join(run, "evidence", feature)
  rmSync(dir, { recursive: true, force: true })
  mkdirSync(dir, { recursive: true })
  const browser = await chromium.launch()
  // Same timezone as apps/web/playwright.config.ts, so server and client format dates alike.
  const context = await browser.newContext({
    baseURL: BASE_URL,
    viewport: { width: 1440, height: 1000 },
    timezoneId: "Europe/Copenhagen",
  })
  const page = await context.newPage()
  // Uncaught page errors (such as a hydration mismatch) are evidence too.
  const pageErrors: string[] = []
  page.on("pageerror", (error) => pageErrors.push(error.message.split("\n")[0]))
  const steps: { name: string; url: string; screenshot: string }[] = []

  // Saves a screenshot and an ARIA snapshot of the page as the next numbered step.
  const proof = async (name: string) => {
    const base = join(dir, `${String(steps.length + 1).padStart(2, "0")}-${name}`)
    await page.screenshot({ path: `${base}.png`, fullPage: true })
    // ARIA snapshots include input values, so a filled password field would leak it.
    // Redact the known value, as Playwright's MCP server does with its secrets. A value
    // Playwright escapes or collapses (a \, ", or double space) wouldn't match.
    const aria = await page.locator("body").ariaSnapshot()
    const password = process.env.TEST_USER_PASSWORD
    const safe = password ? aria.replaceAll(password, "[redacted]") : aria
    writeFileSync(`${base}.aria.txt`, `${page.url()}\n\n${safe}`)
    steps.push({ name, url: page.url(), screenshot: `${base}.png` })
    console.log(`proof: ${base}.png`)
  }

  const close = () => browser.close()
  return { page, proof, close, dir, pageErrors, steps }
}

// Signs in through the real login page as the seeded owner. The OTP bypass in
// launch.sh accepts the fixed code for this user only.
export async function signIn(page: Page) {
  const password = process.env.TEST_USER_PASSWORD
  if (!password) throw new Error("TEST_USER_PASSWORD is unset; run recipes through scripts/run.sh")
  await page.goto("/auth/login")
  await page.getByLabel("Email address").fill(USER)
  await page.getByLabel("Password", { exact: true }).fill(password)
  await page.getByRole("button", { name: "Continue", exact: true }).click()
  // The bypass covers email OTP only, and suppresses the email itself. Login lands on the
  // method choice, the email code, or the authenticator code, depending on the user's
  // factors and which one they used last; reach the email code from any of them.
  const emailCode = page.getByLabel(/one-time code \(check your email\)/)
  const emailMethod = page.getByRole("link", { name: "Email one-time password" })
  const otherMethod = page.getByRole("link", { name: "Use another authentication method" })
  await expect(emailCode.or(emailMethod).or(otherMethod).first()).toBeVisible({ timeout: 30_000 })
  if (!(await emailCode.isVisible())) {
    if (await otherMethod.isVisible()) await otherMethod.click()
    await emailMethod.click()
  }
  await emailCode.fill(OTP)
  await page.getByRole("button", { name: "Continue", exact: true }).click()
  await expect(page).not.toHaveURL(/\/auth\//, { timeout: 30_000 })
}

// Signs in through the real login page and saves the browser state (cookies) to path,
// for explore.sh to load into agent-browser. Owner-only, since it holds a live session.
export async function saveSignIn(path: string) {
  const browser = await chromium.launch()
  try {
    const page = await browser.newPage({ baseURL: BASE_URL })
    await signIn(page)
    await page.context().storageState({ path })
    chmodSync(path, 0o600)
  } finally {
    await browser.close()
  }
}

// Runs a recipe, saving a failure screenshot and exiting 1 when a step throws. Writes
// steps.json, the run's record of the result, steps, and page errors that gallery.sh shows.
export async function verify(feature: string, recipe: (session: Awaited<ReturnType<typeof open>>) => Promise<void>) {
  const session = await open(feature)
  let error: string | undefined
  try {
    await recipe(session)
    console.log(`✅ ${feature}: verified; evidence in ${session.dir}`)
  } catch (cause) {
    error = cause instanceof Error ? cause.message : String(cause)
    await session.proof("failure").catch(() => {})
    console.error(`❌ ${feature}: ${error}`)
    process.exitCode = 1
  } finally {
    await session.close()
  }
  if (session.pageErrors.length) {
    writeFileSync(join(session.dir, "page-errors.txt"), session.pageErrors.join("\n") + "\n")
    console.log(`⚠️ ${session.pageErrors.length} page error(s) during the run; see ${session.dir}/page-errors.txt`)
  }
  const record = { feature, result: error ? "failed" : "verified", error, steps: session.steps, pageErrors: session.pageErrors }
  writeFileSync(join(session.dir, "steps.json"), JSON.stringify(record, null, 2) + "\n")
}
