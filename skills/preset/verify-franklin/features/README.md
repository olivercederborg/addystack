# Franklin web verification map

The maintained source for verifying user-facing web behavior. Read this index, then use
the matching feature file as the recipe.

| Feature | File | Recipe |
|---|---|---|
| Command palette | [command-palette.md](command-palette.md) | `command-palette.ts` |
| Notification settings | [settings-notifications.md](settings-notifications.md) | `settings-notifications.ts` |
| File archive cleanup | [archive-cleanup.md](archive-cleanup.md) | `archive-cleanup.ts` |

## Baseline preconditions

- `scripts/launch.sh` started this run, and `scripts/doctor.sh` is all ✅.
- The seeded owner `dev+local@hifranklin.com` signs in through `/auth/login`, with the
  email OTP bypass code `123456`.
- The active company is "Franklin Test" (the TEST banner shows at the top).

## Driving conventions

- Start every recipe with `signIn(page)` from `../scripts/browser.ts`.
- Prefer ARIA roles and accessible names (`getByRole`, `getByLabel`) over CSS selectors.
  The e2e specs under `apps/web/test/e2e/` show the names each page uses.
- Read a value before changing it, once its control is enabled (Settings controls render
  disabled and empty until the page loads), and restore it at the end.
- Call `proof("<step>")` after each user-visible result.

## Feature entry contract

Each feature file starts with an H1 and one paragraph on the user-visible behavior, then
exactly these four H2 sections:

1. `Sub-features`: short IDs, one line each.
2. `How to get to it (user POV)`: every entry point a user has.
3. `Driving it with verify-franklin`: `Preconditions:`, then labeled bullets pairing
   each action with the recipe step and the observable result.
4. `Gotchas`: traps that waste or invalidate a run.
