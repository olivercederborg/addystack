Review this {kind}. Leave the repo as it is: do not edit, stage, commit, push, comment,
or run destructive commands. This prompt is the whole review; use it in place of any
review skill.

Target: {target}
Scope: {scope}
Spec: {spec}
Packet: {packet}
{round}
Checks already run:
{checks}
Rerun none of these.

{lenses}

{ask}
Prove each finding with a run against the real code, such as a failing test, a repro
script, or command output that shows the wrong behavior. For a doc or prompt, quote the
line made false and the case it gets wrong, or the two lines that conflict. For a plan,
probe the current tree or run a prototype. Keep repros under a fresh `mktemp -d`. Give
each finding the exact command, the output it printed, and the output the intent
requires. When a run needs what you lack, such as installed dependencies, give its
command and mark the finding unproven. For a rule the repo documents, quote it and the
line that breaks it. Leave out anything you did not show, such as style, naming, or
structure no documented rule names, and risks that need a future change to matter
other than a maintenance cost the change adds.
Blocker: wrong behavior, data loss, security, a failing check, or a broken rule.
Cleanup: scope creep, a changed line no test protects (shown by a mutant of it that passes),
or a maintenance cost the change adds, such as logic it writes twice (cite each copy).
When the intent asks for a minimal change, Cleanup also covers each part of the diff the
intent still meets without, shown by the checks passing with it removed.
Optional: a nicety with no correctness or maintenance cost; a finding with either is a
Blocker or Cleanup.
Label a finding Pre-existing when the change didn't cause, newly reach, or worsen it,
whatever its severity.
Give a complete, independent review. No findings is a valid result; say so.
