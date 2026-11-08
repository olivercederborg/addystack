# Domain docs as you go

Read from scope-grill when an answer touches the glossary or may need an ADR.

- **Glossary conflicts**: when the user's word conflicts with the glossary, or is fuzzy
  (for example, "account" could mean Customer or User), ask which they mean.
- **Terms**: when an answer settles a domain term, show it inside that question's fold
  as a one-line addition to `CONTEXT.md`, and write it when the user accepts the round. A term never
  gets its own question. `CONTEXT.md` stays a glossary, with no implementation details.
- **ADRs**: offer one, as an ADR option in that turn's `Next`, only when a decision passes all
  three tests:
  1. It's hard to undo (the winning option's cost line says so).
  2. It's the result of a real trade-off (a losing option has a "becomes worth it when"
     line).
  3. A future reader would be surprised without the reason.
- **File formats**: use `domain-modeling` for file formats and for repos with several
  contexts, when it's installed. Create files only when there is something to write.
