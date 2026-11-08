#!/usr/bin/env bash
# Copy of skills/primitive/show-me-your-work/scripts/log.sh, written by scripts/sync-copies.py: edit the source, then run the script.
# Append a well-formed row to a show-me-your-work decision log (TSV).
# Usage: log.sh [--pr you|agent] <logfile> <phase> <decision> <why> <evidence> <result>
#        log.sh import <logfile> <plan-or-brief>
# --pr marks a call a PR reviewer should see: `you` when the user made it, `agent` when
# the agent did. Its evidence must hold a path:line or a commit SHA, so the row can link
# to code. `import` logs each `D<n>. …` line of a saved plan or brief as a `plan` row:
# `agent` when the line ends `[assumed]` (the user never picked it), `you` otherwise.
set -euo pipefail

usage() {
	printf 'usage: log.sh [--pr you|agent] <logfile> <phase> <decision> <why> <evidence> <result>\n       log.sh import <logfile> <plan-or-brief>\n' >&2
	exit 1
}

header6=$'ts\tphase\tdecision\twhy\tevidence\tresult'
header7=$'ts\tphase\tdecision\twhy\tevidence\tresult\tpr'

# Start a log, or check the one that's there. Prints its column count. Use `>>`, never
# `>`: a network mount can fail `-s` for a log that exists, and then the cost is one
# stray header line, not the rows.
open_log() {
	local logfile="$1" logdir first
	logdir="$(dirname "$logfile")"
	[ -d "$logdir" ] || mkdir -p "$logdir"
	if [ ! -s "$logfile" ]; then
		printf '%s\n' "$header7" >> "$logfile"
	fi
	IFS= read -r first < "$logfile" || true
	case "$first" in
		"$header7") echo 7 ;;
		"$header6") echo 6 ;;
		*) printf 'log.sh: %s has another header, so it is not a show-me-your-work log\n' "$logfile" >&2; exit 1 ;;
	esac
}

# Strip tabs/newlines/CR so cells stay on one line, and prefix any cell
# whose first char a spreadsheet would parse as a formula (=, +, -, @)
# with a single quote. The skill expects this log to be read in
# spreadsheets, so attacker-controlled evidence (PR titles, filenames,
# generated text) must not become formula execution when a reviewer
# opens the file.
clean() {
	local v
	v=$(printf '%s' "$1" | tr '\t\n\r' '   ')
	case "$v" in
		=*|+*|-*|@*) printf "'%s" "$v" ;;
		*) printf '%s' "$v" ;;
	esac
}

# append <logfile> <columns> <pr> <phase> <decision> <why> <evidence> <result>
append() {
	local logfile="$1" columns="$2" pr="$3"
	shift 3
	if [ -n "$pr" ]; then
		case "$pr" in you|agent) ;; *) printf 'log.sh: --pr takes you or agent, not %s\n' "$pr" >&2; exit 1 ;; esac
		if [ "$columns" = 6 ]; then
			printf 'log.sh: %s has no pr column; start a new log to use --pr\n' "$logfile" >&2
			exit 1
		fi
		# A timestamp's HH:MM would pass as path:line, so drop timestamps first.
		if ! printf '%s' "$4" | sed -E 's/[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z?//g' | grep -Eq '[^[:space:]:]*[A-Za-z_][^[:space:]:]*:[0-9]+|(^|[^0-9a-zA-Z])[0-9a-f]{7,40}($|[^0-9a-zA-Z])'; then
			printf 'log.sh: a --pr row needs a path:line or a commit SHA in its evidence, not "%s"\n' "$4" >&2
			exit 1
		fi
	fi
	local row ts
	ts="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
	row="$ts"$'\t'"$(clean "$1")"$'\t'"$(clean "$2")"$'\t'"$(clean "$3")"$'\t'"$(clean "$4")"$'\t'"$(clean "$5")"
	[ "$columns" = 6 ] || row="$row"$'\t'"$pr"
	printf '%s\n' "$row" >> "$logfile"
}

if [ "${1:-}" = import ]; then
	[ "$#" -eq 3 ] || usage
	logfile="$2"
	plan="$(cd "$(dirname "$3")" && pwd)/$(basename "$3")"
	[ -f "$plan" ] || { printf 'log.sh: no plan at %s\n' "$3" >&2; exit 1; }
	columns="$(open_log "$logfile")"
	[ "$columns" = 7 ] || { printf 'log.sh: %s has no pr column; start a new log to import\n' "$logfile" >&2; exit 1; }
	n=0 found=0
	while IFS= read -r line || [ -n "$line" ]; do
		n=$((n + 1))
		[[ "$line" =~ ^[[:space:]*-]*(D[0-9]+\.[[:space:]].*)$ ]] || continue
		decision="${BASH_REMATCH[1]}"
		decision="${decision%"${decision##*[![:space:]]}"}"
		if [[ "$decision" == *"[assumed]" ]]; then
			decision="${decision%\[assumed\]}"
			decision="${decision%"${decision##*[![:space:]]}"}"
			append "$logfile" 7 agent plan "$decision" "assumed in the plan; the user never picked it" "$plan:$n" planned
		else
			append "$logfile" 7 you plan "$decision" "the user decided it in the plan" "$plan:$n" planned
		fi
		found=$((found + 1))
	done < "$plan"
	printf 'log.sh: imported %d decisions from %s\n' "$found" "$3" >&2
	exit 0
fi

pr=""
if [ "${1:-}" = --pr ]; then
	[ "$#" -ge 2 ] || usage
	pr="$2"
	[ -n "$pr" ] || { printf 'log.sh: --pr takes you or agent\n' >&2; exit 1; }
	shift 2
fi
[ "$#" -eq 6 ] || usage

logfile="$1"
shift
columns="$(open_log "$logfile")"
append "$logfile" "$columns" "$pr" "$@"
