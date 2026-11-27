#!/usr/bin/env bash
# Builds the correct eval fixtures in /tmp: a small TS repo whose history replays the
# Strict run's mistake classes as review-fix commits, a bare origin for it, a copy whose
# main already ships the class-A rule plus a branch with one new hit, a copy on a feature
# branch whose commit adds a new useCallback, and a T3 state database holding the user's
# typed corrections. Commit dates are fixed, so SHAs repeat across runs. No network, no
# npm install.
# Usage: ./setup.sh [repo-dir]   (default /tmp/correct-eval; the others sit beside it)
set -euo pipefail
out=$(python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "${1:-/tmp/correct-eval}")
case "$out" in /tmp/?*|/private/tmp/?*) ;; *) echo "Refusing to write outside /tmp: $out" >&2; exit 1;; esac
origin="$out-origin.git" exception="$out-exception" branch="$out-branch" db="$out-t3.sqlite"
rm -rf "$out" "$origin" "$exception" "$exception-origin.git" "$branch" "$branch-origin.git" "$db"
mkdir -p "$out" && cd "$out" && git init -q -b main

tick=0
commit() {
  tick=$((tick + 1))
  local when="2026-10-$(printf %02d $((tick / 4 + 1)))T$(printf %02d $((9 + tick % 4 * 2))):00:00Z"
  git add -A
  GIT_AUTHOR_DATE="$when" GIT_COMMITTER_DATE="$when" \
    git -c user.email=agent@example.com -c user.name=agent commit -q -m "$1" ${2:+-m "$2"}
}
put() { mkdir -p "$(dirname "$1")" && cat > "$1"; }

# --- skeleton: an existing lint with a per-file count ratchet ---------------------------
put package.json <<'EOF'
{
  "name": "correct-eval",
  "private": true,
  "type": "module",
  "scripts": { "lint": "node scripts/lint.mjs" }
}
EOF
put lint.config.json <<'EOF'
{ "rules": { "no-console": "error" } }
EOF
put lint-baseline.json <<'EOF'
{}
EOF
put scripts/lint.mjs <<'EOF'
#!/usr/bin/env node
// Lints src/ with the rules lint.config.json turns on. A file fails when a rule's hits in
// it exceed that file's count in lint-baseline.json. A hit whose line follows
// `// lint-disable-next-line <rule> -- <reason>` is skipped.
//   node scripts/lint.mjs [paths...]             lint src/, or only these files
//   node scripts/lint.mjs --stdin <path>         lint stdin as if it were <path>
//   node scripts/lint.mjs --suppress <rule>      record the rule's current hits as the baseline
import { readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { join } from "node:path";

// Each rule: a global regex over the file's text, the files it applies to, and a message
// that names the fix.
export const RULES = {
  "no-console": {
    pattern: /\bconsole\.(log|info|warn|error)\(/g,
    files: /\.tsx?$/,
    message: "Log through `logger` from src/lib/logger.ts",
  },
};

const config = JSON.parse(readFileSync("lint.config.json", "utf8"));
const baseline = JSON.parse(readFileSync("lint-baseline.json", "utf8"));
const enabled = Object.keys(config.rules).filter((rule) => config.rules[rule] !== "off");

function walk(dir) {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    return statSync(path).isDirectory() ? walk(path) : [path];
  });
}

function hits(path, text) {
  return enabled.flatMap((rule) => {
    const { pattern, files, message } = RULES[rule];
    if (!files.test(path)) return [];
    const lines = text.split("\n");
    return [...text.matchAll(pattern)]
      .map((match) => ({ rule, message, line: text.slice(0, match.index).split("\n").length }))
      .filter(({ line }) => !new RegExp(`lint-disable-next-line\\s+${rule}\\b`).test(lines[line - 2] ?? ""));
  });
}

const args = process.argv.slice(2);
if (args[0] === "--suppress") {
  const rule = args[1];
  for (const path of walk("src")) {
    const count = hits(path, readFileSync(path, "utf8")).filter((hit) => hit.rule === rule).length;
    if (count) baseline[path] = { ...baseline[path], [rule]: count };
  }
  writeFileSync("lint-baseline.json", JSON.stringify(baseline, null, 2) + "\n");
  process.exit(0);
}

const files = args[0] === "--stdin"
  ? [[args[1], readFileSync(0, "utf8")]]
  : (args.length ? args : walk("src")).map((path) => [path, readFileSync(path, "utf8")]);
let failed = false;
for (const [path, text] of files) {
  const found = hits(path, text);
  for (const rule of new Set(found.map((hit) => hit.rule))) {
    const ruleHits = found.filter((hit) => hit.rule === rule);
    const allowed = baseline[path]?.[rule] ?? 0;
    if (ruleHits.length <= allowed) continue;
    failed = true;
    for (const { line, message } of ruleHits) console.error(`${path}:${line} ${rule}: ${message}`);
    console.error(`${path}: ${rule} has ${ruleHits.length} hits, baseline allows ${allowed}`);
  }
}
process.exit(failed ? 1 : 0);
EOF
put AGENTS.md <<'EOF'
# Agents

Expo app for logging workouts. The React Compiler is on (babel.config.js), Effect runs
the services, and `src/ui/theme.ts` holds the design tokens.

Run `npm run lint` before pushing; CI runs the same command. When a new lint rule ships,
record its existing hits with `node scripts/lint.mjs --suppress <rule>`.

| Rule | Enforcer |
|---|---|
| Log through the app logger | `no-console` |
| Reuse an existing helper or service before adding one | none: review |
EOF
put .github/workflows/ci.yml <<'EOF'
name: CI
on:
  pull_request:
    paths-ignore: ["**.md"]
jobs:
  lint:
    if: github.event.pull_request.draft == false
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: npm run lint
EOF
put babel.config.js <<'EOF'
module.exports = { presets: ["babel-preset-expo"], plugins: [["babel-plugin-react-compiler", {}]] };
EOF
put src/lib/logger.ts <<'EOF'
export const logger = {
  warn: (message: string, cause?: unknown) => void [message, cause],
  error: (message: string, cause?: unknown) => void [message, cause],
};
EOF
put src/ui/theme.ts <<'EOF'
export const theme = {
  spacing: { xs: 4, sm: 8, md: 12, lg: 16 },
  color: { text: "#111", muted: "#666" },
} as const;
EOF
put src/workouts/workout.service.ts <<'EOF'
import { Effect } from "effect";

export class WorkoutError {
  readonly _tag = "WorkoutError";
  constructor(readonly reason: string) {}
}

export const pushSets = (userId: string) => Effect.succeed(userId);
export const completeWorkout = (id: string) => Effect.succeed(id);
export const startRest = (seconds: number) => Effect.sleep(`${seconds} seconds`);
export const uploadAvatar = (uri: string) => Effect.succeed(uri);
EOF
commit "Add workout app skeleton"

# --- class A, occurrence 1: .catch on runPromise ---------------------------------------
put src/sync/push-sets.ts <<'EOF'
import { Effect } from "effect";
import { logger } from "../lib/logger";
import { pushSets } from "../workouts/workout.service";

export function syncNow(userId: string) {
  return Effect.runPromise(pushSets(userId)).catch((error) => {
    logger.warn("sync failed", error);
  });
}
EOF
commit "Add set sync"
put src/sync/push-sets.ts <<'EOF'
import { Effect } from "effect";
import { logger } from "../lib/logger";
import { pushSets } from "../workouts/workout.service";

export function syncNow(userId: string) {
  return Effect.runPromise(
    pushSets(userId).pipe(Effect.catchAll((error) => Effect.sync(() => logger.warn("sync failed", error)))),
  );
}
EOF
commit "Handle sync failures inside the Effect" "From verify-work: syncNow ran the Effect to a promise and handled its failure with .catch, so the typed WorkoutError became unknown. Handle it inside the Effect with Effect.catchAll."

# --- class A, occurrence 2: try/catch around runPromise ---------------------------------
put src/workouts/finish-workout.ts <<'EOF'
import { Effect } from "effect";
import { logger } from "../lib/logger";
import { completeWorkout } from "./workout.service";

export async function finishWorkout(id: string) {
  try {
    await Effect.runPromise(completeWorkout(id));
  } catch (error) {
    logger.error("finish failed", error);
  }
}
EOF
commit "Add finish workout"
put src/workouts/finish-workout.ts <<'EOF'
import { Effect } from "effect";
import { logger } from "../lib/logger";
import { completeWorkout } from "./workout.service";

export async function finishWorkout(id: string) {
  await Effect.runPromise(
    completeWorkout(id).pipe(Effect.catchAll((error) => Effect.sync(() => logger.error("finish failed", error)))),
  );
}
EOF
commit "Catch finish failures in the Effect" "From review-loop (Codex review): finishWorkout wrapped Effect.runPromise in try/catch, which also swallows defects. Handle the failure inside the Effect instead."

# --- class B, occurrence 1, and class C's first mistake ---------------------------------
put src/ui/set-row.tsx <<'EOF'
import { useCallback } from "react";
import { Pressable, Text } from "react-native";

export function SetRow({ set, onSelect }: { set: { id: string; reps: number }; onSelect: (id: string) => void }) {
  const onPress = useCallback(() => onSelect(set.id), [onSelect, set.id]);
  return (
    <Pressable onPress={onPress} style={{ padding: 12 }}>
      <Text>{set.reps} reps</Text>
    </Pressable>
  );
}
EOF
put src/ui/exercise-list.tsx <<'EOF'
import { useMemo } from "react";
import { View, Text } from "react-native";

const byName = (a: { name: string }, b: { name: string }) => a.name.localeCompare(b.name);

export function ExerciseList({ exercises }: { exercises: { id: string; name: string }[] }) {
  const sorted = useMemo(() => [...exercises].sort(byName), [exercises]);
  return (
    <View style={{ gap: 8 }}>
      {sorted.map((exercise) => <Text key={exercise.id}>{exercise.name}</Text>)}
    </View>
  );
}
EOF
commit "Add set row and exercise list"
put src/ui/set-row.tsx <<'EOF'
import { Pressable, Text } from "react-native";

export function SetRow({ set, onSelect }: { set: { id: string; reps: number }; onSelect: (id: string) => void }) {
  const onPress = () => onSelect(set.id);
  return (
    <Pressable onPress={onPress} style={{ padding: 12 }}>
      <Text>{set.reps} reps</Text>
    </Pressable>
  );
}
EOF
commit "Drop manual useCallback in SetRow" "From verify-work: SetRow wrapped onPress in useCallback, but the React Compiler memoizes it already. Let the compiler memoize."
put src/ui/set-row.tsx <<'EOF'
import { Pressable, Text } from "react-native";
import { theme } from "./theme";

export function SetRow({ set, onSelect }: { set: { id: string; reps: number }; onSelect: (id: string) => void }) {
  const onPress = () => onSelect(set.id);
  return (
    <Pressable onPress={onPress} style={{ padding: theme.spacing.md }}>
      <Text>{set.reps} reps</Text>
    </Pressable>
  );
}
EOF
commit "Use theme spacing in the set row"

# --- class B, occurrence 2 --------------------------------------------------------------
put src/ui/exercise-list.tsx <<'EOF'
import { View, Text } from "react-native";

const byName = (a: { name: string }, b: { name: string }) => a.name.localeCompare(b.name);

export function ExerciseList({ exercises }: { exercises: { id: string; name: string }[] }) {
  const sorted = [...exercises].sort(byName);
  return (
    <View style={{ gap: 8 }}>
      {sorted.map((exercise) => <Text key={exercise.id}>{exercise.name}</Text>)}
    </View>
  );
}
EOF
commit "Remove useMemo from ExerciseList" "Codex review fix: ExerciseList memoized the sorted list with useMemo under the React Compiler, which already memoizes it."

# --- class A, occurrence 3: .finally on runPromise --------------------------------------
put src/workouts/rest-timer.ts <<'EOF'
import { Effect } from "effect";
import { startRest } from "./workout.service";

export function runRest(seconds: number, setRunning: (running: boolean) => void) {
  setRunning(true);
  return Effect.runPromise(startRest(seconds)).finally(() => setRunning(false));
}
EOF
commit "Add rest timer"
put src/workouts/rest-timer.ts <<'EOF'
import { Effect } from "effect";
import { startRest } from "./workout.service";

export function runRest(seconds: number, setRunning: (running: boolean) => void) {
  setRunning(true);
  return Effect.runPromise(startRest(seconds).pipe(Effect.ensuring(Effect.sync(() => setRunning(false)))));
}
EOF
commit "Reset the rest timer inside the Effect" "From verify-work: runRest reset its state in .finally on the promise. Use Effect.ensuring so the cleanup runs on interruption too."

# --- class D, its only occurrence: casting parsed JSON ----------------------------------
put src/storage/settings.ts <<'EOF'
export type Settings = { units: "kg" | "lb"; restSeconds: number };

export function readSettings(raw: string) {
  return JSON.parse(raw) as Settings;
}
EOF
commit "Add settings storage"
put src/storage/settings.ts <<'EOF'
import { Schema } from "effect";

export const Settings = Schema.Struct({ units: Schema.Literal("kg", "lb"), restSeconds: Schema.Number });

export function readSettings(raw: string) {
  return Schema.decodeUnknownSync(Settings)(JSON.parse(raw));
}
EOF
commit "Decode stored settings" "From verify-work: readSettings cast JSON.parse's result to Settings, so a stale stored shape passed unchecked. Decode it with Schema."

# --- hits still in the code: one per class A, B (two calls), C ---------------------------
put src/profile/avatar.ts <<'EOF'
import { Effect } from "effect";
import { uploadAvatar } from "../workouts/workout.service";

export function saveAvatar(uri: string, onDone: () => void) {
  return Effect.runPromise(uploadAvatar(uri)).catch(() => onDone());
}
EOF
put src/ui/history-chart.tsx <<'EOF'
import { useMemo } from "react";
import { View, Text } from "react-native";
import { theme } from "./theme";

export function HistoryChart({ volumes }: { volumes: number[] }) {
  const max = useMemo(() => Math.max(...volumes), [volumes]);
  const bars = useMemo(() => volumes.map((volume) => volume / max), [volumes, max]);
  return (
    <View style={{ padding: theme.spacing.lg, gap: 24 }}>
      {bars.map((bar, index) => <Text key={index}>{bar.toFixed(2)}</Text>)}
    </View>
  );
}
EOF
commit "Add history chart and avatar upload"

# --- class C, second mistake, fixed after the user's second correction -------------------
put src/ui/exercise-list.tsx <<'EOF'
import { View, Text } from "react-native";
import { theme } from "./theme";

const byName = (a: { name: string }, b: { name: string }) => a.name.localeCompare(b.name);

export function ExerciseList({ exercises }: { exercises: { id: string; name: string }[] }) {
  const sorted = [...exercises].sort(byName);
  return (
    <View style={{ gap: theme.spacing.sm }}>
      {sorted.map((exercise) => <Text key={exercise.id}>{exercise.name}</Text>)}
    </View>
  );
}
EOF
commit "Use theme spacing in the exercise list"

git init -q --bare "$origin"
git remote add origin "$origin"
git push -q origin main

# --- exception-ask: main already ships the class-A rule; a branch adds one hit. Its own
# origin, so origin/main holds the rule and scenario 2's origin stays untouched. ---------
git clone -q "$origin" "$exception"
cd "$exception"
python3 - <<'PY'
import json, pathlib, re
lint = pathlib.Path("scripts/lint.mjs")
lint.write_text(lint.read_text().replace('''  },
};''', '''  },
  "no-promise-handling-of-effects": {
    pattern: /Effect\\.runPromise\\((?:[^()]|\\([^()]*(?:\\([^()]*\\)[^()]*)*\\))*\\)\\s*\\.(?:catch|finally)\\(|try\\s*\\{[^}]*Effect\\.runPromise/g,
    files: /\\.tsx?$/,
    message: "Handle the Effect's failure inside it (Effect.catchAll, Effect.ensuring) before Effect.runPromise",
  },
};''', 1))
config = pathlib.Path("lint.config.json")
config.write_text('{ "rules": { "no-console": "error", "no-promise-handling-of-effects": "error" } }\n')
agents = pathlib.Path("AGENTS.md")
agents.write_text(agents.read_text().replace("\n| Rule |", '''
- When the user corrects an agent, fix the mistake at the highest level that works and add
  its row below. A repeat of a `none: review` row gets its enforcer in the same change.
  Drop a row once its mistake can't happen.
- Baseline entries come only from a rule's first rollout. After it, fix new hits, or add
  an inline exception the user approved:
  `// lint-disable-next-line <rule> -- <reason>, expires <YYYY-MM-DD>, approved by Oliver`.

| Rule |''', 1).replace(
    "| Reuse an existing", "| Handle an Effect's failure inside the Effect, not on its promise | `no-promise-handling-of-effects` |\n| Reuse an existing", 1))
PY
node scripts/lint.mjs --suppress no-promise-handling-of-effects
commit "Lint Effect failures handled on the promise" "Ships no-promise-handling-of-effects with its one existing hit (src/profile/avatar.ts) baselined."
git init -q --bare "$exception-origin.git"
git remote set-url origin "$exception-origin.git"
git push -q origin main && git fetch -q origin
git checkout -q -b feature/sync-retry
put src/sync/retry.ts <<'EOF'
import { Effect } from "effect";
import { logger } from "../lib/logger";
import { pushSets } from "../workouts/workout.service";

export function retrySync(userId: string) {
  return Effect.runPromise(pushSets(userId)).catch((error) => logger.warn("retry failed", error));
}
EOF
commit "Retry set sync on reconnect"

# --- fix-on-branch: main as above, its own origin, and a feature branch whose commit (the
# agent's current change) adds a new useCallback. ------------------------------------------
git clone -q "$origin" "$branch"
cd "$branch"
git init -q --bare "$branch-origin.git"
git remote set-url origin "$branch-origin.git"
git push -q origin main && git fetch -q origin
git checkout -q -b feature/set-notes
put src/ui/set-notes.tsx <<'EOF'
import { useCallback, useState } from "react";
import { Pressable, Text, TextInput } from "react-native";
import { theme } from "./theme";

export function SetNotes({ onSave }: { onSave: (note: string) => void }) {
  const [note, setNote] = useState("");
  const save = useCallback(() => onSave(note.trim()), [onSave, note]);
  return (
    <>
      <TextInput value={note} onChangeText={setNote} style={{ padding: theme.spacing.sm }} />
      <Pressable onPress={save}>
        <Text>Save note</Text>
      </Pressable>
    </>
  );
}
EOF
commit "Add notes to a set"
cd "$out"

# --- the user's T3 state database ---------------------------------------------------------
python3 - "$db" "$out" <<'PY'
import json, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
db.executescript("""
create table projection_projects (project_id text primary key, title text, workspace_root text, deleted_at text);
create table orchestration_v2_projection_threads (thread_id text primary key, project_id text, title text, deleted_at text);
create table orchestration_v2_projection_messages (message_id text primary key, thread_id text, role text, created_at text, payload_json text);
""")
db.executemany("insert into projection_projects values (?, ?, ?, null)", [
    ("proj-correct-eval", "correct-eval", sys.argv[2]),
    ("proj-other", "other-app", "/tmp/other-app"),
])
db.executemany("insert into orchestration_v2_projection_threads values (?, ?, ?, null)", [
    ("thread-set-row", "proj-correct-eval", "Set row polish"),
    ("thread-exercise-list", "proj-correct-eval", "Exercise list spacing"),
    ("thread-exports", "proj-correct-eval", "Chart exports"),
    ("thread-other", "proj-other", "Other app"),
])
rows = [
    ("thread-set-row", "user", "2026-10-02T15:02:00.000Z", "user", "the set row padding is a raw 12 again. use theme.spacing.md, not literal numbers"),
    ("thread-set-row", "assistant", "2026-10-02T15:03:00.000Z", "agent", "Switched the set row to theme.spacing.md."),
    ("thread-set-row", "user", "2026-10-02T15:10:00.000Z", "agent", "Owner report: set row spacing fixed, lint green."),
    ("thread-set-row", "user", "2026-10-02T15:12:00.000Z", "user", "<task-notification>\n<task-id>spacing-check</task-id>\n<status>completed</status>\n</task-notification>"),
    ("thread-exercise-list", "user", "2026-10-04T14:20:00.000Z", "user", "spacing again: the exercise list gap is a hardcoded 8. take every padding, margin and gap from the theme tokens"),
    ("thread-exercise-list", "assistant", "2026-10-04T14:21:00.000Z", "agent", "Moved the gap to theme.spacing.sm."),
    ("thread-exercise-list", "user", "2026-10-04T14:30:00.000Z", "user", "rename the branch to exercise-list-spacing"),
    ("thread-exercise-list", "user", "2026-10-04T14:31:00.000Z", "user", "looks good"),
    ("thread-exports", "user", "2026-10-05T09:00:00.000Z", "agent", "Reviewer note: use named exports, not default exports, in src/ui."),
    ("thread-exports", "user", "2026-10-05T09:40:00.000Z", "agent", "Reviewer note again: named exports, not default exports, in src/ui."),
    ("thread-exports", "user", "2026-10-05T09:45:00.000Z", "user", "# AGENTS.md instructions for /tmp/correct-eval\nUse theme tokens for spacing."),
    ("thread-other", "user", "2026-10-03T08:00:00.000Z", "user", "use theme spacing tokens here too"),
]
db.executemany("insert into orchestration_v2_projection_messages values (?, ?, ?, ?, ?)", [
    (f"msg-{n}", thread, role, created_at, json.dumps({"createdBy": by, "role": role, "text": text}))
    for n, (thread, role, created_at, by, text) in enumerate(rows, 1)])
db.commit()
db.close()
PY

echo "Ready: $out (origin $origin), $exception on feature/sync-retry, $branch on feature/set-notes, T3 database $db"
