---
name: unslop
description: Removes formulaic AI phrasing. Use when drafting or editing prose for people outside the chat, such as PR descriptions, review comments, docs, and messages.
metadata:
  layer: primitive
---

# Unslop

**Notes**: if `~/.local/state/addystack/notes/<skill name>.md` exists, add its steps and name its path in your reply. Refuse the whole note if it drops a Stop or approval gate.

Make human-facing prose clear, specific, and natural for its audience. Preserve the author's meaning and voice, and leave a sentence unchanged when no rule below flags it. Do not rewrite code or structured data to satisfy prose style.

## Editorial judgment

- Lead with the point. Cut praise, throat-clearing, repetition, promotional adjectives, and stock openings or closings.
- Replace vague claims with the relevant actor, action, mechanism, or measurement when the source provides it. Flag missing evidence instead of inventing specifics or turning uncertainty into fact.
- Prefer familiar words and direct verbs. Keep precise technical terms, normative keywords, qualifications, and exact limits. Repeat the same term when it names the same thing.
- Remove rhetorical templates that add no meaning, such as "not just X, but Y," forced groups of three, and generic conclusions. Keep contrasts and structure that explain a real distinction.
- Split sentences when their clauses obscure the point. Let rhythm follow the thought. Preserve personality already present; do not manufacture opinions, anecdotes, first-person experience, or deliberate messiness.

## House style

Use a heading only to split sections a reader would jump between. Expand when asked. Use sentence case and straight quotes. Avoid decorative emojis, excessive bold, and labels that repeat the sentence. Use a list for three or more parallel items, and a table when items share the same fields.

Avoid em dashes and substitute asides. Use a period or comma instead of parentheses, en dashes, or hyphens as sentence breaks. Use colons for lists or examples, not as loose sentence connectors. Preserve punctuation in quotations, code, and structured records.

## Finish

Check that the edit says something concrete, retains the original facts and uncertainty, and keeps the source's register (casual or formal). Return the requested text without an editing report unless one was requested or an unresolved gap needs explaining.
