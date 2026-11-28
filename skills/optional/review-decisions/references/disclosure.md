<!-- Copy of shared/disclosure.md, written by scripts/sync-copies.py: edit the source, then run the script. -->
# Agent disclosure

Every comment or reply posted to GitHub starts with:

```markdown
<sub>`AGENT` {model} · on behalf of **{name}**</sub><br>
```

- `{model}` is the writing model's name as the runtime reports it, without
  context-size suffixes such as `(1M context)` or `[1m]`.
- `{name}` is the user's first name.
- Keep only the segments you can verify, so the posted line is always complete.
  The shorter forms are `` <sub>`AGENT` {model}</sub><br> ``,
  `` <sub>`AGENT` on behalf of **{name}**</sub><br> ``, and `` <sub>`AGENT`</sub><br> ``.
- Keep `<br>` directly after `</sub>` so the body starts on the next line.

Older agent replies start with `🤖 **[Agent]:**`. They count as ours when checking
whether a thread is already answered.
