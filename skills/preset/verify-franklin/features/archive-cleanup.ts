// Recipe for features/archive-cleanup.md. Run: scripts/run.sh features/archive-cleanup.ts
import { expect, signIn, verify } from "../scripts/browser"

await verify("archive-cleanup", async ({ page, proof }) => {
  await signIn(page)
  await page.goto("/settings")
  const cleanup = page.getByRole("combobox", { name: "Move unmatched files to trash" })
  const save = page.locator("form").filter({ has: cleanup }).getByRole("button", { name: "Save changes" })
  const saved = page.getByText("File archive cleanup saved")

  const choose = async (option: string) => {
    await cleanup.click()
    await page.getByRole("option", { name: option, exact: true }).click()
    await expect(cleanup).toHaveText(option)
    await save.click()
    await expect(saved.first()).toBeVisible()
  }

  await expect(cleanup).toBeEnabled()
  const original = (await cleanup.innerText()).trim()
  const target = original === "After 90 days" ? "After 60 days" : "After 90 days"

  await choose(target)
  await proof("cleanup-saved")

  await page.reload()
  await expect(cleanup).toHaveText(target)
  await proof("cleanup-after-reload")

  await choose(original)
  await page.reload()
  await expect(cleanup).toHaveText(original)
  await proof("cleanup-restored")
  console.log(`restored file archive cleanup to ${original}`)
})
