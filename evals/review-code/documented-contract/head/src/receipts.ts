import { signUrl } from "./storage.ts"

export type ReceiptDocument = { id: string; transactionId: string; fileName: string; storageKey: string }

// Stands in for the receipt_documents table.
export const DOCUMENTS: ReceiptDocument[] = [
  { id: "d1", transactionId: "t1", fileName: "taxi.pdf", storageKey: "r1" },
  { id: "d2", transactionId: "t1", fileName: "hotel.jpg", storageKey: "r2" },
  { id: "d3", transactionId: "t2", fileName: "lunch.pdf", storageKey: "r3" },
  { id: "d4", transactionId: "t2", fileName: "dinner.pdf", storageKey: "r1" },
]

const downloadUrlLifetimeSeconds = 15 * 60

/** The Transaction's receipt documents, each with a download URL valid for 15 minutes. */
export const listReceiptDocuments = async (transactionId: string) => {
  const rows = []
  for (const { storageKey, ...metadata } of DOCUMENTS.filter((d) => d.transactionId === transactionId)) {
    rows.push({ ...metadata, downloadUrl: await signUrl(storageKey, downloadUrlLifetimeSeconds) })
  }
  return rows
}
