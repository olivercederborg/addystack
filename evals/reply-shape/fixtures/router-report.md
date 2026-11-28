🟡 **The router is live, and 6 of 7 evals pass. The interface-change eval fails: autopilot skipped architect for a new optional parameter.**

| Eval | Result | What happened |
|---|---|---|
| Personal feature | ✅ (gap) | It went straight to autopilot and pushed a branch with no stops, then ended with Done. The brief logged only 3 of its 6 fields. |
| Interface change | ❌ | It added `delimiter?: Delimiter` to `exportTransactionsCsv` without running architect. No `Shape-` trailers. |
| Franklin repo | ✅ | It took the gated flow: a scope-grill round first, then waited. |
| Address-review stops | ✅ | Bot replies posted. The human reply was drafted and it stopped. |
| Loading, Claude | ✅ | Autonomous mode, measured without changing anything, ended with `Next`. |
| Loading, Codex | ✅ | It read `router.md`, then the principles index, before replying. |
| No-autonomy opt-out | ✅ | It started with a scope-grill round and didn't touch any code. |

**Why the interface eval failed:** its decision log says "one optional field on an internal options type; picked inline, no separate architect run", citing the slim-scope principle. The kit never says whether a new optional parameter counts as an interface change. Your existing autopilot eval (EX-9) assumes it does, since its gate fires on exactly this delimiter change. This is the pre-existing "what counts as an interface" gap that both dry runs flagged. One line in autopilot would close it.

**Needs you**: nothing.

<details><summary>Evidence</summary>

- **Interface change**: `git log` on the eval repo shows commit `19ddcc0` with no `Shape-*` trailers. Decision-log row 7 records the skip.
- **Personal feature**: the decision log's first row is "personal · autonomous · trust draft". The bare origin has `csv-currency-column`.
- **Codex loading**: in the Codex session transcript, the first command is `cat ~/Developer/personal/skills/router.md …`, and the second is `cat …/principles/index.md`.
- **Config files**: switched from the drafts. Backups are in `~/Developer/personal/skills-backups/router-activation-20261015/`. Copying those two files back undoes it.

</details>

---

**Next**

- **`a` → define an interface change in autopilot as any change to an exported function's or type's signature, a new optional parameter included, then rerun the interface-change eval and also log every brief field** · *recommended*
- `b` → keep the agent's call that additive optional fields skip architect, and update the eval and EX-9 to match
