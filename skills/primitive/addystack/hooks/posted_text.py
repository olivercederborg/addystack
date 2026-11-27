"""Which text a tool call is about to post, and where, for named-links-check.py. Owns every
rule about it: the routes (gh pr create, edit, and comment in Bash; T3's pull_request_create
and pull_request_update; Linear's save_issue, save_comment, and save_project, directly or
through Executor's `call`), gh's body flags, a heredoc the same command writes to its body
file, a body file's bounds, and Linear's fields and patch operations. Titles and relation
fields are never posted text here.

A body it can't place, such as stdin, a FIFO, a device, an oversized or unreadable file, or
a file the command writes some other way than a heredoc, yields no Post, so the check
passes it."""
from typing import List, NamedTuple, Optional

# The tool names whose calls may post text, as one regex both runtimes' manifest entries
# carry; test_named_links checks the manifest against it.
MATCHER = ("Bash|mcp__t3-code__pull_request_(create|update)"
           "|mcp__.*[Ll]inear.*__save_(issue|comment|project)|mcp__executor-.+__call")


class Post(NamedTuple):
    target: str  # where it posts, as the call names it: "gh pr comment 12", "save_issue DEV-4"
    text: str    # the Markdown it posts there


def posts(tool_name: object, tool_input: object, cwd: Optional[str]) -> List[Post]:
    """Each text this call would post that can be placed, in the order the call posts them;
    [] for any other call or a shape it doesn't expect."""
    raise NotImplementedError
