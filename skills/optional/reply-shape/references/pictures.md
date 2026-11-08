# Pictures in replies

How to draw a Mermaid view, or the turn's one picture: an image or an inline page. Keep a
diagram to five boxes or fewer, and keep a list or a run of steps as text.

## Mermaid

- It renders in T3 and on GitHub. Terminal output, commit messages, and files show it
  as raw text, so use a text diagram there.
- Before a diagram goes to GitHub, in a PR, issue, or comment, run this skill's
  `scripts/check-mermaid.mjs FILE`, which parses it with the version GitHub renders.
  Fix each block it rejects; quoting the label, as in `A["call (x)"]`, fixes most.
- Color nodes with `classDef bad fill:#fdecec,stroke:#e5484d,color:#7f1d1d`,
  `classDef hit fill:#fff4d6,stroke:#d4a106,color:#713f12`, and
  `classDef good fill:#e8f7ee,stroke:#30a46c,color:#14532d`.

## Inline pages

- Check the exact page you'll publish with `html_preview` at 728px and 390px wide, and
  again after any edit, since the reader may be on a phone.
- The page sits above the reply, so the reply adds only what the page doesn't say.
