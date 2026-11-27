"""What analyze.py and designs.py share: the replay's rows, which heartbeats acted, the
kind of each tick finding, and which coordinators are Franklin's or legacy."""
import json, re

# A heartbeat acted when it delegated, sent to a thread, loaded a skill, edited a file
# outside the project folder, committed, pushed, or merged.
ACT = re.compile(r"^(mcp__t3-code__(delegate_task|t3_thread_send|t3_thread_launch|t3_pending_request)|Skill):"
                 r"|^(Edit|Write):(?!.*\.local/state/orchestrate)"
                 r"|^Bash:.*(git commit|git push|gh stack (push|submit|merge|sync|rebase)|gh pr (merge|ready|comment|edit|review)"
                 r"|gh api [^|]*-X ?(POST|PATCH|PUT)|merge-gate\.py)")


def kind(line):
    return ("stopped" if "stopped (" in line else "asked" if "question(s)" in line else "stuck" if "no new thread item" in line
            else "elsewhere" if "another machine" in line else "pr")


def load(out):
    """Rows with `acted` set, all turns, session → transcript path, starts, the legacy
    sessions (most started runs went to `t3_thread_launch` threads), and Franklin's rows."""
    rows = json.load(open(out + "replay.json"))
    turns = json.load(open(out + "turns.json"))
    files = {x["file"].split("/")[-1][:-6]: x["file"] for x in turns}
    starts = json.load(open(out + "starts.json"))
    legacy = {s for s, v in starts.items() if v and sum(i.startswith("mcp:launch:") for _, i, _ in v) > len(v) / 2}
    for row in rows:
        row["acted"] = any(ACT.search(t) for t in row["tools"])
    franklin = [r for r in rows if "franklin" in files.get(r["sess"], "") and r["sess"] not in legacy]
    return rows, turns, files, starts, legacy, franklin
