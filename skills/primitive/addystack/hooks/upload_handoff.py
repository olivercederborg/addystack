#!/usr/bin/env python3
"""Stop: send a reply back when it hands the user a screenshot upload for a PR ("drag the
screenshots into #5418's UI evidence section") or says gh can't upload images.

gh uploads images and video with `--attach` on `gh pr` and `gh issue` create, edit, and
comment, but models learned an older gh and kept handing the upload to the user: T3
threads 45ca0b6d (Sep 29), bd024e64 (Oct 22), and b439f951 (Oct 26, 2026), and a work
PR on Oct 27, each followed by the user's "use the gh cli". The kit's gist workaround, whose
header said gh takes only text, taught the same until it was deleted.

A line counts when it names an image (a screenshot, image, video, or media file) and a
PR beside a hand-off (drag, drop in, through your browser, the web page, by hand), or
when it says gh can't upload or attach. Code spans and quoted text are examples. A line
that reports or retracts the claim ("claims gh can't", "I was wrong that gh can't")
isn't making it, and a line linking another T3 thread relays that thread's need. Folds
and the turn block aren't read. Over 42,666 T3 assistant messages from Sep 1 to Oct 27,
2026, it flags 23 lines, all hand-offs, in 8 threads. T3 delegated children pass, as in
bare_references.py."""
import json, pathlib, re, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from bare_references import delegated_child, plain, visible  # noqa: E402

IMAGE = re.compile(r"\b(?:screenshots?|images?|videos?|recordings?|gifs?)\b|\.(?:png|jpe?g|gif|webm|mp4|mov)\b", re.I)
PR = re.compile(r"\b(?:PRs?|pull requests?|descriptions?|UI evidence)\b|#\d+", re.I)
BROWSER = r"(?:(?:through|in|via|from|needs) (?:your|the|a|T3[’']s) (?:signed-in )?browser|web (?:page|ui)|by hand)"
HANDOFF = re.compile(r"\b(?:drag\w*|drop (?:it |them |the \w+ )?in(?:to)?|" + BROWSER + r")\b", re.I)
CANT = r"(?:can[’']?t|cannot|can not|doesn[’']?t|does not|won[’']?t|unable to|has no way to)"
# "the gist script wrongly claims gh can't attach" reports the claim; it doesn't make it.
SUBJECT = r"\b(?:gh|GitHub CLI|the CLI)\b"
REPORTED = re.compile(r"\b(?:claim\w*|thinks?|thought|believ\w*|said|says|told|wrong|mistaken)\b[^.\n]*" + SUBJECT, re.I)
CLAIM = re.compile(SUBJECT + r"[^.\n]{0,40}\b" + CANT + r"\b[^.\n]{0,30}\b(?:upload|attach)", re.I)


def problems(text):
    """Each visible line that hands the user an image upload or says gh can't do it."""
    found = []
    for line in visible(text):
        words = plain(line.replace("`gh`", "gh"))  # agents write "`gh` can't upload"
        if "t3-thread://" in line:
            continue  # relays another thread's need, as a coordinator does
        handoff = IMAGE.search(words) and PR.search(words) and HANDOFF.search(words)
        if handoff or (CLAIM.search(words) and not REPORTED.search(words)):
            found.append(line.strip())
    return found


def main():
    try:
        event = json.loads(sys.stdin.read())
    except ValueError:
        return
    if event.get("stop_hook_active") or delegated_child(event):
        return
    found = problems(event.get("last_assistant_message") or "")
    if not found:
        return
    listing = "\n".join(f"- {line}" for line in found)
    feedback = (
        "These lines hand the user a screenshot upload, or say gh can't upload images:\n" + listing +
        "\ngh uploads them itself. `gh pr edit <n> --attach '<file>#<alt text>'` appends each "
        "file to the PR description, and a reference such as `![Before](./before.png)` in a "
        "`--body-file` becomes the uploaded image; `gh pr create` and `gh pr comment` take the "
        "same flag, and so do `gh issue create`, `edit`, and `comment`. Upload the files, check "
        "that `gh pr view <n> --json body` shows github.com/user-attachments links, then send "
        "your whole reply again without the upload step.")
    # Codex's Stop takes only decision and reason, and its input carries turn_id; Claude
    # Code continues through additionalContext (see bare_references.py).
    if "turn_id" in event:
        print(json.dumps({"decision": "block", "reason": feedback}))
    else:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "Stop", "additionalContext": feedback}}))


if __name__ == "__main__":
    main()
