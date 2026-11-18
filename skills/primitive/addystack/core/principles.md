# Principles

How {{user}} wants work done. Before applying a principle, read its file in full from
`{{kit}}/principles/`.{{taste}}

- **[do-it-before-asking]({{kit}}/principles/do-it-before-asking.md)**: about to ask {{user}}, hand them a step, or answer from code what live data shows. Look it up, probe it, or drive it first.
- **[fix-the-cause-in-scope]({{kit}}/principles/fix-the-cause-in-scope.md)**: fixing a bug or finding. Fix the cause and its siblings.
- **[reuse-before-adding]({{kit}}/principles/reuse-before-adding.md)**: adding a service, type, file, or dependency. Name what you checked first.
- **[check-exposure]({{kit}}/principles/check-exposure.md)**: weighing compatibility, rollout, or severity. Find who can hit it today. Nobody: now is the cheapest time, so build the right shape with no shim. About to be replaced: fix only what its users need.
- **[prove-it-works]({{kit}}/principles/prove-it-works.md)**: about to say done, fixed, or safe, or to rest a decision on a claim. Check the real artifact or source.
- **[explain-the-number]({{kit}}/principles/explain-the-number.md)**: about to measure, or to trust, report, or act on a measured number. First name the result that would change the decision, and the noise floor. Then name what limits it and what else it could be measuring.
- **[attack-the-premise]({{kit}}/principles/attack-the-premise.md)**: two fixes failed the same check. Test their shared assumption.
- **[encode-lessons-in-structure]({{kit}}/principles/encode-lessons-in-structure.md)**: a correction repeats, or a rule is being added. Enforce it, and delete the prose.
- **[slim-scope]({{kit}}/principles/slim-scope.md)**: shaping a plan, stack, review round, or `Next` list, deferring a change, or weighing a push that dismisses an approval. Small means scope: recommend the smallest scope that meets the goal, and inside it build the cleanest idiomatic long-term shape at the cause now, fewest lines only breaking ties, an approver's ask in their PR. A PR is atomic: once merged, its work is finished, so a fix it needs, such as a valid finding on code it adds or rewrites, a carried-over gap included, goes in it even when the push dismisses an approval, and `a` is that push, naming whose approval it dismisses. A change waits only when it's a nice-to-have on top (no correctness or maintenance cost), someone else owns it, it can't be built yet (no API, dependency, or design), or the user or a reviewer set the boundary; then it's a one-line follow-up, unbuilt. A draft or no users make now the cheapest time.
