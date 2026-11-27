# Type checking

Run `pnpm typecheck`. Compiler flags live in `tsconfig.base.json`, which every
`tsconfig.json` extends.

`noUncheckedIndexedAccess` is on: an indexed read such as `rows[0]` may be `undefined`,
so check it before use.

After you change a flag in `tsconfig.base.json`, delete `.cache/tsbuildinfo.json` once,
or tsc reuses its last result and misses the new errors. CI starts without `.cache/`.
