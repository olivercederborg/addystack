# Upstream

A change to the kit that would help every user: a step a core skill misses, a wrong
fact, a hook gap. It becomes a draft PR to the kit's repo for its maintainer to review.
This job opens the draft and stops; marking it ready and merging are the maintainer's.

## 1. Check it belongs upstream

It belongs in the kit when a user with other repos, hosts, and habits would want it too.
A preference of this user's (their repos, their tools, their wording) is a Change or a
Note instead; say which, and offer it.

The kit's text names "the user", never a person, and holds no one's paths, hosts,
machines, or team. Write the change that way.

## 2. Look up

- **The kit's repo.** In a git checkout of the kit, `git -C <kit> remote get-url origin`.
  Otherwise the `source` of the `addystack` entry in the skills CLI's lock file
  (`$XDG_STATE_HOME/skills/.skill-lock.json`, or `~/.agents/.skill-lock.json`).
- **Push rights.** `gh repo view <repo> --json viewerPermission`. Without `WRITE` or
  above, the branch goes through a fork (step 4).
- **Its rules.** In a fresh clone (`gh repo clone <repo> <scratch>/kit`), read its
  README and contributing notes, run `git config core.hooksPath .githooks` when the repo
  has one, and run `<clone>/skills/primitive/addystack/bin/addystack policy --repo <clone>`
  for how it takes branches, pushes, and PRs.

## 3. Preview

Make the change on a new branch in the clone and run the repo's checks, such as its
pre-commit hook. Show the user:

- the `diff`;
- the PR title and body: the problem, the evidence that it's general (with nothing
  private in it), and the checks run.

Opening a PR sends it to a person, so the user's okay on this preview is required.

## 4. Open the draft

Commit, push the branch the way the policy says, and open it as a draft:
`gh pr create --draft --repo <repo>`.

Without push rights, go through a fork:

1. In the clone, `gh repo fork --remote --remote-name fork` forks the repo and adds the
   fork as the `fork` remote, leaving `origin` on the kit's repo.
2. `git push -u fork <branch>`, even when the policy says gh stack: a stack's later PRs
   need their base branches in the kit's repo, so the fork carries one branch.
3. `gh pr create --draft --repo <repo> --head <fork owner>:<branch>`, where the fork
   owner is `gh api user --jq .login`.

**Done when:** the draft PR's URL is in the reply, or the reply says what's waiting on
the user.
