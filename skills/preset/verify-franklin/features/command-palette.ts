// Recipe for features/command-palette.md. Run: scripts/run.sh features/command-palette.ts
import { expect, signIn, verify } from "../scripts/browser"

await verify("command-palette", async ({ page, proof }) => {
  await signIn(page)
  await page.goto("/settings")

  // The shortcut listener attaches on hydration, which `next dev` can delay past page load.
  const input = page.getByPlaceholder("Search pages, cards, transactions, and receipts...")
  await expect(async () => {
    if (!(await input.isVisible())) await page.keyboard.press("ControlOrMeta+k")
    await expect(input).toBeVisible({ timeout: 2_000 })
  }).toPass({ timeout: 30_000 })
  await proof("palette-open")

  await input.fill("Test Card")
  const cards = page.getByRole("group", { name: "Cards" })
  await expect(cards.getByRole("option", { name: /Test Card/ }).first()).toBeVisible()
  await proof("cards-found")

  await input.fill("Slack")
  const transactions = page.getByRole("group", { name: "Transactions" })
  const receipts = page.getByRole("group", { name: "Receipts" })
  await expect(transactions.getByRole("option", { name: /SLACK/i }).first()).toBeVisible()
  await expect(receipts.getByRole("option", { name: /SLACK/i }).first()).toBeVisible()
  await expect(page.getByText(/Search failed for/)).toHaveCount(0)
  await proof("transactions-and-receipts-found")

  await transactions.getByRole("option", { name: /SLACK/i }).first().click()
  await expect(input).toBeHidden()
  await expect(page).toHaveURL(/\/transactions/)
  await proof("transaction-opened")
})
