// Stands in for the bucket. r3's object was deleted, as happens when a file is cleaned up but its row isn't.
const BUCKET = new Set(["r1", "r2"])

/** Checks the object exists (HEAD), then signs a GET URL that expires in `expiresIn` seconds. */
export const signUrl = async (key: string, expiresIn: number) => {
  await new Promise((resolve) => setTimeout(resolve, 50)) // one storage round trip
  if (!BUCKET.has(key)) throw new Error(`No object at ${key}`)
  return `https://bucket.example/${key}?X-Amz-Expires=${expiresIn}`
}

/** Reports a receipt file that's missing from storage (Sentry in the app). */
export const reportMissing = (key: string) => console.warn(`Missing receipt file: ${key}`)
