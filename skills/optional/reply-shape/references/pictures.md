# Pictures in replies

Replies are text: in two rounds of side-by-side picks, every visual format lost to labeled
rows, lists, and small tables. Draw a picture only when the reader asks for one, or show a
screenshot or recording when the subject is UI.

## Mermaid

- It renders in T3 and on GitHub. Terminal output, commit messages, and files show it
  as raw text, so use a text diagram there.
- Before a diagram goes to GitHub, in a PR, issue, or comment, run this skill's
  `scripts/check-mermaid.mjs FILE`, which parses it with the version GitHub renders.
  Fix each block it rejects; quoting the label, as in `A["call (x)"]`, fixes most.

## Inline pages

- Check the exact page you'll publish with `html_preview` at 728px and 390px wide, and
  again after any edit, since the reader may be on a phone.
- The page sits above the reply, so the reply adds only what the page doesn't say.
