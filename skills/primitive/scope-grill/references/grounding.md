<!-- Copy of skills/primitive/grounding/SKILL.md, written by scripts/sync-copies.py: edit the source, then run the script. -->
---
name: grounding
description: "Verifies a technical claim against installed code, primary docs, and project rules. Use when asked whether an API, pattern, or claim is idiomatic, correct, or best practice, when asked \"are you sure?\", or before relying on a recommendation or fix."
metadata:
  layer: primitive
---

# Grounding

**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

Grounding checks one claim and establishes what's true. Project instructions and
convention skills still decide what to do with it.

From the request and the context, name the claim, the target (a package, a tool, or a
design question), and the environment. Ask only when a missing decision would change
the investigation, and keep gathering evidence in the meantime.

**Answering the user directly**, including a challenge such as "are you sure?": read
grounding's `references/answer.md` now, before checking
sources. Loaded as another skill's lens, report in that skill's format instead.

## Sources

Check every row that applies:

| Target | Check |
|---|---|
| Package or library | Which workspace owns the import. The locked, installed version, and its type declarations or source in `node_modules`. Peer packages only when they interact. For an uninstalled package, read the source at the exact version tag and say it isn't installed. |
| Tool or platform | The installed or live version and local config. The tool's `--help`, source, or current official docs. Live state when deployed behavior matters. |
| Design or architecture | The project's docs, ADRs, and domain rules, plus the relevant spec or standard. Add a minimal reproduction when the docs don't settle it. |

When a docs MCP server for the library is connected (for example effect-docs or
context7), use it alongside the installed source.

### Idiomatic and best-practice claims

"Idiomatic" means the way the library's authors intend it to be used. Rank the evidence
in this order:

1. The library's official docs, guides, and examples for the installed version. When
   docs and the installed source disagree, the source wins.
2. The library's own source, tests, and maintained example repos, at the installed
   version.
3. The project's rules: its conventions and ADRs.
4. Repo precedent. This shows consistency, not idiom.

When repo precedent and the library's idiom disagree, show both and say which one the
project's rules favor. To claim one option is best, name the project's constraints and
compare the viable alternatives against them. A comparison, or a claim that no
alternative exists, states the search scope and the date.

## Depth

Keep reading until more reading wouldn't change the decision. Widen the search when
sources conflict or leave a material gap.

- **Uncertain API combinations or runtime behavior**: run a minimal example against
  the installed version before calling it working. Label an untested sketch
  `Proposal`.
- **Experiments**: settle uncertainty with reversible local experiments. Ask only when
  the gap touches user intent, security, external effects, or a public contract.
- **Third-party APIs**: read the vendor's live docs and the installed source. When that
  runs past a page or two, read in a subagent and keep only what decides the question.
  Write notes to a file only when asked.
- **Absence claims**: before saying local work doesn't exist, query by ancestry
  (`git branch -a --contains <head>`) and run `git status` in each `git worktree list`
  entry, since a name search can't prove absence.
- **Capability claims**: before saying a tool or library can't do something, check
  its `--help`, docs, or source.
- **Not checked**: check anything the repo, installed source, docs, or `--help` can
  answer, and leave `not checked: <gap>` for the rest.
- **Open details**: an unresolved implementation detail stays an open question. Keep
  it separate from the verdict on the design.

## Reuse

Reuse verified evidence while the target, the version, the rules, and the relevant
state stay unchanged. Explaining, implementing an accepted decision, drafting comments,
and a final review all reuse it. Recheck only what new code, new state, or conflicting
evidence invalidates, and state a changed conclusion in one line.

**Done when:** every applicable Sources row is checked, and a direct answer follows
`references/answer.md`.
