---
name: tidy
description: Simplify completed code changes before review, or when requested, without changing behavior. Keep the pass within the current task or specified diff.
metadata:
  layer: primitive
---
**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

Review the diff against the PR base or parent branch (`git diff <base>...HEAD`), or the scope the user specifies. Apply these criteria without changing behavior. Only touch code in that scope, and run the relevant existing checks after changes.

Where the repo's conventions or lenses cover the same point, such as names, comments, or file layout, follow them over this skill.

## Word choice in code and comments

Variable names, function names, and comments are all prose. Apply Orwell's rules ("Politics and the English Language") to each:

> Never use a long word where a short one will do.
> 
> If it is possible to cut a word out, always cut it out.
> 
> Never use the passive where you can use the active.
> 
> Never use a foreign phrase, a scientific word, or a jargon word if you can think of an everyday English equivalent.

Latinate vocabulary (reconcile, coalesce, normalize, reconciliation) sounds technical and abstract; Anglo-Saxon words (prune, run, watch, stop, drop, walk) are short and physical. Prefer the Saxon word.

### Names

1. **One word per concept, one concept per word.** Keep a vocabulary. If `sync` names "pulling remote changes," it cannot also name "flushing edits to disk;" rename one of them.
2. **Cut words the context already carries.** A module named `workspaceWatcher` does not need `startNativeWorkspaceWatcher`; `watchWorkspace` says the same thing.
3. **A compound name is usually a hedge:**

- ❌ `lastObservedDiskContent` is a specification to defend
- ✅ `baseline` is a readable description

### Comments

State, in plain English, the constraint the code cannot show: why the **non-obvious** exists.

- ✅ If code is complex and the implementation is non-obvious, add a comment.
- ✅ If a function contains complex behaviors or side effects, add a doc comment.
- 🗑️ If a comment narrates change history from the conversation or restates code whose behavior is self-evident, delete it.

## Code structure

Make these moves inside the code the change touched. A move that reaches past it, such as splitting a file the change edited one line of or merging a type other code owns, goes in the report as a suggestion.

1. **Inverted pyramid.** Within a file, lead with the exported or significant functions and push helpers below them. Don't bury the lead.
2. **Related concepts over monoliths.** Split a file that holds two concepts with separate callers into one module per concept.
3. **Combine overlapping concepts.** If two types, functions, or constants hold the same fields or do the same job for every caller, merge them. The fewer distinct concepts a reader must hold in their head, the better.
4. **Use shared code.** Check for an existing library or utility function (ex. file path parsing) before inlining one.
5. **Derivability.** If a value can be computed from values already in scope, don't pass or store it separately. Removing derivable state often simplifies signatures, types, and control flow in one move. Example: an `isDirty` parameter that is always `editorContent !== baseline` can be dropped.

## Overfitting

Code must stand on its own. A change that only makes sense to someone who watched it happen (this conversation, this PR) is overfitted. Write for the reader who arrives with no history.

- If a name or comment needs the conversation to be understood, rewrite it against the codebase's own vocabulary.
- **No backwards compatibility with unshipped code.** An old signature, alias, or data shape that only existed earlier in the same branch was never deployed: delete the old path and update its callers.

## Report

List what you changed, file by file, and the suggestions you left for the user.

**Done when:** every changed file was checked against each section above, the existing checks for that code pass, and the report names both the changes and the suggestions.

