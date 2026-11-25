"""Finds the issue and PR ids a Markdown text cites without a link whose text names
them, as reply-shape's "Links that name" asks: `[DEV-3127, Allow failure-only export
emails](https://linear.app/…)`, once a text. Owns every rule about it: what text is
visible (not code, not HTML comments, which hide the turn block), what counts as an id
(a Linear-style `ABC-123` that isn't a standard such as UTF-8, `#N`, `repo#N`), and what
counts as named (a link whose text holds the id and words). named-links-notice.py reads
replies with it, and scripts/check_examples.py the kit's example replies."""
from typing import List, NamedTuple


class Cited(NamedTuple):
    id: str    # as first written: "DEV-3127", "#124", "dotfiles#12"
    line: int  # the 0-based line of text that first cites it


def unnamed(text: str) -> List[Cited]:
    """Each id text cites in visible prose with no link anywhere in text that names it,
    once, in the order first cited."""
    raise NotImplementedError
