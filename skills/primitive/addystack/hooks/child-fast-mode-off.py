#!/usr/bin/env python3
"""PreToolUse on T3's thread-creating tools (`delegate_task`, `create_threads`,
`t3_thread_launch`): turns Claude fast mode off in the thread it starts, through
`updatedInput`, so only threads the user starts themselves run fast. A child inherits the
parent's model options, `fastMode: true` included. Fast mode measured 2.78× output speed
at 2× price, billed to usage credits; over the 30 days to Oct 30, 2026, threads the user
started cost about $5.7k at standard rates, and agent-started threads and children about
$6.3k. Claude transcripts from Sep 30 to Oct 31, 2026 hold 2,067 `delegate_task` calls in
228 sessions (8 named fastMode) and 79 `t3_thread_launch` calls in 32 sessions (73 passed
no `modelSelection`), counted once per tool_use ID; none called `create_threads`.

- `delegate_task` and each `create_threads` thread get `fastMode: false` in
  `target.options`, which T3 merges over the inherited options ("Given values override
  inherited"), so the inherited effort stays: a delegate_task with no options ran as
  effort high, fastMode false on Oct 31, 2026. A dict stays a dict and a list a list. An
  empty one, an explicit clear, stays as it is, since T3 runs a cleared selection with
  fastMode off.
- `t3_thread_launch` with `modelSelection` gets it there. Without one, the launch inherits
  the parent's model, so the hook copies the parent thread's `modelSelection` from T3's
  state database (`t3_child.py`) with fastMode off. When the database can't be read, no
  single thread owns this session, or the parent has none, the launch passes unchanged.
- Only a model whose T3 catalog entry (`model-manifest.json`) offers fastMode gets it,
  found by slug or alias such as `opus`: T3 rejects the option on Sonnet, Haiku, and
  Fable. A target without a model runs the parent's. A target or parent on another
  provider, or a catalog that can't be read, passes unchanged.

It returns no permission decision, so the session's own permission mode decides the call,
auto mode's classifier included; Claude Code 2.1.314 applies an `updatedInput` that comes
without one. Returning "ask" outside bypass mode would stop an auto-mode thread at a
prompt. Outside T3, and on any input it doesn't expect, it adds nothing. Codex parents
aren't covered: the hook is in Claude Code's list only. Provider IDs, model names, and
option IDs are compared as written, though T3 trims them and matches aliases in any case;
none of those 2,146 calls padded or capitalized one, or gave a launch both `instanceId`
and `provider`."""
import functools, json, os, pathlib, sqlite3, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import t3_child  # noqa: E402

CLAUDE = "claudeAgent"
MANIFEST = os.environ.get("T3_MODEL_MANIFEST", "~/.t3/userdata/model-manifest.json")


class Unexpected(Exception):
    """An input shape the hook doesn't know, so it leaves the call alone."""


@functools.cache
def fast_models():
    """Every name, slug or alias, of a Claude model whose T3 catalog entry offers fastMode.
    T3 rejects fastMode on any other model, Sonnet included. Empty when the catalog can't
    be read, so nothing changes."""
    try:
        claude = json.loads(pathlib.Path(MANIFEST).expanduser().read_text())["manifest"]["providers"][CLAUDE]
        names = set()
        for model in claude["models"]:
            descriptors = claude["profiles"][model["profile"]]["capabilities"].get("optionDescriptors", [])
            if any(descriptor.get("id") == "fastMode" for descriptor in descriptors):
                names |= {model["slug"], *model.get("aliases", [])}
        return frozenset(names)
    except (OSError, ValueError, KeyError, TypeError, AttributeError):
        return frozenset()


def turned_off(options):
    """options with fastMode false, in the same shape, or None when it needs no change. An
    empty one clears the inherited options, and T3 then runs fastMode off; adding fastMode
    would keep the rest of the inherited options instead, so it stays as it is."""
    if options is None:
        return {"fastMode": False}
    if options == {} or options == []:
        return None
    if isinstance(options, dict):
        return None if options.get("fastMode") is False else {**options, "fastMode": False}
    if not isinstance(options, list) or not all(isinstance(item, dict) for item in options):
        raise Unexpected
    fast = [item for item in options if item.get("id") == "fastMode"]
    if fast and all(item.get("value") is False for item in fast):
        return None
    if not fast:
        return [*options, {"id": "fastMode", "value": False}]
    return [{**item, "value": False} if item.get("id") == "fastMode" else item for item in options]


def on_claude(*providers):
    """False when a provider field names another provider; only Claude has fastMode."""
    return all(provider is None or provider == CLAUDE for provider in providers)


def with_target_off(holder, parent):
    """holder (a delegate_task input or a create_threads thread) with fastMode off in its
    target, or None when it needs no change. A target without a model runs the parent's."""
    if not isinstance(holder, dict):
        raise Unexpected
    target = holder.get("target", {})
    if not isinstance(target, dict):
        raise Unexpected
    if not on_claude(target.get("providerInstanceId"), target.get("driverKind")):
        return None
    model = target.get("model") or (parent() or {}).get("model")
    if model not in fast_models():
        return None
    options = turned_off(target.get("options"))
    return None if options is None else {**holder, "target": {**target, "options": options}}


def with_selection_off(selection):
    """A modelSelection with fastMode off, or None when it needs no change."""
    if not isinstance(selection, dict) or not isinstance(selection.get("model"), str):
        raise Unexpected
    if not on_claude(selection.get("instanceId"), selection.get("provider")):
        return None
    if selection["model"] not in fast_models():
        return None
    options = turned_off(selection.get("options"))
    return None if options is None else {**selection, "options": options}


def parent_selection(session_id):
    """The modelSelection of the T3 thread that owns this session, or None in doubt."""
    if not isinstance(session_id, str) or not session_id:
        return None
    try:
        db = t3_child.connect()
        try:
            owners = t3_child.threads(db, session_id)
            if len(owners) != 1:
                return None
            row = db.execute("select json_extract(payload_json, '$.modelSelection') "
                             "from orchestration_v2_projection_threads where thread_id = ?", owners[0]).fetchone()
        finally:
            db.close()
        selection = json.loads(row[0]) if row and row[0] else None
    except (sqlite3.Error, ValueError):
        return None
    # A parent on another provider keeps its own options; only Claude has fastMode.
    return selection if isinstance(selection, dict) and selection.get("instanceId") == CLAUDE else None


def rewrite(tool, tool_input, session_id):
    """The rewritten tool_input, or None when it needs no change."""
    parent = functools.cache(lambda: parent_selection(session_id))
    if tool.endswith("__delegate_task"):
        return with_target_off(tool_input, parent)
    if tool.endswith("__create_threads"):
        threads = tool_input.get("threads")
        if not isinstance(threads, list):
            raise Unexpected
        changed = [with_target_off(thread, parent) for thread in threads]
        if all(thread is None for thread in changed):
            return None
        return {**tool_input, "threads": [new or old for new, old in zip(changed, threads)]}
    if tool.endswith("__t3_thread_launch"):
        if "modelSelection" in tool_input:
            selection = with_selection_off(tool_input["modelSelection"])
        else:
            selection = parent() and with_selection_off(parent())
        return None if selection is None else {**tool_input, "modelSelection": selection}
    return None


def main():
    # Outside T3 Code there are no T3 threads to start.
    if not os.environ.get("T3CODE_CLI_PATH"):
        return
    payload = json.load(sys.stdin)
    tool, tool_input = payload.get("tool_name"), payload.get("tool_input")
    if not isinstance(tool, str) or not isinstance(tool_input, dict):
        return
    updated = rewrite(tool, tool_input, payload.get("session_id"))
    if updated is None:
        return
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "updatedInput": updated,
    }}))


try:
    main()
except Exception:  # noqa: BLE001 — a crash would show a hook error on every T3 call; leave the call alone instead
    pass
