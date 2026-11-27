"""The record of posts named-links-check.py denied, so it denies each at most once: an
identical retry, with the same session, target, and text, passes. Owns the record's file
($ADDYSTACK_STATE/named-links-denied.json, by default under ~/.local/state/addystack), its
key (a hash, so no posted text reaches disk), its bound, its lock, and its atomic write.
Any doubt passes the post: a record it can't read or write never denies."""
import fcntl, hashlib, json, os, pathlib, tempfile, time

# Denials kept, newest last; a retry comes seconds after its denial, so 200 covers any
# session's backlog many times over.
KEEP = 200


def first(session_id: object, target: str, text: str) -> bool:
    """True when this session hasn't been denied this text to this target, and the denial is
    now on record; False for a repeat, and when it can't tell or can't record."""
    if not isinstance(session_id, str) or not session_id:
        return False
    key = hashlib.sha256(json.dumps([session_id, target, text]).encode()).hexdigest()
    folder = pathlib.Path(os.environ.get("ADDYSTACK_STATE", "~/.local/state/addystack")).expanduser()
    record = folder / "named-links-denied.json"
    try:
        folder.mkdir(parents=True, exist_ok=True)
        # Two hooks may run at once (parallel tool calls); the lock file keeps each
        # read-modify-write whole, and the record itself is only ever replaced.
        with open(folder / "named-links-denied.lock", "a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            denied = json.loads(record.read_text()) if record.exists() else {}
            if not isinstance(denied, dict):
                return False
            if key in denied:
                return False
            denied[key] = time.time()
            kept = dict(list(denied.items())[-KEEP:])
            handle, temporary = tempfile.mkstemp(dir=folder, prefix=".named-links-denied.")
            try:
                with os.fdopen(handle, "w") as stream:
                    json.dump(kept, stream)
                os.replace(temporary, record)
            except BaseException:
                os.unlink(temporary)
                raise
        return True
    except (OSError, ValueError):
        return False
