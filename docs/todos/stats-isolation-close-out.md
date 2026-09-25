# stats-isolation close-out (2026-09-25)

Leftovers from the code/data split + per-day records arc (range f2f4348..884e334) that were not codex findings.

- **Failed push is never retried** (found by the fixer, pre-existing): if `git commit` on `output` succeeds but `git push` fails, the next run compares against the local `output` HEAD, sees no change, and does not push until the next day's data changes. Self-heals on the following daily run; a check of `origin/output` vs local `output` before exiting would close it.
