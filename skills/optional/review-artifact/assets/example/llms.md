# Dinero on Export V3

shop · [#5527](https://github.com/acme/shop/pull/5527) (head `1ca088c190`) · [#5528](https://github.com/acme/shop/pull/5528) (head `067fcfb23e`, stacked on #5527) · into develop

**Safe to merge dark.** Export V3 can now export Dinero receipts; no company has `EXPORT_V3_DINERO`, so all stay on V2.

0 companies exposed · 2 stacked PRs · 84/84 unit tests · 35/35 parity cases

Rollout: 01 review #5527 and #5528 (this review) · 02 merge, dark, no company · 03 beta, DEV-1796 · 04 roll out, the flag per company

HTML version: [/](/)

## Route

`runsOnExportV3` checks the company's `EXPORT_V3_DINERO` flag (#5528).

Pins mark what to review; Details has the code behind each one.

- Flag off, every company today: the export goes to Export V2, unchanged (`exportBookkeepingExportV2`).
- Flag on, no company yet (pin 1 marks this gate, #5528), the receipt takes #5527's Export V3 AttachmentFirst path:
  1. Upload the receipt file: `POST /v1/{org}/files` with `receipt.pdf`. Dinero answers with `fileGuid` `file-guid-1`.
  2. Post one ledger line that links it: `POST /v1.2/{org}/ledgeritems`.

What lands in Dinero for the contract-test receipt (pin 2). This illustrates the request body; it is not a Dinero screenshot.

| Date | Account | Contra | Description | Amount | File |
|---|---|---|---|---|---|
| 2026-01-15 | 3606 | 55000 | Cloud hosting | 125.5 | receipt.pdf (`fileGuid` file-guid-1) |

An expired Dinero login asks to reconnect, without retrying (`InvalidCredentials`, not retryable).

## Currency

Dinero books only DKK; `projectToLedgerCurrency` keeps V2's behavior for other wallets.

| Wallet | amount sent | description sent |
|---|---|---|
| DKK wallet (18.15 EUR purchase) | 136.125 | Cloud hosting |
| EUR wallet (20 EUR) | 20 | [EUR amount treated as DKK; correct draft before posting] - Cloud hosting (pin 3) |

## Decisions

- Rollout flag: picked `EXPORT_V3_DINERO`, on for no company, over `EXPORT_V3`, already on for 214 e-conomic companies plus Acme, which #5287 deletes.
- Non-DKK wallets: picked V2's note, so the draft exports flagged, over failing the export, which leaves no draft at all.

## Verified

| Check | At | Result |
|---|---|---|
| Required CI | `1ca088c190` (#5527), `067fcfb23e` (#5528) | Both PRs pass: Lint and Typecheck, Vitest, Playwright, Storybook, Linear issue. |
| Unit tests | `067fcfb23e` | Adapter, gate and error mapping 84/84; dispatcher 4/4. |
| V2/V3 parity | `742c277b9f` | 35/35 money cases match; payload, attachments, lifecycle and eligibility traced (differences in #5528). |
| Pages | `4250ed670b` | Receipts and accounting-rules pages unchanged, flag on or off. |

## Not verified

| Gap | Covered |
|---|---|
| A real Dinero organization | The beta step, DEV-1796. |
| Merging with #5287, in either order | A test fails if Dinero reaches V3 without its flag. |

## Details

### Path through the code

`createPendingExport`, `createPendingReexport`, and `exportScheduler` ask `runsOnExportV3`, then `dispatchBookkeepingExports` sends the export to `exportBookkeepingExportV2` or `startExportTask`. On V3, `exportReceiptTask` gets `integrationLayer`'s `DINERO` case, which runs `ExportAttachmentFirst` with `DineroAttachments` and `DineroJournalEntries`. On develop, `routesByServiceType.DINERO` is `null`, so `isOnExportV3("DINERO")` is false. Every document is uploaded; the first `fileGuid` is linked, as in V2.

### Pin 1 · The gate · `apps/web/src/features/bookkeeping/bookkeeping-integration.layer.ts:65-91`

```ts
/** The flag each V3 service type still rolling out needs; the rest use V3 for every company. */
const EXPORT_V3_ROLLOUT_FLAGS = new Map<BookkeepingServiceType, FeatureFlag>([
  ["E_CONOMIC", EXPORT_V3_FEATURE_FLAG],
  ["DINERO", EXPORT_V3_DINERO_FEATURE_FLAG],
])

/**
 * Whether the company's exports through a service type run on Export V3. It needs Export Strategy
 * routes, and during the service type's rollout the company's rollout flag.
 */
export const runsOnExportV3 = Effect.fn("runsOnExportV3")(function* ({
  company,
  serviceType,
}: {
  company: FeatureFlagCompany
  serviceType: BookkeepingServiceType
}) {
  if (!ExportStrategy.isOnExportV3(serviceType)) return false

  const rolloutFlag = EXPORT_V3_ROLLOUT_FLAGS.get(serviceType)
  if (!rolloutFlag) return true

  const featureFlags = yield* FeatureFlags

  return yield* featureFlags.has(company, rolloutFlag)
})
```

### Gate outcomes · `bookkeeping-integration.layer.test.ts`

| `serviceType` | Stored flags | Runs on |
|---|---|---|
| `DINERO` | none, or only `EXPORT_V3` | V2 |
| `DINERO` | `EXPORT_V3_DINERO` | V3 |
| `DINERO`, Acme's own company | none | V2 |
| `E_CONOMIC` | `EXPORT_V3` / only `EXPORT_V3_DINERO` | V3 / V2 |
| `MONEYBIRD` | none | V3 |
| `UNICONTA` | both | V2 |

### Pin 2 · Field mapping · `(dinero)/(export)/create-ledger-item.ts:49-68`, values from its contract test

| `JournalEntryDraft` | `LedgerItemModelV2` | Example |
|---|---|---|
| `date` | `voucherDate` | 2026-01-15T23:59:59.000Z → "2026-01-15" |
| `references.attachmentIds[0]` | `fileGuid` | "file-guid-1", left out with no documents |
| `account.number` | `lines[0].accountNumber` | "3606" → 3606 |
| `contraAccount.number` | `lines[0].balancingAccountNumber` | "55000" → 55000; missing fails with `MissingAccountNumber` |
| `walletAmount` | `lines[0].amount` | 125.5 |
| `description` | `lines[0].description` | "Cloud hosting" |
| `vatCode`, currencies, `supplierId`, dimensions | not sent | VAT comes from the account's default |

### Pin 3 · Currency · `projectToLedgerCurrency`

`projectToLedgerCurrency` (`create-ledger-item.ts:99-113`) sends a DKK wallet's amount as is, zero included (`ee038144a2`). Any other wallet gets the V2 prefix. Since `1ca088c190` it no longer calls the shared `BookingCurrency.resolve`. Test values: a DKK wallet with an 18.15 EUR purchase sends 136.125; a 20 EUR wallet sends 20 with the prefix.

### Notes

- Expired login (`c64f6bc77d`): `(dinero)/dinero-error-mapping.ts` reads Visma Connect's `invalid_grant` as `InvalidCredentials`, which doesn't retry and shows "Authentication failed. Please reconnect your integration."
- Merge rule for #5287: whoever merges second keeps `runsOnExportV3` and its map, and drops only the `E_CONOMIC` entry.

### Evidence

- Dinero adapter tests 19/19 against mocked Dinero (ledger item 12, attachment 4, accounts 3), plus 8 gate cases and the Acme company case.
- apps/web typecheck exit 0. Unit tests for the adapter, gate, OAuth, and error mapping: 84/84.
- CI passes on both PRs: Typecheck, Lint, Vitest, Storybook, and Playwright 1–4/4.
- Heads: #5527 `1ca088c190`, #5528 `067fcfb23e`.
