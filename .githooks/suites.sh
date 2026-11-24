# Sourced by .githooks/pre-commit and .githooks/pre-push, with $root and $hooks_staged set.
# Each folder's test_*.py, on this machine, counting the suites it runs in suites_ran.
suites_ran=0
run_suites() {
  local tests file
  for tests in "$@"; do
    # The folder stays literal, so a [ or * in its path can't glob; the first test file
    # that exists runs the folder once, whatever nullglob or a dangling link does.
    for file in "$tests"/test_*.py; do
      if [ -e "$file" ]; then
        PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -q -s "$tests" -p 'test_*.py'
        suites_ran=$((suites_ran + 1))
        break
      fi
    done
  done
}

# The kit's suites, which are Dagger checks: each shipped skill's scripts/test_*.py
# (skills/<layer>/<skill>/scripts), shared/scripts', scripts/', and the tool's
# hooks/test_*.py when hooks_staged. Finding none blocks the commit, since a folder list
# that matches nothing would otherwise pass it untested.
host_suites() {
  # Declared, then assigned: bash 3.2 does no brace expansion inside `local dirs=(…)`.
  local dirs
  dirs=("$root"/skills/{primitive,orchestrator,optional}/*/scripts "$root"/shared/scripts "$root"/scripts)
  if $hooks_staged; then dirs+=("$root"/skills/primitive/addystack/hooks); fi
  run_suites "${dirs[@]}"
  if [ "$suites_ran" = 0 ]; then
    echo "pre-commit: no host test suite ran, since none of these has a test_*.py:" \
         "${dirs[*]#"$root"/}; fix host_suites' folder list in .githooks/pre-commit" >&2
    exit 1
  fi
}
