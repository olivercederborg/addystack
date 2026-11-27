import type { Company } from "./export"

export const showSupplierPicker = (company: Company) => company.exportVersion === "v3" && company.hasSupplierCatalog
