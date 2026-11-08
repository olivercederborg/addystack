#!/usr/bin/env bash
# Checks every SKILL.md's frontmatter: it opens and closes with ---, has a name that
# matches its folder and a description, and each one-line top-level value is valid
# YAML (an unquoted value can't contain ": " or " #", or start with a YAML indicator).
# Block values (`key: >`) and nested maps (`key:` then indented lines) are left as is.
# A skill hidden from Claude's model (disable-model-invocation: true) must also be hidden
# from Codex's, through its agents/openai.yaml policy.
# Usage: scripts/check-frontmatter.sh   # exit 1 on any problem
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
python3 - "$root" <<'PY'
import pathlib, re, sys
root = pathlib.Path(sys.argv[1])
INDICATORS = tuple("[]{}#&*!|>%@`,")
problems = []
for skill in sorted(root.glob("skills/*/*/SKILL.md")):
    where = skill.relative_to(root)
    lines = skill.read_text().split("\n")
    if lines[0] != "---" or "---" not in lines[1:]:
        problems.append(f"{where}: frontmatter must open and close with ---")
        continue
    fields, key = {}, None
    for number, line in enumerate(lines[1:lines.index("---", 1)], 2):
        if not line.strip() or line[0] in " \t":
            # A block value's or nested map's indented line; it also gives `key:` a value.
            if key and line.strip() and not fields[key]:
                fields[key] = line.strip()
            continue
        match = re.match(r"([A-Za-z_-]+):(?: (.*))?$", line)
        if not match:
            problems.append(f"{where}:{number}: expected a top-level `key: value`")
            continue
        key, value = match.group(1), (match.group(2) or "").strip()
        fields[key] = value
        quoted = len(value) > 1 and value[0] == value[-1] and value[0] in "'\""
        if quoted or not value or re.fullmatch(r"[>|][+-]?[1-9]?", value):
            continue
        if value.startswith(INDICATORS) or value.startswith(("'", '"')):
            problems.append(f"{where}:{number}: {key} starts with a YAML indicator; quote it")
        elif ": " in value or value.endswith(":"):
            problems.append(f"{where}:{number}: {key} contains ': '; reword or quote it")
        elif " #" in value:
            problems.append(f"{where}:{number}: {key} contains ' #', which starts a comment; quote it")
    if fields.get("name") != skill.parent.name:
        problems.append(f"{where}: name must be {skill.parent.name!r}")
    if not fields.get("description"):
        problems.append(f"{where}: description is missing")
    # Codex ignores disable-model-invocation and lists the skill in every session.
    policy = skill.parent / "agents" / "openai.yaml"
    if fields.get("disable-model-invocation") == "true" and not (
        policy.exists() and re.search(r"^\s+allow_implicit_invocation: false\s*$", policy.read_text(), re.M)
    ):
        problems.append(f"{where}: hidden from Claude only; add `allow_implicit_invocation: false` under `policy:` in {policy.relative_to(root)}")
print(*problems, sep="\n") if problems else print("frontmatter valid")
sys.exit(1 if problems else 0)
PY
