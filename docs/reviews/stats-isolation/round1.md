# codex challenge — range f2f43489634ff81ba8799468dc204e231c9885dc..7454ceb58c99f1a11af995e47c03fc13940d9ea2 — checkout /Users/turbokach/Dev/ai-token-burn-output — model gpt-6-astra/medium — exit 0 — 130s
data/stats.json:1 — Deleting the tracked accumulation state erases retained history on a clean upgrade; the next publish rebuilds from surviving logs, permanently omitting pruned days unless manually recovered from Git.

tools/publish.sh:74 — Publishing from two machines silently loses history: fetching and fast-forwarding `output` never merges its stats into local accumulation, so an older machine overwrites newer remote history and successfully pushes it.

accumulate.py:184 — Legacy residuals remain fixed when an undetailed historical row gains detail; restore previously unavailable logs after migration and a 100-token day produces 200 model tokens while the overview remains 100.

accumulate.py:85 — Migration subtracts detail from newly added days from historical aggregates; one pruned session plus one new session at the same hour becomes one session in `hourCounts`, and historical cache counts are similarly lost.

accumulate.py:167 — Selecting entire rows solely by token count now discards preserved detail: prune some sessions and grow a surviving session past the previous daily total, and hours, cache counts, and subagent totals decrease despite increasing headline tokens.

accumulate.py:131 — Migration corrects only positive subagent gaps; independently max-merged historical input/output fields can exceed retained daily subTokens, leaving model totals and percentages inconsistent indefinitely.

tools/publish.sh:55 — An ordinary `.output/` directory passes `rev-parse --is-inside-work-tree` by discovering the parent repository; publishing then runs merge/commit against the code checkout, potentially committing unrelated staged changes.

tools/publish.sh:68 — A dry run leaves modified tracked files in `.output/`; if another machine subsequently updates those files remotely, every scheduled publish fails during fast-forward with local-overwrite errors until manually repaired.

tools/publish.sh:90 — `git add -A .` publishes every stray file in the output worktree; a debug transcript or `.env` placed there is silently committed and pushed publicly on the next refresh.

tools/setup.sh:20 — Checkout paths are interpolated without sed or XML escaping; cloning under a directory containing `&` corrupts the generated plist, and a path containing `|` makes setup fail outright.