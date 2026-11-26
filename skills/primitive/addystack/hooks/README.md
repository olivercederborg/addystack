# Claude Code hooks

Hooks for steps a wrong call can't take back: a merge, marking a PR ready, a push that
dismisses an approval, a dropped review watch, agent spend,
and this machine's keychain and memory, plus the session-start hooks that load the reply
rules and keep the kit current. A rule with exceptions, reply format included, stays in
the instructions: "Every hook and deny rule will occasionally fire when it shouldn't"
([best practices](https://code.claude.com/docs/en/best-practices)), and a Stop hook that
sends a reply back makes the agent post it a second time.

| Hook | Runs on | What it does |
|---|---|---|
| `reply-shape-context.py` | SessionStart, in Claude Code and Codex | Loads the `reply-shape` skill at every session start, resumes and forks included, when `replies.style` is `reply-shape`. A resumed session can hold two copies, which costs less than losing the rules. A second SessionStart entry, `reply-rules`, runs it with `--rules` to load the file `replies.rules` names, when one is set; a missing file loads nothing, and `addystack doctor` reports it. They stay two payloads so each fits the 10,000-character hook limit. Subagents don't run SessionStart hooks, so they skip both. T3 delegated child tasks skip both too, unless a line of their brief starts with `Reply rules: on`; it finds them in T3's state database and loads the rules when it can't read it. A coordinator's worker on a linked machine counts as a child, found by the `Worker of:` line in its agent-written first message. |
| `skills-checkout-check.py` | SessionStart, in Claude Code and Codex | Fast-forwards the skills checkout that Claude Code's skill folder (`$CLAUDE_CONFIG_DIR/skills`, else `~/.claude/skills`) links into when it's a clean `main` behind `origin/main`, then reruns `addystack build` when its files are stale and tells the session to read the rebuilt ones. Otherwise warns: on `main` with local changes every session, on another branch once a day per branch. Also warns on hook drift from `manifest.json` (see Install). |
| `keychain-home-guard.py` | PreToolUse, `Bash`, on macOS | Denies a command that points `HOME` at another folder and runs `claude`, `gh`, `security`, `yadm`, a bootstrap script, or a git network command, since macOS then can't find the login keychain and shows the user a "Keychain Not Found" dialog for each write. On Oct 26, 2026 a verifier testing dotfiles bootstrap step 45 under `HOME=$(mktemp -d)` popped it repeatedly. Replayed on the 800 most recent transcripts, it denies all 17 commands that ran a writer under a fake home, including `HOME=$(mktemp -d)`, a heredoc fed to `bash`, and `bash $STEP`, and allows the 36 others, which read files, keep the real home, or run on another machine. It misses a writer behind a script or shell function that doesn't name it, or in a script a shell gets as a string or a pipe (`bash -c '…'`, `cat <<EOS | bash`). |
| `merge-gate.py` | PreToolUse, `Bash`, in Claude Code and Codex | Denies `gh pr merge` and `gh stack merge` unless each PR's checks ran and passed, the default branch is green, a fresh `work-verifier`'s latest verdict for that exact diff is Done (`verdicts.py`, which records Not done and Not verified too, so a later one revokes a Done), and its base branch gained no commits since it branched that touch files it changes. A command that writes out more than one merge is denied, since the checks read one; one merge that `xargs` repeats isn't caught. In a repo with no files in `.github/workflows`, or whose workflows' path and branch filters all skip the PR (`workflow_triggers.py`, which counts a workflow it can't read as running), a PR with no checks passes the checks part only when the latest prompt is the user's own and asks for the merge, or, with no workflow at its base, head, or default branch, when the checkout's trust resolved to `gate` (`resolved.py`) and the command is a merge line of the form `stack.sh where` prints. That's stricter than `merge on go`, which also counts the go that started a run. A go is a short literal request, matched whole by `merge_go.py`, such as "merge it", "a, and merge them", "merge both stacks please", "merge #92 through #112 into main", "lets get the final PRs merged", or "lets merge it?"; or a key, such as "a", that picks an option the reply it answered classes `stop:merge` in its turn block, whose text is itself a literal go, so "mark #17 ready, but don't merge" isn't one, and which names the PR being merged or no PR. The reply a key answers is the last one before it, past messages T3's database says another agent sent in the same turn, such as a worker's result that arrived as they typed, whose own turn blocks never count, and past a command Claude Code runs itself, such as `/compact`, with its output: on Nov 16, 2026 the compact rows read as a prompt nothing answered and cost the user a typed go; in T3, a session no T3 thread owns gives no go. A denial says what a key picked and why it isn't a go. The reply's raw HTML refuses a key only where it could hide the turn block (`turn_block.py`), such as an open `<title>`, a comment, or a line that starts an HTML block with no blank line after it; a `<code>` in a fold's summary or `Option<T>` in inline code doesn't, and on Nov 17, 2026 one had cost the user a typed go. A question about whether to merge, a refusal, an if-clause first, another step before or after the merge (verify, rebase, deploy, release, try it out), a pick of an earlier reply's option, a T3 delegated child's brief, and T3's state database when it can't be read give no go. Of the 33 prompts the gate denied for want of a go from Oct 11 to Oct 29, 2026, on the Mac and a Linux machine, earlier rounds of this matcher read 10 as a go and this one reads 10 more, such as "merge both stacks please"; the 13 left name no merge, ask whether to merge, open on an if-clause, add a step before or after the merge, or pick an option whose text adds one. Of all 7,923 prompts typed there from Sep 23, it reads 90 as a go, the 75 the matcher before it read and 15 more, each a real merge request; `MergeGo` in `test_hooks.py` holds the replayed prompts with their sources. Of the 36 `stop:merge` options in those replies that offer a merge, 14 add another step, as in "merge #90 and deploy production from the main checkout on main", so picking one gives no go. GitHub can't require checks on private repos on a free plan; on Oct 11, 2026 a Strict stack merged 11 minutes after `main` went red, and a noyer PR merged with no CI or final verify-work. `merge-gate.py --dry-run '<merge command>'` runs the same checks from the current directory and prints each reason or `would pass`. A denial names the go to ask for, and a merge from the wrong checkout points at `shared/scripts/stack.sh where`. |
| `verdict-stamp.py` | PreToolUse, `Bash` | Passes a `work-verifier` subagent's identity, which only hook input carries, to `record-verdict.sh`; the recorder refuses any other caller. pstack's rule: no owner merges on its own verdict. The recorder also refuses a Done until the change carries the evidence its type needs (`evidence.py`: a capture for UI, a base-and-head comparison for a refactor, mutants on money and auth paths, and so on). In the user's Oct 2026 audit, about 10 claims of done or fixed weren't, and verify-work hadn't asked for UI or deploy evidence. |
| `ready-gate.py` | PreToolUse, `Bash`, in Claude Code and Codex | Denies `gh pr ready`, `gh stack submit --open`, and `gh pr create` without `--draft` unless review-loop recorded a result for each PR's current diff (`verdicts.py review`, in verify-work's store, matched on patch-id): the rounds it ran, or a skip, whose reason the user sees. The denial names the head with no result. R58 (Nov 2026) found no review-loop on three work-repo PRs a teammate later caught bugs in. |
| `push-gate.py` | PreToolUse, `Bash`, in Claude Code and Codex | Denies `gh stack push`, `gh stack submit`, `gh stack sync`, and `git push` when a PR the push moves has a live approval: a reviewer whose latest review that isn't a comment is APPROVED, which a repo that dismisses stale approvals on push then dismisses. A PR counts only when its branch's local tip differs from the PR's head, or a sync would rebase it, so an unchanged branch passes. Only the user's latest prompt allows it (`user_turn.py`, the T3 logic merge-gate uses): a pick of a `stop:push` option or a typed request, either one at most 200 characters and the shape the denial suggests, "push #N (dismisses X's approval)": a push verb (push, force-push, restack, rebase, sync, or submit), naming each PR (#N), or none for a lone approval, then the dismissal, which may instead list every PR whose approval goes ("on #N and #M"), and only steps such as post, reply, or resolve, with no refusal, condition, question, or modal such as "would". The same push typed without the dismissal counts right after a reply whose `stop:push` option is such a go (`push_go.py` holds the grammar). A pick of another class, a T3 delegated child, and T3's state database when it can't be read give no go. PushGate in `test_hooks.py` replays the Nov 24, 2026 pushes that dismissed an approval and the Nov 26 goes the gate refused three times. The denial names each PR, its approver, and the review's time, and the option to ask for. It reads gh stack's branches from `gh stack view --json` and the remote gh stack picks, git push's from `git push --dry-run --porcelain`, skipping a remote off github.com, and each branch's PRs from GitHub, on its repo or the repo it forks. A branch move earlier in the same command counts the PR as moved. `push-gate.py --dry-run '<push command>'` prints each branch it would push and the verdict. Its docstring lists the known limits, such as a push through a script or `bash -c`, and it assumes the repo dismisses stale approvals. |
| `child-fast-mode-off.py` | PreToolUse, T3's `delegate_task`, `create_threads`, and `t3_thread_launch`, in Claude Code | Turns Claude fast mode off in the thread an agent starts, through `updatedInput`, so only threads the user starts themselves run fast; a child otherwise inherits the parent's `fastMode: true`. Fast mode measured 2.78× output speed at 2× price, billed to usage credits, and in the 30 days to Oct 30, 2026, agent-started threads and children cost about $6.3k at standard rates, against $5.7k for threads the user started. Claude transcripts from Sep 30 to Oct 31, 2026 hold 2,067 `delegate_task` calls in 228 sessions (8 named fastMode) and 79 `t3_thread_launch` calls in 32 sessions (73 passed no `modelSelection`), counted once per tool_use ID. It adds `fastMode: false` to `target.options` or `modelSelection.options`, keeping a dict a dict and a list a list, which T3 merges over the inherited options, so the inherited effort stays; an empty one, an explicit clear, stays as it is, since T3 runs a cleared selection with fastMode off. It adds it only for a model whose T3 catalog entry (`model-manifest.json`) offers fastMode, by slug or alias such as `opus`, since T3 rejects the option on Sonnet, Haiku, and Fable; a target without a model runs the parent's. A launch without `modelSelection` gets a copy of the parent thread's, from T3's state database, with fastMode off. A target or parent on another provider passes unchanged. It returns no permission decision, so the session's permission mode decides the call, auto mode's classifier included; Claude Code 2.1.314 applies an `updatedInput` that comes without one, and an "ask" would stop an auto-mode thread at a prompt. Known limits: Codex parents aren't covered, since the hook is in Claude Code's list only, and a call that runs the parent's model, a launch without `modelSelection` or a target without a model, passes unchanged when the database can't be read or no single thread owns the session, as does every call when the catalog can't be read. It compares provider IDs, model names, and option IDs as written, where T3 trims them and matches aliases in any case, and it wants every provider field of a launch to name Claude, where T3 takes `instanceId` over a legacy `provider`; none of those 2,146 calls padded, capitalized, or mixed them. |
| `unwatch-gate.py` | PreToolUse, T3's `unwatch_pull_request`, in Claude Code | Denies dropping the watch on an open, ready (non-draft) PR the user wrote, unless the user's latest prompt asks to stop watching, typed or as the text of the option its key picks (`user_turn.py`): at most 200 characters, and the whole text a request to stop watching with its PRs, naming this one or none (a URL on its host, owner, repo, and number), as push-gate reads a push go, so "stop watching #6226" or "can you unwatch PR #6226?" is one and "why did you unwatch it?" or "the unwatch was a bug" isn't. Such a PR waits on reviewers, and the watch is what wakes the thread on a review. The denial says to re-watch with `until: "checks"`, which returns the thread to the user's inbox once checks finish and keeps waking it on reviews. A merged or closed PR, a draft, another author's PR, and a T3 delegated child pass. On Nov 25, 2026 babysit's old Done step dropped the watch on a work repo's #6226 at hand-back with two reviews pending; Claude transcripts from Oct 17 to Nov 25 hold 771 unwatch calls, 283 of them on 86 open, ready PRs of the user's, none after a prompt asking to stop watching. It reads the PR from `gh pr view` and the user from `gh api user`, and fails closed, which leaves a watch on. `unwatch-gate.py --dry-run '<PR url>'` prints the verdict. |
| `agent-memory-guard-notice.py` | PostToolUseFailure, `Bash` | When `agent_memory_guard.py` killed the command, tells the agent why and not to rerun it as is; otherwise the agent sees exit 1 with no output. |
| `watch-reminder.py` | PostToolUse, T3's `pull_request_update` and `pull_request_create`, and `Bash`, in Claude Code | After a call that leaves a PR waiting on reviewers, tells the agent to watch each open, ready PR of the user's it left with `until: "checks"` before ending the turn: `pull_request_update` with `ready: true`, `state: "open"`, or `requestReviewers`, `pull_request_create` without `draft: true`, or a command running `gh pr ready`, `gh pr reopen`, `gh pr edit --add-reviewer`, `gh pr create` without `--draft`, or `gh stack submit --open`. On Nov 25, 2026 an agent requested two reviews on a work repo's #6215 and ended with no watch. It reads the command as text, so a quoted `gh pr ready` reminds too, and skips a T3 delegated child, whose owner holds the watch. It never blocks. |
| `card-check.py` | Stop, in Claude Code | Sends a reply back once when its turn block offers a `stop:push` option that asks for a push and says it dismisses an approval but isn't `push_go.literal_go`, so the agent rewords it before the user's pick is refused at push-gate. Whether a push dismisses an approval depends on reviews the reply can't see, so an option naming no dismissal passes, as do one whose every push verb is declined ("don't push …", "skip the push") and every `stop:merge` option, since merge-gate reads the go only for a PR with no checks; one with a condition, modal, or `no:` lead goes back. Of 1,198 push and merge cards on two machines from Nov 18 to 26, 2026, it flags 21 push options. T3 shows the first card as it streams; the resent one is the one a key answers. `stop_hook_active` keeps it to one send per stop, and any error passes. |
| `cleanest-ask.py` | Stop, in Claude Code, only when `hooks.enable` names `cleanest-ask` (review threads) or `cleanest-ask-impl` (`--scope implementation`: every other top-level thread) | When a review-teammate-pr thread (titled `◎ #`) stops on a `review` or `decide` need, queues `/cleanest` as its next turn with `t3 thread send`, so the agent answers the user's "is this the cleanest, best and most idiomatic long-term solution?" before they type it. Install links `commands/cleanest.md`, that sentence, into Claude Code's `commands/` while either id is on. T3 adds no "not the user" note to a slash command, so the agent gets what typing it gets; T3's database still names an agent as sender, and the text is no go. Once per run, the turns since a reply that ends `done`; it skips children, workers, and T3 workflow steps, a latest prompt that's neither the user's nor a notice that a child or background task finished, and a run that already asked. In the week to Nov 25, 2026 the user typed the question in 50 of the 85 review threads they typed in on one machine. A Stop hook's system reminder and a fork's directive found less than the typed question (R184, R186). Replayed on 29 cards, `/cleanest` found the live fix in 30 of 57 trials and changed a sound card in 13 of 30, between the typed question's two runs (10 and 14) (R186). In the implementation scope, such as a coordinator thread, it fires only when option `a` is a `decision`, `stop:merge` or `stop:push`, a run also starts at each prompt the user types that isn't the ask, and needs one, so a scheduled task's run doesn't ask: the user asked on 47 of 1,168 stop cards there in the week to Nov 25, 2026, about 1 in 20 of every card shape, and coordinator replies rarely end `done`. Replayed on each of that week's cards on both machines, it sent on 362: 23 of the 47 the user asked on and 339 of the 1,121 they didn't, none to a review thread, child, worker or workflow step, and none twice in a run (R188). Each send, and each skip of a card that can fire in a thread in its scope, goes to `cleanest-ask.jsonl` in the state folder with its `scope`; `--dry-run` prints the decision. Known limits: an agent reading the thread can't tell its turn from the user's, each card's answer comes about 80 s later, a re-review before the run ends `done` doesn't ask again, a skill named `cleanest` would run in the command's place, and a link left from before the kit moved and was rebuilt stays, pointing nowhere. |

`turn_block.py` isn't a hook: it parses the turn block that ends each final reply, as [`references/turn-block.md`](../references/turn-block.md) specifies it, for `merge-gate.py`.

`shell_dirs.py` isn't a hook: it follows a command's `cd`, `pushd`, and `popd` for `merge-gate.py`, `ready-gate.py`, and `push-gate.py`, so each reads the checkout a merge, ready, or push runs in the same way.

## Install

`manifest.json` lists every hook the kit ships for `~/.claude/settings.json` and
`~/.codex/hooks.json`, with its event, matcher, timeout, and `onFailure`. Each entry also
has an `id`, `tags` (`safety`, `workflow`, `replies`, `machine`, or `trial`, which only
`hooks.enable` installs), an optional
`requires`, and a command that starts with `{{kit}}`. `lib/hookset.py` selects the
entries your addystack config installs: the `hooks.preset`'s tags (`recommended` is
safety and workflow, `all` adds replies and machine), then `requires`, a Resolved path that
must be truthy (`reply-rules` needs `replies.rules`), then
`hooks.enable` and `hooks.disable` by id, then `hosts`. An entry with `hosts`, such as
`["darwin"]` for the macOS-only `keychain-home-guard.py` and
`agent-memory-guard-notice.py`, applies only on those host profiles: `darwin`, `linux`,
or `sandbox` (a Linux host, so `linux` entries apply there too). `{{kit}}` becomes the
built config's kit path, as `~/…` under your home. The two scripts below read the built
`resolved.json` (`addystack build`), or the kit's defaults, the `recommended` set,
without one. `addystack install` merges the selection into both files; to preview one, render it
instead of editing it by hand, from the kit (the addystack skill's folder):

```sh
python3 hooks/render_hooks.py --runtime claude --profile darwin --into ~/.claude/settings.json --out /tmp/settings.json
python3 hooks/render_hooks.py --runtime codex --profile linux --out /tmp/hooks.json
```

`--into` keeps every other key of the file and every hook the kit didn't install, in place, and the output keeps the committed files'
format, so a diff shows only hook changes. Each event's hooks keep the manifest's order,
and consecutive entries with the same matcher share a group. Codex trusts a hook by its
position, so keep the manifest in the installed, trusted order: moving an entry
untrusts it on every machine. Each entry lands under its event in this shape:

```json
{ "matcher": "Bash", "hooks": [{ "type": "command", "command": "~/.agents/skills/addystack/hooks/merge-gate.py", "timeout": 60, "onFailure": "block" }] }
```

Every command runs its script from the kit, so no hook needs a link. Links an older
install made into `~/.claude/hooks/` and `~/.codex/hooks/` show as extra entries until the
file is rendered again; Codex then asks to trust each changed entry once. `addystack
install` also links `~/.claude/agents/work-verifier.md`, which `verdict-stamp.py` needs,
to verify-work's copy. Then check the machine:

```sh
python3 <kit>/hooks/hook_parity.py --codex-trust   # <kit>: the addystack skill's folder
```

It prints one line per drift, a missing, extra, changed, or reordered entry, or a
command whose script doesn't exist, and exits 1 on any. It compares only the hooks
addystack installs, a command in the kit's `hooks/` or named like a manifest script, so
your own hooks are never drift. `--profile` picks the host profile whose
entries to expect; the default, `auto`, is `darwin` on macOS, `linux` elsewhere, and
`sandbox` when `SBX_SANDBOX=1`. An installed entry the manifest declares only for
other hosts isn't drift. A missing `~/.codex/hooks.json` counts only
when `codex` is on PATH. Codex runs a new or changed entry only once it's trusted, so
`--codex-trust` asks `codex app-server` for each entry's trust; trust any it names by
opening `codex` and running `/hooks`. `skills-checkout-check.py` runs the same check,
without `--codex-trust`, at every session start, and warns on drift.

`merge-gate.py`, `verdict-stamp.py`, `ready-gate.py`, and `push-gate.py` have `"onFailure":
"block"`, so a crash or timeout denies. Codex has no `onFailure`, so there a merge-gate or push-gate crash or
timeout lets the merge or push through. After installing `reply-shape-context.py`, remove the `reply-shape`
import and the Replies and Next sections from `~/.claude/CLAUDE.md`, and the reply rules
from `~/.codex/AGENTS.md`, so sessions don't load them twice.

Codex sends Bash commands to PreToolUse in Claude's payload shape, so `merge-gate.py`,
`ready-gate.py`, and `push-gate.py` run there unchanged. Codex also gives hooks
the session's cwd and never `exec_command`'s `workdir`, and a T3 thread's cwd is a
scratch folder. A command that reaches its repo only through `workdir` gets checked
against the wrong repo: `merge-gate.py`
denies with "not a git repository" or checks the wrong PR. Start such commands with
`cd <checkout> && …` on a literal, unquoted path, which the gates read.

## Agent memory guard

`agent_memory_guard.py` isn't a hook: it's a launchd agent that kills an agent's runaway
command before it freezes the Mac. Every half second it attributes each process to the
`claude` or `codex` command that started it and SIGKILLs a command over 600 processes or
20 GB of footprint, or the biggest when agent commands together pass 1,500 processes or
28 GB. On Oct 15, 2026 a stress script with a broken parallelism limit started about
4,500 node processes and froze the Mac; a hook couldn't see inside the script, and
addystack's Bash hooks mostly don't run in Codex. It also kills an abandoned command,
one whose shell is gone, once it averages over half a core for 30 minutes: on Nov 2,
2026 ten Vitest fork workers, orphaned by an agent's `pkill` of hung runs, spun at 100%
CPU for 15 hours. Its docstring lists the known limits.

From the kit's folder, install it, and the kernel backstop for fork storms in agent shells:

```sh
# An older install may run the guard under another label: stop it and remove its plist first.
launchctl list | grep agent-memory-guard  # then: launchctl bootout gui/$(id -u)/<that label>
# Fill {{kit}} and {{home}} through plistlib, so a path holding & or < stays valid.
python3 -c 'import plistlib, sys
fill = lambda v: {k: fill(x) for k, x in v.items()} if isinstance(v, dict) else [fill(x) for x in v] if isinstance(v, list) else v.replace("{{kit}}", sys.argv[1]).replace("{{home}}", sys.argv[2]) if isinstance(v, str) else v
sys.stdout.buffer.write(plistlib.dumps(fill(plistlib.load(open("hooks/agent-memory-guard.plist", "rb")))))' "$PWD" "$HOME" \
  > ~/Library/LaunchAgents/addystack.agent-memory-guard.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/addystack.agent-memory-guard.plist
# in ~/.zshenv: fork fails past 3,000 user processes in agent shells; GUI apps keep 8,000
[[ -n $CLAUDECODE || -n $T3CODE_CLI_PATH ]] && ulimit -Su 3000
```

Kills go to `~/Library/Logs/agent-memory-guard.log`, a notification, and, through
`agent-memory-guard-notice.py`, the agent. After editing the guard, restart it with `launchctl kickstart -k gui/$(id -u)/addystack.agent-memory-guard`.
