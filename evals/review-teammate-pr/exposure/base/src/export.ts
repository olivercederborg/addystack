export type Company = { id: string; exportVersion: "v2" | "v3"; hasSupplierCatalog: boolean }
export type ExportInput = { amounts: number[]; supplierId?: string }

// V2's file format has no supplier column.
const exportV2 = (input: ExportInput) => ({ lines: input.amounts.map((amount) => ({ amount })) })

const exportV3 = (input: ExportInput) => ({ supplierId: input.supplierId, lines: input.amounts.map((amount) => ({ amount })) })

export const runExport = (company: Company, input: ExportInput) =>
  company.exportVersion === "v3" ? exportV3(input) : exportV2(input)
