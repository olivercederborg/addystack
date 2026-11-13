# Franklin checklist

The **Standards** lens reads this in a Franklin repo. Route each changed file to its
authorities first, then ask the questions below.

## Route each file to its authorities

For every changed file, read the repo and path instructions that apply, follow their
pointers to the owning convention or workflow, and load any repo skill they name.

- **Repo authorities** own Franklin preferences, such as the legacy-library table,
  comment rules, and naming.
- **Installed source and runtime evidence** own library behavior. Source proves what the
  installed version can do, but doesn't override a Franklin policy that allows or
  rejects a supported pattern.
- **Generic advice** is not an authority.

When two in-scope Franklin authorities disagree, or a written mechanics claim conflicts
with verified source, report an **authority failure** citing both, and don't enforce the
disputed claim.

The questions below focus attention. A finding cites its owning rule and the target
evidence; a pattern with no current owning rule prompts a look, never a finding.

## Ownership and dependency direction

Name the owner of each changed concept. Ask whether its current consumers and change
reasons support that owner. Look for:

- one sibling feature importing another sibling's internal files;
- a shared type or read workflow left under its first consumer after a second consumer
  appears;
- a context, optional dependency, or re-export hiding a dependency inversion;
- optionality hiding an ownership problem;
- a broad port exposing operations only one provider uses;
- a root registry learning provider-specific data, validation, or form details;
- shared bookkeeping or Chift code named after its first provider, such as
  `exactConnectionProps`, where its role (settlement, combined) names it;
- a `serviceType` branch in a shared form or component, where each service type can own
  its form or component.

## Framework-owned lifecycle state

Identify who owns pending, failure, cancellation, retry, and resolved data at each
asynchronous boundary. Verify framework mechanics from the installed version when the
answer depends on them. Look for:

- a data result holding presentation-only `loading` or generic `error` status;
- a server helper returning fallback presentation data for a pending operation;
- a deferred computation nested inside another result when one boundary can own the
  promise or Effect;
- the framework boundary and application data both modelling the same lifecycle;
- an Effect Layer or external client built before a feature, permission, or state guard
  that can skip it.

## Test ownership and layer

Identify the Franklin-owned behavior each added or changed test protects, and which
layer proves it through a stable public boundary. Look for:

- a test restating a Prisma schema declaration, cascade, or library guarantee;
- a browser test invoking Trigger or another worker to prove behavior a lower workflow
  owns;
- the same scenario matrix at several layers without a distinct risk;
- a test-only abstraction larger than the production behavior it protects;
- setup creating data the scenario doesn't use.

## Effect and other library boundaries

Apply the library's repo authority and its version-grounding workflow. Look for:

- synchronous helpers that can throw inside a non-throwing constructor;
- typed failures turned into defects without an explicit invariant;
- runtime execution below the owning entry point;
- type predicates or assertions that promise more than runtime validation proves.
