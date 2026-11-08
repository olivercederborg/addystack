#!/usr/bin/env python3
"""PreToolUse on T3's `html_render`: refuses a reply card that would draw wrong, so a
broken card never reaches the user. reply-shape's `scripts/validate-card.py --hook` holds
the check and its tests: a page that loads reply.js from any URL but the pinned one in
reply-shape's `ui/renderer.url`, or whose card payload is missing or fails the catalog
schema, is denied with the fix. A page that doesn't load reply.js passes.

This wrapper only finds reply-shape: beside the kit in an install (`skills/reply-shape`),
in the kit's own checkout (`skills/optional/reply-shape`), or the folder of the
REPLY_SHAPE_SKILL file. Without reply-shape there are no cards to check, so it passes; a
check that crashes or times out refuses the card, naming why."""
import json, os, pathlib, subprocess, sys

KIT = pathlib.Path(__file__).resolve().parent.parent


def validator():
    """reply-shape's validate-card.py, or None when reply-shape isn't installed."""
    # Runtime places, not hook-test inputs: reply-shape's own suite runs this wrapper.
    places = [KIT.parent / "reply-shape", KIT.parents[1] / "optional" / "reply-shape"]
    if os.environ.get("REPLY_SHAPE_SKILL"):
        places.insert(0, pathlib.Path(os.environ["REPLY_SHAPE_SKILL"]).expanduser().parent)
    for place in places:
        script = place / "scripts" / "validate-card.py"
        if script.is_file():
            return script
    return None


def main():
    script = validator()
    if script is None:
        return
    try:
        done = subprocess.run([sys.executable, str(script), "--hook"], input=sys.stdin.read(),
                              capture_output=True, text=True, timeout=8)
        failed = done.returncode != 0 and (done.stderr.strip().splitlines() or ["no output"])[-1]
    except subprocess.TimeoutExpired:
        done, failed = None, "timed out"
    if failed:
        # A card the check couldn't finish isn't known to draw, so it's refused, with why.
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
              "permissionDecisionReason": f"reply-shape's card check failed ({failed}); fix the card, or run "
                                          "scripts/validate-card.py page.html to see why."}}))
        return
    sys.stdout.write(done.stdout)


if __name__ == "__main__":
    main()
