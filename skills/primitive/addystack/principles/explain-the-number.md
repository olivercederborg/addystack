# Explain the number

**Apply when** you're about to measure, or to trust, report, or act on a number you
measured: a speedup, a regression, a latency, a throughput, or an eval result.

Find what limits the number, and rule out that it measured something other than the
work you think.

**Why:** "For performance work, measure the bottleneck first". A run that went wrong
still prints a plausible number.

**Pattern:**
- **Decide before you run**: write the decision the run informs, the result that would
  change it, and the noise floor. Stop when the run-to-run spread is larger than the
  effect.
- **Ask "why not double?"**: name the core, lock, disk, network, or load generator that
  bounds the result, from a profile or counters taken during the run, mapped to source.
- **Rule out the suspects**: failed requests, cached or skipped work, a side left on
  defaults, run-to-run noise, and a piece too small to matter end to end.
- **Evals**: check every trial did the task and the gap holds across trials and models.
- **Keep the evidence with it**: the run count, the spread, and the limiter.

**Tell:** a run started with no result that would change a decision, a number with no
run count, no spread, or no named limiter, or a saving bigger than the time the changed
piece took.
