#!/usr/bin/env python3
"""UserPromptSubmit, in Claude Code and Codex: when the reply the user last saw cites an
issue or PR id without a link whose text names it (named_links.py), adds context only
the agent sees, asking it to cite each as `[ID, title](url)` from now on. It never
blocks the prompt and never asks for the old reply again, so no second reply posts; a
Stop hook that sent replies back did (commit 08be571)."""
import pathlib, sys
from typing import List

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))


def notice(ids: List[str]) -> str:
    """The context that names ids and asks for named links from now on."""
    raise NotImplementedError


def main() -> None:
    raise NotImplementedError


if __name__ == "__main__":
    main()
