export type ReceiptDocument = { id: string; transactionId: string; fileName: string; storageKey: string }

// Stands in for the receipt_documents table.
export const DOCUMENTS: ReceiptDocument[] = [
  { id: "d1", transactionId: "t1", fileName: "taxi.pdf", storageKey: "r1" },
  { id: "d2", transactionId: "t1", fileName: "hotel.jpg", storageKey: "r2" },
  { id: "d3", transactionId: "t2", fileName: "lunch.pdf", storageKey: "r3" },
  { id: "d4", transactionId: "t2", fileName: "dinner.pdf", storageKey: "r1" },
]

/** The Transaction's receipt documents, without their storage keys. */
export const listReceiptDocuments = async (transactionId: string) =>
  DOCUMENTS.filter((d) => d.transactionId === transactionId).map(({ storageKey, ...metadata }) => metadata)
