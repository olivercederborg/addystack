import { listReceiptDocuments } from "../receipts.ts"

/** GET /v1/transactions/:id/receipts */
export const getReceipts = async (transactionId: string) => {
  try {
    return { status: 200, body: await listReceiptDocuments(transactionId) }
  } catch {
    return { status: 500, body: { error: "Unable to list receipts" } }
  }
}
