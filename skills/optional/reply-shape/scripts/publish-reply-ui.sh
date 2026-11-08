#!/usr/bin/env bash
# Publishes ui/reply.js to a public GitHub repo and tags it, so a page can load it from
# jsDelivr pinned to that tag: https://cdn.jsdelivr.net/gh/<owner/repo>@<tag>/reply.js
#
# The public repo holds only reply.js, the kit's MIT LICENSE, and a one-paragraph README.
# Before pushing, every file is grepped for tokens, keys, home paths, local hostnames, and
# IP addresses, plus the extended regex in REPLY_UI_DENY (names you keep out of public
# repos), and the push stops on a match. A tag is never moved: jsDelivr caches a tag's
# files for good, so a change gets a new version. After the push, the script fetches the
# pinned URL until it serves the same bytes.
#
# Run from a kit checkout, since the LICENSE is the kit's.
# Usage: REPLY_UI_DENY='regex' publish-reply-ui.sh <owner/repo> <vX.Y.Z>
set -euo pipefail

repo="${1:?usage: publish-reply-ui.sh <owner/repo> <vX.Y.Z>}"
tag="${2:?usage: publish-reply-ui.sh <owner/repo> <vX.Y.Z>}"
[[ $tag =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "tag must look like v1.0.0, got $tag" >&2; exit 1; }
here="$(cd "$(dirname "$0")" && pwd)"
kit="$(git -C "$here" rev-parse --show-toplevel)"
url="https://cdn.jsdelivr.net/gh/$repo@$tag/reply.js"

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
git clone -q "https://github.com/$repo.git" "$work/repo"
cd "$work/repo"
if git ls-remote --exit-code --tags origin "refs/tags/$tag" > /dev/null; then
  echo "$repo already has $tag; tags are immutable on the CDN, so publish a new version" >&2
  exit 1
fi
git checkout -q -B main

cp "$here/../ui/reply.js" reply.js
cp "$kit/LICENSE" LICENSE
cat > README.md <<EOF
# reply-ui

\`reply.js\` draws a compact JSON reply card as themed UI inside an HTML page, for coding agents that show inline pages in chat. Load it pinned to a tag and put the card in a \`<script type="application/json" id="ui">\` after it: \`<script src="https://cdn.jsdelivr.net/gh/$repo@$tag/reply.js"></script>\`. A card is \`{"ui": [blocks]}\`, where each block is one of \`outcome\`, \`delta\`, \`change\`, \`decision\`, \`table\`, \`checks\`, or \`flow\`; colors and fonts come from the host page's CSS variables (\`--foreground\`, \`--success\`, \`--font-mono\`, and so on), and a block the renderer doesn't know shows as plain text with a \`console.error\`. MIT licensed.
EOF

leaks='(/Users/|/home/|~/|gh[pousr]_[A-Za-z0-9]{20}|github_pat_|sk-[A-Za-z0-9_-]{20}|xox[abprs]-|AKIA[0-9A-Z]{16}|PRIVATE KEY|[Tt]oken[=:]|\.localhost|\.local\b|\.internal\b|\b[0-9]{1,3}(\.[0-9]{1,3}){3}\b)'
if grep -nE "$leaks" reply.js LICENSE README.md; then
  echo "a file above holds a token, path, host, or address; nothing was pushed" >&2
  exit 1
fi
if [[ -n ${REPLY_UI_DENY:-} ]] && grep -nE "$REPLY_UI_DENY" reply.js LICENSE README.md; then
  echo "a file above matches REPLY_UI_DENY; nothing was pushed" >&2
  exit 1
fi
extra="$(git ls-files | grep -vxE 'reply\.js|LICENSE|README\.md' || true)"
[[ -z $extra ]] || { echo "the public repo holds other files: $extra" >&2; exit 1; }

git add reply.js LICENSE README.md
git commit -q -m "reply.js $tag"
git tag "$tag"
git push -q origin main "refs/tags/$tag"
echo "pushed $repo $tag"

for attempt in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsSL "$url" -o "$work/served.js" && cmp -s "$work/served.js" reply.js; then
    echo "serves: $url"
    exit 0
  fi
  sleep $((attempt * 3))
done
echo "pushed, but $url doesn't serve the file yet; retry the fetch in a few minutes" >&2
exit 1
