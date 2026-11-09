# TypeScript style and safety

Use strict TypeScript settings when practical:

- `strict: true`
- `noUncheckedIndexedAccess: true`
- `exactOptionalPropertyTypes: true`
- `noImplicitOverride: true`
- `noFallthroughCasesInSwitch: true`

Prefer inferred return types for implementation functions. Annotate when defining a public contract or enforcing an intentional boundary. When inference loses precision because of how a generic is shaped, reshape the generic first, such as making the element the type parameter instead of the whole container, and annotate only when no reshaping keeps the exact type.

Prefer immutable values. Local mutation is acceptable inside performance-sensitive code, builders, adapters, or effectful workflows when a precise interface hides it.

## Names

Name things by what they are or do in the domain, in plain words:

- **Constructors**: `make*` for factories and Layer constructors (`makeExportService`),
  not `create*`.
- **Layers**: suffix the role with `Layer` (`testLayer`, `liveLayer`), not a `layer*`
  prefix (`layerTest`).
- **Collections**: `list*` for functions that return many (`listTransactions`), and
  `get*` for one.
- **Vague verbs**: avoid `load*`, `prepare*`, `handle*`, `process*`, and `do*` when a
  precise verb exists.
- **Precise, not exhaustive**: let the verb and one noun tell neighbours apart
  (`getErrorCode` reads a typed value, `decodeErrorCode` parses `unknown`). Leave
  parameter types and call sites out of the name.
- **Provider neutrality**: keep provider names out of domain names. `BankAccount`, not
  `StripeAccount`. Provider names belong in adapters.

## Control flow

Keep functions flat. Replace nested `if` blocks with early returns, guard clauses, or a
lookup table. When branches grow, extract a named predicate or a small function.

## Casts, `any`, and non-null assertions

Keep the type a value already has. A value your code built or a typed API returned keeps that type, never widened to `unknown`, `object`, or a record for convenience. A value already parsed into the type you need passes on unparsed. Branch, parse, or refine instead of `any`, non-null assertions, and casts. A value widened and then cast back, as in `as unknown as T`, is a cast with no evidence: redesign the boundary. `as const` is fine.

Brand a value through a type guard that runs the check, so the check and the brand stay together. The parser returns the narrowed value with no cast:

```ts
function isEmailAddress(value: string): value is EmailAddress {
  return EMAIL_PATTERN.test(value);
}

// In parseEmailAddress, after normalizing:
if (isEmailAddress(normalized)) return normalized;
```

Use a cast only when TypeScript cannot express a checked invariant, such as an interop boundary. Add a focused safety comment that names the runtime evidence and the test that fails if the invariant breaks:

```ts
// SAFETY: <the runtime check or guarantee that makes `value` a `Target`>.
// Verified by: <the test that fails when that check or guarantee breaks>.
const target = value as Target;
```

A rare `any` also needs a targeted lint suppression and safety reason.

## Imports and exports

Prefer direct imports from the file that owns the abstraction. Avoid application barrel files by default. Follow the repository's package-entrypoint rules.

Namespace imports can preserve a domain module's shape. Use named imports for classes and focused helpers. Use `import type` and `export type` for type-only imports and exports.

Export only what callers should use. Keep internal helpers private. Do not export an implementation detail only for a test. Avoid TypeScript `namespace` unless interop requires it.

## Files

Place new code with the module or domain that owns it. Code used only inside one feature
or slice lives there, not in a shared `utils` folder.

Avoid vague names such as `utils.ts`, `helpers.ts`, `common.ts`, and `misc.ts`. Use names that identify the owner or behavior, such as `email-address.ts` or `billing-period.ts`.

Small generic helpers may share an explicit module when they have no more precise owner. Keep domain and application policy with their semantic owner.

Split a file when it has unrelated reasons to change or makes callers understand unrelated concepts.

## Comments and JSDoc

Comments should explain invariants, non-obvious domain rules, external-system quirks, trade-offs, and safety reasons. Do not narrate obvious code.

Use JSDoc when it helps a caller understand a public contract. Good candidates include:

- exported service interfaces and non-obvious operations
- deep modules whose interface hides meaningful behavior or policy
- constructors, parsers, and transitions with constraints that types do not express
- configuration, protocol, or extension points with caller obligations
- public fields with non-obvious meaning, units, lifecycle, or sensitivity

Skip JSDoc when the name and type state the whole contract. Put documentation on the original declaration, not its re-exports.

Use `@throws` only for defects or framework-required throws, not expected typed failures.
