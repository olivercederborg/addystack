import { DOCUMENTS } from "../receipts.ts"
import { reportMissing, signUrl } from "../storage.ts"

/** The web app's receipt list: signs every file at once and leaves out, and reports, one whose file is gone. */
export const listReceiptsForWeb = async (transactionId: string) => {
  const documents = DOCUMENTS.filter((d) => d.transactionId === transactionId)
  const results = await Promise.allSettled(
    documents.map(async (d) => ({ id: d.id, fileName: d.fileName, url: await signUrl(d.storageKey, 900) })),
  )
  return results.flatMap((result, i) => {
    if (result.status === "fulfilled") return [result.value]
    reportMissing(documents[i].storageKey)
    return []
  })
}
