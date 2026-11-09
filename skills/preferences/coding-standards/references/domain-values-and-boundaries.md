# Domain values and boundaries

## Expected failures

Represent each known failure as a precise typed value. A custom tagged error is useful when it adds a stable distinction, domain context, or safe diagnostic data. Do not wrap an existing error type that already expresses the needed failure precisely.

Known failures include domain, parsing, authorization, integration, I/O, persistence, configuration, and workflow failures. A caller must handle them or return them. The outermost boundary translates them into its protocol, such as an HTTP response, CLI exit code, retry decision, dead letter, or startup message.

Use the repository's established error model. Prefer:

1. Effect error channels when the repository uses Effect.
2. `better-result` when it is already available and appropriate.
3. A small local tagged union when neither exists.

Catch unclassified third-party promise rejections inside the owning adapter. Translate them before they cross the adapter boundary. Let rejection escape application code only for a defect.

## Defects

Throw or panic only when an internal defect makes correct execution impossible. Examples include a violated invariant, an impossible branch, or a temporary unimplemented path. A known configuration failure is an expected failure, not a defect.

Use the repository's exhaustive-union and panic helpers. Do not add one-off variants when equivalent helpers exist.

## Error data and telemetry

Keep error unions precise at module boundaries. Avoid a broad `AppError` type except near entrypoints, orchestration, logging, and rendering.

A custom error should have a stable tag, a useful message, structured context, safe telemetry fields, and an optional `cause: unknown` when the source failure matters.

Trace requests, jobs, workflows, adapters, and external calls with safe fields such as domain IDs, operation names, provider names, state tags, retry counts, and error tags.

Never put secrets in errors, traces, logs, or snapshots. Wrap tokens, passwords, credentials, and API keys in the repository's redacted type at the boundary. Unwrap them only where the raw value is required.

## Parse inputs

Parse input once, in the adapter that receives it, when it is truly unknown or less structured: a request body, row, environment value, file, or SDK result. Choose the decoder by what the input already is: a typed decoder when the input's type is the schema's encoded type, and otherwise an unknown decoder such as `Schema.decodeUnknown*`, never a cast to make the types meet. Parsing should return the refined value instead of discarding what it learned.

Add a protocol or persistence type only when its shape or meaning differs from the application input. Name it for its role, such as `CreateUserRequest`, `StripeCustomerResponse`, or `UserRecord`. Do not use `DTO` or `Dto` in symbol names. Do not carry schema-inferred transport types through the application.

Use names consistently:

- `parseX` for untrusted or less-structured input
- `makeX` for smart constructors from typed parts
- `isX` for predicates
- `assertX` only at a framework or test boundary that requires assertion

Use schema libraries at boundaries, not as scattered validators. Use the repository's established schema library. Prefer Effect Schema in Effect codebases, Standard Schema compatibility for generic helpers, Zod 4 otherwise, and a hand-written parser when it is clearer for a small domain type.

## Domain values

Use branded, refined, or domain types when they prevent realistic misuse. Common cases include identifiers, parsed strings, constrained numbers, and units.

Construct these values through parsers or smart constructors. Do not pass raw strings or numbers where a domain type exists.

## Absence

In Effect codebases, domain and application code model absence as `Option.Option<A>`: optional fields, parameters, and return values. Convert `null`, `undefined`, and optional properties to `Option` at the edge that receives them, such as a Prisma row, an HTTP body, or an SDK result. In a schema, pick the transform that matches how the input marks absence: `Schema.OptionFromNullOr` for `null`, `Schema.OptionFromNullishOr` for `null` or `undefined`, and for a missing key `Schema.optionalWith(…, { as: "Option" })` in Effect 3 or `Schema.OptionFromOptionalKey` in Effect 4. Convert back only where an external contract requires that form. React component props and other framework-facing UI types keep optional properties.

A function that requires a value takes `A`, not `Option<A>` or `A | undefined`. Avoid `Partial<T>` as an application or domain input unless partiality is the domain concept.

## State and booleans

Model meaningful lifecycle states with tagged unions or equivalent value classes. Each variant should contain only the data valid for that state.

Avoid boolean parameters that select behavior. Use a named option or domain type instead. Booleans remain appropriate for predicates such as `isExpired` and `hasPermission`.
