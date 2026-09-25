# codex challenge — range f2f43489634ff81ba8799468dc204e231c9885dc..884e3343891e260c27897b02fdcc63c2441c38b5 — checkout /Users/turbokach/Dev/ai-token-burn-output — model gpt-6-astra/medium — exit 0 — 98s
tools/publish.sh:145 — Publishing from a stale second checkout overwrites newer remote history: the fetch updates `.output`, but collection merges only local `data/stats.json`, which then replaces the fetched snapshot.

tools/publish.sh:114 — If another publisher pushes between fetch and push, the rejected local commit leaves `output` diverged; every subsequent run fails at `merge --ff-only`, stopping scheduled publication indefinitely.

accumulate.py:88 — Migration subtracts unrelated new days from historical aggregates: one pruned session plus one new session at the same hour produces a count of one instead of two; cache totals suffer the same permanent undercount.

accumulate.py:184 — Restoring transcripts for a previously undetailed day double-counts its usage because its fixed legacy contribution survives alongside the newly accepted detail; reproduced model totals of 300 against an overview of 200.

accumulate.py:167 — Selecting whole rows solely by token count now discards retained hours, cache usage and subagent counts when partial pruning plus a resumed session produces an equal-or-higher-token replacement; reproduced cache usage falling from 1,000 to 1.

accumulate.py:130 — Subagent migration repairs only positive gaps; old input-heavy aggregates combined with output-heavy replacement detail can exceed `subTokens`, permanently publishing model percentages above 100%.

collect.py:62 — An existing but truncated or unreadable snapshot passes the publisher’s existence guard, then silently triggers fresh collection and overwrites retained history, including days whose transcripts were pruned.

collect.py:29 — Overlapping manual and scheduled publications share the same temporary filename without locking; one process can rename it while another still writes, exposing partial JSON, losing updates and making the other process fail at `os.replace`.

tools/setup.sh:20 — Checkout paths containing `&` expand the sed replacement placeholder instead of preserving the path; XML-special characters are also unescaped, producing an unusable launchd configuration.