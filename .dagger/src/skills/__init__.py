"""The kit's push checks as Dagger checks, one per suite.

Each check loads only its suite's files, through its `source` argument's Ignore
patterns, so a change outside them (say, under docs/) leaves that check's cached result in
place. A suite whose tests read a file outside its patterns fails on the missing file, so
widen the patterns rather than the test.

Run them all with `dagger check`, one with `dagger check hooks-tests`, and list them with
`dagger check -l`.
"""

from .main import Skills as Skills
