import assert from "node:assert/strict"
import { test } from "node:test"
import { getReceipts } from "./api/routes.ts"

test("lists each receipt document with a 15-minute download URL", async () => {
  const { status, body } = await getReceipts("t1")
  assert.equal(status, 200)
  assert.deepEqual(body, [
    { id: "d1", transactionId: "t1", fileName: "taxi.pdf", downloadUrl: "https://bucket.example/r1?X-Amz-Expires=900" },
    { id: "d2", transactionId: "t1", fileName: "hotel.jpg", downloadUrl: "https://bucket.example/r2?X-Amz-Expires=900" },
  ])
})

test("fails the whole listing when a file can't be signed, with no partial results", async () => {
  assert.deepEqual(await getReceipts("t2"), { status: 500, body: { error: "Unable to list receipts" } })
})
