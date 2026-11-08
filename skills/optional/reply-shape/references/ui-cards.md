# UI cards

A UI card draws a reply's glance as UI with one `html_render` call: a small JSON
payload that reply-shape's renderer turns into themed blocks. The reader reads the card,
and the text keeps what tools parse.

## When

Draw a UI card only on a final reply the reader reads in a T3 thread that has
`html_render`, when its shape fits the catalog. Every other reply stays plain Markdown:
a mid-turn progress line, a ⏳ `running` reply, a delegated child's report, a harness
without `html_render`, a one-sentence answer, and a shape the catalog can't draw, such
as an interface with its call site or a diff.

## Split

- **Card**: the outcome, the views, the notes worth a glance, and a decision card's
  options. A note goes in the block it's about: a PR's risk as that change's `note`, a
  check or risk as a `checks` item. One that fits no block stays in text.
- **Text**, in this order: the headline line, unchanged (it's the fallback when the card
  can't load), any note the card can't hold, the fold, then `**Next**` and the turn block,
  unchanged, since the kit's hooks and Prefrontal read them. The text adds only what the
  card doesn't say.

## Blocks

`ui/catalog.schema.json` is the source; `ui/examples/catalog.json` shows each block.

| Block | Draws | Fields |
|---|---|---|
| `outcome` | the headline; it opens a card for the blocks after it | `status`: done, risk, blocked, working; `text` |
| `delta` | a measured before and after | `label`, `now`, `was`, optional `bars` of `[label, number]` |
| `change` | one PR | `pr`, `state`: draft, open, fixing, blocked, merged, closed; optional `title`, `sha`, `checks`, `diff`, `note`, `url` |
| `decision` | the options, with `rec` on the pick | `options` of `{key, text, rec}`; optional `question` |
| `table` | a comparison, up to six rows | `columns`, `rows`; optional `pick`, a row index |
| `checks` | a check list, worst first | items of `{status: fail, warn, wait, skip, pass, text}` |
| `flow` | an order of steps | `steps`; optional `label`, `mark` (the end state; default the last step) |

## Call

The bare call, nothing around it, with the URL exactly as written here:

```html
<script src="https://cdn.jsdelivr.net/gh/olivercederborg/reply-ui@v1.1.1/reply.js"></script>
<script type="application/json" id="ui">{"ui":[{"outcome":{"status":"done","text":"Tick CPU spike fixed"}},{"change":{"pr":108,"state":"merged","checks":["verified"]}}]}</script>
```

Give it a short `title` and `height: 2000`, the tool's maximum: T3 measures the card at
each width and fits the frame to it, and only a smaller `height` caps it, so phones would
scroll the rest. A card taller than 2,000 px is too long: split the reply. The
`reply-card` hook refuses a call whose URL or payload is wrong and names the fix;
`scripts/validate-card.py page.html` lists every problem at once.
