# Update

## 1. Look up, before updating

- **The installed release's newest entry**: the first `## ` heading of
  `<kit>/CHANGELOG.md`. Keep it. A kit without a CHANGELOG has no entries to compare.
- **Each built note's first line**: `head -1` of each file in
  `~/.local/state/addystack/notes/`. Each records the hash of its skill when it was
  built.

## 2. Update

Show the command and what it will change, then run it on the user's okay; it has no
dry run. Run `<kit>/bin/addystack update`. It updates the kit and its skills, adds the skills
the release makes core, removes the ones it dropped, then installs, which builds and
runs `doctor`. It runs without a terminal. When only `doctor` fails, the update landed:
go on to steps 3 and 4, then report doctor's failure and its `fix:` line, since a note
on a dropped skill fails it. When an earlier step fails, report its error and the
`fix:` line, and stop.

## 3. Summarize

Read `<kit>/CHANGELOG.md` again and summarize each entry above the heading you kept,
breaking changes first. When the kept heading isn't there, or there was none,
summarize the newest entry and say older entries weren't compared. When the release has
no CHANGELOG, say so.

## 4. Flag notes

A note needs a look when:

- `doctor`'s `notes` check names it: its skill is gone or no longer core;
- its built first line changed from the one you kept: its skill changed in this update,
  so a step the note anchors on may have moved. The build already refreshed the hash, so
  `doctor` alone can't show this.

For each, name the note and its skill, read the skill's changed text, and say whether
the note still fits. Offer a Note edit for any that doesn't.

**Done when:** the reply names the release it moved from and to (the kept and new
CHANGELOG headings), summarizes the new entries (or says
there's no CHANGELOG), and lists each note that needs a look, or says none do.
