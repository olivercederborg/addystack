# addystack evals

[`evals.json`](evals.json) holds two runnable scenarios, each in its own folder under
`/tmp` built by [`setup.sh`](setup.sh), with the config, state folder, and host files
inside it:

- **explain-stop**: why a checkout stopped at a draft PR, answered from
  `addystack policy --explain` with nothing written.
- **change-previews**: "stop before merging" in one repo becomes a `policy.repos` rule,
  previewed as a diff with the config untouched, then written, built, and proved with
  `--explain` after the user's okay.

Run them with the runner in [evals](../README.md#run-with-the-runner).
