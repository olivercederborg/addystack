---
name: review-artifact
description: "Builds a PR's review artifact: a one-page visual technical document of what the PR changes, with a Markdown copy for AI reviewers, published on Lakebed. Use when a PR needs a review artifact or review document, or open-pr's Review guide links one."
compatibility: Requires git, gh, Node 22.18+, and Playwright's Chromium. Publishing needs the use-lakebed skill and a Lakebed login.
metadata:
  layer: optional
---

# Review artifact

A review artifact **explains** a PR to an engineer in about a minute. It's a visual
technical document: an engineering write-up with diagrams of the real system, read top to
bottom. One idea per visual. Show the change instead of describing it, and keep text as
captions. Evidence lives in the Verified rows and the fold, beside the explanation.

The approved page is [`assets/example/`](assets/example/), and
[`assets/example/desktop.png`](assets/example/desktop.png) shows it rendered. Match its
structure and its bar, not its content.

<!-- toolkit-format:start (edit shared/format-pointer.md, then run scripts/sync-format.sh) -->
**Chat format**: read [`references/format.md`](references/format.md) first, and again
before you report if its text has left your context.
<!-- toolkit-format:end -->

## The format

**Layout** comes whole from [`assets/page.css`](assets/page.css), which the build embeds:
the system note's spec sheet, read like a datasheet rather than a column of rows. A caps
mono running head, a big title beside the verdict, a strip of numbers, then numbered
sections, each a heading and one line over a full-width framed figure or a spec table. An
8px rhythm, hairlines, mono for names and values, and ink, greys and one accent, which
marks only what's new. Each frame has crop marks, a caps bar reading `Fig. n — <label>`
with grey meta on the right, and a dot-grid body that centres the drawing: 640px on
desktop, 358px on a phone, where the frame bleeds to the screen edges. Geist and Geist
Mono are embedded in full, and the build adds a footer with the font notice. `extra.css`
may place a page's figures, using only the template's tokens.

**Structure**, in this order:

1. **Running head**: `header.bar`, the repo and "review" on the left, the PR links and
   their base on the right.
2. **Hero**: the title, and beside it one verdict-first sentence that opens with a bold
   verdict and gives the exposure: "**Safe to merge dark.** Export V3 now exports Dinero
   receipts, but no company has `EXPORT_V3_DINERO`, so every Dinero export stays on V2."
   With no gate, the verdict says who gets the change and when.
3. **Specs**: 2–4 numbers that sum the PR up, each over a short mono caption: who's
   exposed, how many PRs, the test and parity counts.
4. **Ruler**, optional: the rollout's 3–6 steps, with this review's step as `.now`. Leave
   it out when the PR ships whole.
5. **One section per changed behavior**, headed in plain words ("Route", "Currency"):
   one line only when the figure needs it, then at most one framed figure of the real
   behavior, then an optional `ol.notes` row of 1–3 short notes, each opening with a bold
   lead.
6. **Decisions**: forks, one per call: the option picked over the one passed up, each
   with what it means ("`EXPORT_V3_DINERO`: on for no company" over "`EXPORT_V3`:
   already on for 214 companies"). The passed-up option's cost is the reason, so there's
   no why column.
7. **Verified**: a spec table, Check · At · Result, each row at its commit. Evidence with
   no commit, such as the author's manual run, goes in the fold's evidence, marked so.
8. **Not verified**: a spec table, Gap · Covered, naming what would show it.
9. **One fold** at the end, for the code, mapping tables, and evidence: the path through
   the code, the key excerpt with the few lines that carry the change in `.new` (even
   when the whole excerpt is new), tables of outcomes or field mappings, notes, and the
   evidence list with heads.

**Figures** draw what the behavior does, using the real names and values, so the reader
compares pictures instead of reading:

- **a split** by default, for any behavior with a before and an after: two panes side by
  side, labelled with who sees each ("Flag off · every company today", "Flag on · no
  company yet"), each a drawing at most 358 wide, so the same panes stack on a phone.
  For a gate, the before pane is the switch off and the after pane the switch on (`gate(x,
  y, { on: true })`);
- **review pins**, 1–4 on a page with figures: `pin()` puts a numbered accent dot on the part a
  reviewer should check (the gate, the posted line, a new string), and the fold heads
  the code behind it with the same `<span class="pin">n</span>`. Pins point at risk,
  not at everything new;
- a gate in a single drawing as a switch in its real state, with the path taken today
  solid and the gated path dashed (with no gate, every path is solid);
- what moves where: a file, a returned ID as an accent token, each call's endpoint set
  on its line;
- what lands in an external system as a faithful mini mock, captioned "Illustration of
  the posted request, not a Dinero screenshot";
- before and after states as cards in a `.frame-body.cards`, one record each.

Label nodes in plain words, with the searchable name as a `.sub` mono sublabel; a node
that needs an outline is a `box` with a tag header row. The frame bar's meta says how to
read the figure ("solid today · dashed behind the flag") or where its values come from. A
behavior that a sentence explains fully gets no figure. Build figures with
[`scripts/figure.mjs`](scripts/figure.mjs), which draws in the example's geometry. A split
is a `.frame-body.split` of two `.pane`s (the second `.pane.after`), each a `p.pane-label`
and a `half` drawing. A single figure wider than 358px pairs a 640-wide `.dg.wide` with a
stacked `.dg.narrow`.

**Limits**: at most 140 words of prose outside the fold, counting the hero, spec captions,
section lines, notes, forks and tables, and leaving out the running head, the spec numbers, the
ruler, and figures with their frame bars. Every name, path, SHA and
value matches the PR's code at its head.

**Rejected looks**, each turned down in review: a review dashboard (merge boxes, check
lists, status chips, JSON dumps, diff hunks), a landing page, a poster, a slide deck, an
explorable map, a long evidence page, a grouped diff map, a copy of a blog's styling, and
a narrow column of hairline rows under gutter labels, framed figures or not. The bar is
the system-note look, as the example renders it; when a page drifts toward a rejected
look, cut back to it.

## 1. Read the PR

- **PR**: `gh pr view <n> --repo <owner/repo> --json title,body,baseRefName,headRefOid,files,commits,statusCheckRollup`,
  and the diff against its base. For a stack, every PR in it.
- **Code**: read the changed code at the head (`git show <head>:<path>`), and the tests
  that pin each behavior. Values for figures come from those tests and fixtures.
- **Exposure**: who hits each behavior today, from the gate's state, its callers, or
  config at the head. The verdict rests on it.
- **Evidence**: what ran, and at which commit: required checks
  (`gh pr checks <n> --required`), tests you or the PR's reports ran, and manual checks.

**Done when:** every behavior the diff changes is listed with its before and after, the
exposure claim has a source, and each piece of evidence has its commit.

## 2. Outline

Write the verdict sentence, the specs' numbers, one line per section (its plain label,
its figure, a split's two pane labels, or "no figure"), where each pin goes, the
Decisions forks, the Verified and Not verified rows, and the fold's headings. Merge two
behaviors a reviewer sees as one; split one that changes for different users.

**Done when:** each changed behavior has a section, each figure shows a behavior rather
than a structure, each pin marks a risk the fold explains, and the prose fits 140 words.

## 3. Build

1. **Work dir**: one per PR, kept, so an update reuses its Lakebed binding:
   `~/.local/state/review-artifact/<owner>-<repo>-<pr>/`. Start from the example's two
   files in `<skill>/assets/example/`, or generate `body.html` from a script.
2. **Write `body.html`**, the page inside `<main>`, in the example's markup:
   `header.bar`, `section.hero` (`h1`, `p.verdict`), `ul.specs` (each `li` a `<b>`
   number and its caption), the optional `ol.ruler`, then each `section.sec` with a
   `div.sec-head` (`h2`, the plain label, and its line; the counter adds the number).
   A figure is `figure.frame` holding `span.cm`, `figcaption.frame-bar` and
   `div.frame-body`. Decisions is a `ul.forks`, each `li` a `.call`, a `p.pick` and a
   `p.over`, each `p` an `.opt` and what it means; Verified and Not verified are each a
   `table.spec` whose value cells are `td.v`.
   Last comes `div.fold` with one `<details>`.
3. **Write `llms.md`**: the same review in Markdown, with a `## <label>` heading for each
   section. Each figure becomes words, a list, or a table. Plain text only, so it stays
   searchable.
4. **Build**: `node <skill>/scripts/build.mjs <dir>` writes `<dir>/index.html` (fonts
   inlined, with a footer holding the llms.md link and the font notice) and `<dir>/capsule/`, the Lakebed capsule.

**Done when:** the build prints both paths.

## 4. Check

1. Run `node <skill>/scripts/check.mjs <dir> --repo <checkout> --rev <head>`, with one
   `--rev` per PR head. It checks the structure, the specs and ruler, framed figures, split
   widths, pins against the fold, the Decisions forks, the word limit, page errors, fonts, sideways scroll, text under 12px, tracking, figure text
   clashes, `extra.css`, the Markdown's headings and SHAs, and that every code name, path and SHA
   resolves at a head. It writes screenshots to `<dir>/shots/`.
2. Fix every `FAIL` in `body.html` or `llms.md`, rebuild, and rerun.
3. **Read each spec number and each value in a figure** against the test, fixture or run
   it came from, since the script checks names, not numbers.
4. **Look at every screenshot** next to the example's: aligned edges, labels clear of
   lines, crop marks at all four corners, nothing clipped, the dark mode legible, the
   hero and specs stacked on a phone, and the mobile figure at the frame's full width.

**Done when:** `check.mjs` exits 0, each figure value has a source, and you've looked at
every screenshot.

## 5. Publish

Publishing makes the page public, so it waits for the user's go (**Approval**). Without
one, stop here: show `shots/desktop.png` and `shots/mobile.png`, and offer publish as
`a`.

- **Publish** with `use-lakebed`, intent `publish`, capsule root `<dir>/capsule`,
  lifecycle owned with no expiry, endpoint verifier `node scripts/verify-routes.mjs`.
  It runs the disclosure review and reports the URL.
- **Link** the URL and its `/llms.md` first in the PR's Review guide, through `open-pr`'s
  sync mode when the PR has a Review guide section, or as the first line of the body.
- **After a push** that changes a behavior, update `body.html` and `llms.md`, rebuild,
  check, and publish again from the same work dir, which updates the same URL.

**Done when:** the published `/` and `/llms.md` return 200, and the PR links them.
