// Recipe for features/settings-notifications.md. Run: scripts/run.sh features/settings-notifications.ts
import { expect, signIn, verify } from "../scripts/browser"

await verify("settings-notifications", async ({ page, proof }) => {
  await signIn(page)
  await page.goto("/settings")
  const threshold = page.getByLabel("Low balance notification threshold")
  const save = page.getByRole("button", { name: "Save changes" }).first()
  const original = await threshold.inputValue()
  const target = original === "1000" ? "1500" : "1000"

  await threshold.fill(target)
  await save.click()
  await expect(page.getByText("Notification settings saved")).toBeVisible()
  await proof("threshold-saved")

  await page.reload()
  await expect(threshold).toHaveValue(target)
  await proof("threshold-after-reload")

  await threshold.fill("-100")
  await save.click()
  await expect(page.getByText("Notification threshold must be greater than or equal to 0")).toBeVisible()
  await proof("negative-rejected")

  await page.reload()
  await expect(threshold).toHaveValue(target)
  await threshold.fill(original)
  await save.click()
  await expect(page.getByText("Notification settings saved")).toBeVisible()
  await page.reload()
  await expect(threshold).toHaveValue(original)
  console.log(`restored threshold to ${original || "(empty)"}`)
})
