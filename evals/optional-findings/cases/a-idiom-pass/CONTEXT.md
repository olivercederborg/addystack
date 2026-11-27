# Session so far: #5612, Receipt Dimensions through Catalog.load

Oliver's own franklin-next PR #5612, "Load Receipt Dimensions through Catalog.load"
(DEV-3239), is a **draft** with the `run-ci` label and no reviews or approvals. A worker
under this project's coordinator built it; CI passes 22 jobs at `9b32605`. It moves Receipt
Dimensions onto the shared `Catalog.load` path that VAT codes and Suppliers already use.

Oliver's last message asked for a review of #5612: "Make sure it's idiomatic and follows
$coding-standards". This session ran **verify-work** on it with the coding-standards lens
(all 5 references) and taste. The verifier's checked facts are below. The severity and call
of each is yours to set, as the skill's format says; reply as that skill's report, ending
with your Next options.

## Verified facts

1. **The dimensions loader builds a Layer from a capability it already holds**:
   `Effect.provide(cachedDimensions(connection).pipe(Layer.provide(Layer.succeed(Dimensions, capability))))`
   at `get-receipt-dimensions.handler.ts:77`. The VAT code sibling
   (`get-cached-vat-codes.handler.ts:37,62`) provides `connectionLayer(connection)` and
   reads the service with `serviceOption`. With `Layer.succeed(capability)`,
   `Catalog.load` can never return Disabled, so that branch is dead.
   `BookkeepingIntegrationLayerMap` is a `LayerMap.Service`, so providing the connection
   layer twice reuses one build. Rule: taste, "Consistent siblings".
2. **This PR adds a third copy of the cached-Catalog Layer and of `connectionLayer`.**
   `connectionLayer` is at `get-receipt-dimensions.handler.ts:93`,
   `get-cached-suppliers.handler.ts:39` and `get-cached-vat-codes.handler.ts:42`; the
   `Layer.effectContext` caches at `:164`, `:80` and `:92`. Rule (modules-and-effects):
   "Add a module only when it … removes current duplication". One shared
   `cachedCatalog({ tag, cacheKey, ttl, schema })` and one `connectionLayer` would serve
   all three.
3. **The "Loaded entries, or none" check is written twice.**
   `catalog._tag === "Loaded" ? catalog.items : []` appears in
   `receipt-dimensions-display.tsx:97` and in `get-receipt-dimensions-view.handler.ts`,
   both added by this PR, and the display cell checks tags one by one
   (`receipt-dimensions-display.tsx:108`) where Effect's `Match.valueTags` would be
   exhaustive. Today's code returns the right result.
4. **The touched display test still mocks framework modules**:
   `vi.mock("next/navigation")` and `vi.mock("@sentry/nextjs")` at
   `receipt-dimensions-display.test.tsx:19,23`. The testing convention moves a touched
   test onto real seams; these two mocks predate this PR.

## Holds up

- `BookkeepingDimensionSchema` matches the `VatCodeSchema` and `SupplierSchema` precedent.
- `Catalog.Plain` with `satisfies` follows the repo's lint rule against explicit return
  types.
- The handler tests use MSW and test Layers, with no module mocks. Typed errors stay in
  Effect channels, and there are no casts.
