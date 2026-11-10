#!/usr/bin/env bash
# Builds one self-contained HTML page of a run's proof from each feature's steps.json:
# the result, the numbered steps with their screenshots, then page errors. Prints the
# page's path. run.sh calls it after every recipe. T3's html_render inlines the
# screenshots' absolute paths.
# Usage: scripts/gallery.sh [run dir]   (defaults to the current run)
set -euo pipefail
source "$(dirname "$0")/common.sh"
run="$(cd "${1:-$CURRENT}" && pwd -P)"
[ -d "$run/evidence" ] || { echo "no evidence in $run" >&2; exit 1; }
python3 - "$run" <<'PY'
import html, json, pathlib, sys
from collections import Counter
from urllib.parse import urlsplit
run = pathlib.Path(sys.argv[1])
esc = html.escape
def read(name):
    path = run / name
    return path.read_text().strip() if path.exists() else "?"

sections = []
for feature in sorted(p for p in (run / "evidence").iterdir() if p.is_dir()):
    record_file = feature / "steps.json"
    if not record_file.exists():
        sections.append(f"<section><h2>⚠️ no result · {esc(feature.name)}</h2>"
                        "<p>The recipe didn't finish, so there's no steps.json.</p></section>")
        continue
    record = json.loads(record_file.read_text())
    steps = "".join(
        f'<figure class="step"><figcaption>{"❌" if step["name"] == "failure" else "✅"} <b>{n:02}</b> '
        f'{esc(step["name"].replace("-", " "))} <span class="url">{esc(urlsplit(step["url"]).path)}</span></figcaption>'
        f'<div class="shot" role="button" tabindex="0" aria-expanded="false">'
        f'<img src="{esc(step["screenshot"])}" alt="{esc(step["name"])}"></div></figure>'
        for n, step in enumerate(record["steps"], 1)
    )
    errors = record["pageErrors"]
    error_list = "".join(f"<li>{esc(line)}{f' <b>×{n}</b>' if n > 1 else ''}</li>" for line, n in Counter(errors).items())
    verdict = "✅ verified" if record["result"] == "verified" else "❌ failed"
    sections.append(
        f'<section><h2>{verdict} · {esc(feature.name)}</h2>'
        + (f'<p class="error">{esc(record["error"])}</p>' if record.get("error") else "")
        + (steps or "<p>No screenshots.</p>")
        + (f'<div class="errors"><h3>⚠️ {len(errors)} page error(s)</h3><ul>{error_list}</ul></div>' if errors else "")
        + "</section>"
    )

HEAD = """<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><style>
body { margin: 0; background: var(--background); color: var(--foreground);
  font: 14px/1.45 system-ui, sans-serif; }
.meta { color: var(--muted-foreground); margin: 0 0 12px; }
h2 { font-size: 15px; margin: 16px 0 8px; }
h3 { font-size: 13px; margin: 0 0 4px; color: var(--warning); }
.step { margin: 0 0 14px; }
figcaption { margin-bottom: 6px; }
.url { color: var(--muted-foreground); font-family: ui-monospace, monospace; font-size: 12px; }
.shot { border: 1px solid var(--border);
  border-radius: 8px; overflow: hidden; cursor: zoom-in; position: relative; text-align: center; }
.shot img { display: block; width: 100%; height: 320px; object-fit: cover; object-position: top; }
.shot::after { content: "Tap to expand"; position: absolute; inset: auto 0 0 0; padding: 18px 0 6px;
  font-size: 12px; color: var(--muted-foreground); background: linear-gradient(transparent, var(--background)); }
.shot[aria-expanded="true"] { cursor: zoom-out; }
.shot[aria-expanded="true"] img { height: auto; }
.shot[aria-expanded="true"]::after { content: none; }
/* Desktop screenshots are unreadable at phone width: zoom in and let the reader pan. */
@media (max-width: 600px) {
  .shot[aria-expanded="true"] { overflow-x: auto; }
  .shot[aria-expanded="true"] img { width: 250%; max-width: none; }
}
.error { color: var(--destructive); font-size: 12px; white-space: pre-wrap; overflow-wrap: anywhere; }
.errors { border-left: 3px solid var(--warning); padding: 2px 0 2px 10px; }
.errors ul { margin: 0; padding-left: 18px; font-size: 12px; overflow-wrap: anywhere; }
</style></head><body>
"""
SCRIPT = """<script>
for (const shot of document.querySelectorAll(".shot")) {
  const toggle = () => shot.setAttribute("aria-expanded", String(shot.getAttribute("aria-expanded") !== "true"))
  shot.addEventListener("click", toggle)
  shot.addEventListener("keydown", (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), toggle()))
}
</script></body></html>
"""
meta = f'<p class="meta">{esc(read("branch"))} · {esc(read("revision"))[:10]} · run {esc(run.name)}</p>'
page = HEAD + meta + "".join(sections) + SCRIPT
out = run / "evidence" / "gallery.html"
out.write_text(page)
print(out)
PY
