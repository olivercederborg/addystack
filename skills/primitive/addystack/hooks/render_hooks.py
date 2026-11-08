#!/usr/bin/env python3
"""Renders the hooks a runtime should hold on a host profile, so a machine's
~/.claude/settings.json `hooks` key and ~/.codex/hooks.json come from the declared set
instead of hand edits. Added for sandboxes, which must equal the Mac and the Linux machine (Oct
2026).

    python3 hooks/render_hooks.py --runtime claude|codex [--profile auto|darwin|linux|sandbox]
                                  [--into PATH] [--out PATH]

Prints `{"hooks": …}`. With --into, prints that JSON file with the selected hooks merged
into its `hooks` key (hookset.merge, the merge `addystack install` runs): the kit's hooks,
the ones install's ledger records and the ones a manifest entry renders, are replaced, and
every other hook and key is kept, in order. --out writes there instead of stdout. The output is
JSON with a 2-space indent and a final newline, the format the committed files use, so a
diff shows only hook changes. A thin wrapper over hookset.render until M3: the declared set
is hook_parity.py's, the manifest entries hookset selects for the built resolved.json, or
for the kit's defaults without one. Each event's hooks come in manifest order, and
consecutive entries with the same matcher share a group. Codex trusts a hook by its
position, so reordering untrusts it: keep the manifest in the installed, trusted order.
Events come in the order the manifest first names them. Entries whose `hosts` exclude the
profile are left out."""
import argparse, json, pathlib, sys

import hook_parity
import hookset  # on sys.path through hook_parity
import reconcile


def render(runtime, profile="auto"):
    """The `hooks` object for runtime on profile: {event: [{"matcher"?, "hooks": [...]}]}."""
    return hookset.render(hook_parity.selected(runtime, profile))


def dumps(document):
    """document as the committed config files format it."""
    return json.dumps(document, indent=2, ensure_ascii=False) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--runtime", required=True, choices=sorted(hook_parity.RUNTIMES))
    parser.add_argument("--profile", default="auto", choices=("auto", *hook_parity.PROFILES))
    parser.add_argument("--into", help="a JSON file whose `hooks` key to replace, such as ~/.claude/settings.json")
    parser.add_argument("--out", help="write here instead of stdout")
    args = parser.parse_args()
    document = {}
    if args.into:
        try:
            document = json.loads(pathlib.Path(args.into).expanduser().read_text())
        except (OSError, ValueError) as error:
            parser.error(f"can't read {args.into}: {error}")
        if not isinstance(document, dict):
            parser.error(f"{args.into} doesn't hold a JSON object")
    document = hookset.merge(document, hook_parity.selected(args.runtime, args.profile),
                             hookset.owner(hook_parity.resolved_config(), reconcile._ledger().get(args.runtime, [])))
    text = dumps(document)
    if args.out:
        pathlib.Path(args.out).expanduser().write_text(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
