import { showSupplierPicker } from "./export-form"
import { runExport, type Company, type ExportInput } from "./export"

export const exportForm = (company: Company) => ({
  showSupplierPicker: showSupplierPicker(company),
  submit: (input: ExportInput) => runExport(company, input),
})
