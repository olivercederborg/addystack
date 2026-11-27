import { exportRows } from "./fees"
import { join } from "node:path"

export const exportPath = (dir: string) => join(dir, "export.csv")
export { exportRows }
