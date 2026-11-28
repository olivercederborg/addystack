# Session so far: #5151, a data-access prototype for Johan

Oliver's own franklin-next PR #5151, "[PROTOTYPE] Build data-access repositories from
contracts", is a **draft** with no reviews and no approvals. It's a prototype of an Effect v4
data-access library API that Oliver will share with Johan, whose own draft it reworks
(`Company.make({...})` builds the repository class and its layer). Earlier this session
Oliver asked for it to be more Effect v4 idiomatic, dropped the Prisma `model` and the
for-update lock example, renamed `Request`, and made it compose with the internal
authorization module. The PR is pushed at `c9dcbd1`.

Oliver's last message asked whether anything else could be improved or cleaned up. This
session ran **verify-work** on #5151 (a fresh verifier, at `c9dcbd1`) to answer it. The
verifier's checked facts are below. The severity and call of each is yours to set, as the
skill's format says; reply as that skill's report, ending with your Next options.

## Checks

✅ typecheck · ✅ lint · ✅ prettier · ✅ demo 20/20 · ✅ idioms (coding-standards,
effect-conventions, grounding, taste). Not run: a real Prisma query, since the prototype
runs on a stand-in by design.

## Verified facts

1. **A field marked `notSelectable` can still be returned.** Only TypeScript's
   excess-property check enforces it. A `select` passed as a variable, such as
   `const s = { name: true, sourceBankAccountNumber: true } as const`, compiles, goes to
   Prisma unchanged, and returns `sourceBankAccountNumber: "5678"`. An unknown key fails
   as `Forbidden("company:undefined")`. Today's code loops over an allowlist, so this is
   a regression, and it goes against ADR-0017's "no caller-defined Prisma selections".
   `Resource.ts:100`, `Repository.ts:239`. Confirmed by a runtime probe
   (`Some({ name: "Acme", sourceBankAccountNumber: "5678" })`) and a type probe. Fix:
   build the selected keys from `resource.access`, skipping `notSelectable`, and derive
   both the Prisma `select` and the decoder from them.
2. **The transaction service is named `Transaction`**, the glossary's name for a card
   transaction, and its commit failures carry `resource: "Transaction"`, the same label
   `TransactionResource` uses. `Transaction.ts:19, 40`. `DatabaseTransaction` is taken by
   `@franklin/prisma`; `UnitOfWork` is free.
3. **Two error details are never used.** The `NotFound` reason can't occur, because
   `update` catches P2025 first and the reads never raise it, and
   `ConstraintConflict.target` is never set. `RepositoryError.ts:14, 22`.
4. **Two leftovers.** `const companies = CompanyRepository` only renames the tag, and in
   `types.check.ts` an import sits above the file's doc comment. `demo.ts:83`,
   `types.check.ts:1`.
5. **Read scope isn't applied to updates.** `update` checks read access as a yes/no gate
   and drops the scope it resolves. An authority with `read:scope` plus unscoped `update`
   would get back a colleague's row. Confirmed by a probe. `member-roles.ts` and
   `resource-relations.ts` show no real role has that combination today. `Repository.ts:308`.
   Fix: add the read scope to the row filter.
6. **Scoped field permissions aren't handled.** The field policy uses `Policy.permission`,
   so cards' `read:sensitive:scope` would always be denied. Cards hasn't moved to this
   library yet.
7. **A cast that could be typed.** `` `${op}:scope` as PermissionScope `` could be a typed
   `{ read: "read:scope", update: "update:scope" }` map.
8. **An unproven PR claim.** The PR body says `Transaction.withTransaction` works and that
   `DatabaseClient.current` picks up the transaction client, but nothing runs
   `withTransaction`. One demo scenario with a fake transaction runner would cover both.
