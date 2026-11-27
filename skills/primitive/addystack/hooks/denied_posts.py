"""The record of posts named-links-check.py denied, so it denies each at most once: an
identical retry, with the same session, target, and text, passes. Owns the record's file
($ADDYSTACK_STATE/named-links-denied.json, by default under ~/.local/state/addystack), its
key (a hash, so no posted text reaches disk), its bound, its lock, and its atomic write.
Any doubt passes the post: a record it can't read or write never denies."""


def first(session_id: object, target: str, text: str) -> bool:
    """True when this session hasn't been denied this text to this target, and the denial is
    now on record; False for a repeat, and when it can't tell or can't record."""
    raise NotImplementedError
