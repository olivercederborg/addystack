#!/usr/bin/env bash
# Builds the review-teammate-pr eval repos in /tmp. Usage: ./setup.sh [target-dir]
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
# Resolve `..` and symlinks first, so the guard sees the path rm -rf will delete.
out=$(python3 -c 'import os, sys; print(os.path.realpath(sys.argv[1]))' "${1:-/tmp/review-teammate-pr-evals}")
case "$out" in /tmp/?*|/private/tmp/?*) ;; *) echo "Refusing to write outside /tmp: $out" >&2; exit 1;; esac
rm -rf "$out" && mkdir -p "$out"
commit() { git -c user.email=eval@example.com -c user.name=eval commit -qm "$1"; }

# Base on develop, PR head on feature/fee-rows. noop-wake reuses fee-rows' code.
for id in fee-rows noop-wake; do
  mkdir "$out/$id"
  (cd "$out/$id" && git init -q -b develop \
    && cp -R "$here/fee-rows/base/." . && git add src && commit "Base" \
    && git checkout -q -b feature/fee-rows \
    && cp -R "$here/fee-rows/head/." . && git add src && commit "Add fee rows to top-up export" \
    && cp "$here/$id/pr.json" .)
done

# held-defect: the PR's only defect is minor, so its call may be non-blocking.
# bot-defect reuses its code, with CodeRabbit having already raised that defect.
for id in held-defect bot-defect; do
  mkdir "$out/$id"
  (cd "$out/$id" && git init -q -b develop \
    && cp -R "$here/held-defect/base/." . && git add src && commit "Base" \
    && git checkout -q -b feature/csv-download \
    && cp -R "$here/held-defect/head/." . && git add src && commit "Download top-up exports as CSV" \
    && cp "$here/$id/pr.json" .)
done

# exposure: the form routes the picker selection to export; the replica shows live exposure.
# No guidance names scripts/replica.sh, as on #4897, where the review never looked for one.
mkdir "$out/exposure"
(cd "$out/exposure" && git init -q -b develop \
  && cp -R "$here/exposure/base/." . && printf '.replica/\n' > .gitignore && git add -A && commit "Base" \
  && git checkout -q -b feature/supplier-picker \
  && cp -R "$here/exposure/head/." . && git add src && commit "Show the supplier picker to every company with a supplier catalog" \
  && mkdir .replica && sqlite3 .replica/prod.db < "$here/exposure/replica.sql" \
  && cp "$here/exposure/pr.json" .)

# dismissed-ci: the user approved the commit tagged `approved`, then a push moved the head.
mkdir "$out/dismissed-ci"
(cd "$out/dismissed-ci" && git init -q -b develop \
  && cp -R "$here/dismissed-ci/base/." . && git add src && commit "Base" \
  && git checkout -q -b feature/fee-rows \
  && cp -R "$here/dismissed-ci/approved/." . && git add src && commit "Add fee rows to top-up export" \
  && git tag approved \
  && cp -R "$here/dismissed-ci/head/." . && git add src && commit "Tidy exportRows" \
  && cp "$here/dismissed-ci/pr.json" .)

# rereview-*: the user's comment was posted at the commit tagged `reviewed`, then a push
# fixed it. 4615's fix misses the lone "No account" button (R51 M5 #5405); 4618's covers
# it and tests it. In both, option ids come from sort order, so no account can take
# "No account"'s id.
for id in rereview-4615 rereview-4618; do
  mkdir "$out/$id"
  (cd "$out/$id" && git init -q -b develop \
    && cp -R "$here/rereview-4615/base/." . && git add -A && commit "Base" \
    && git checkout -q -b feature/account-filter \
    && cp -R "$here/rereview-4615/reviewed/." . && git add -A && commit "Filter receipts by account" \
    && git tag reviewed \
    && cp -R "$here/$id/head/." . && git add -A && commit "Focus the picked option by value" \
    && cp "$here/$id/pr.json" .)
done

# codex-*: the Codex pass's findings are in pr.json. 4616's holds, though the author's
# reply refutes another premise (R51 H5 #4744); 4617's two don't (R51 F1-F8).
for id in codex-4616 codex-4617; do
  mkdir "$out/$id"
  (cd "$out/$id" && git init -q -b develop \
    && cp -R "$here/$id/base/." . && git add -A && commit "Base" \
    && git checkout -q -b "feature/pr-${id#codex-}" \
    && cp -R "$here/$id/head/." . && git add -A && commit "$(jq -r .title "$here/$id/pr.json")" \
    && cp "$here/$id/pr.json" .)
done

# documented-contract: the PR's Risk section accepts an all-or-nothing 500 on a published route, and
# src/web/ skips a missing file and signs in parallel (#5637).
mkdir "$out/documented-contract"
(cd "$out/documented-contract" && git init -q -b develop \
  && cp -R "$here/documented-contract/base/." . && git add -A && commit "Base" \
  && git checkout -q -b feature/receipt-download-urls \
  && cp -R "$here/documented-contract/head/." . && git add -A && commit "Return expiring receipt download URLs through the API" \
  && cp "$here/documented-contract/pr.json" .)

# later-milestone: formatAmount assumes two minor digits, which only a later milestone's
# currencies can reach; the PR's test and EX-70 show the EUR-only intent.
mkdir "$out/later-milestone"
(cd "$out/later-milestone" && git init -q -b develop \
  && cp -R "$here/later-milestone/base/." . && git add -A && commit "Base" \
  && git checkout -q -b feature/receipt-currency \
  && cp -R "$here/later-milestone/head/." . && git add -A && commit "Show receipt PDF amounts in the company's currency" \
  && cp "$here/later-milestone/pr.json" .)

echo "Scenarios ready in $out"
