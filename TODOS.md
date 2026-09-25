# TODOS

## P2

- **Oracle extractor broken on current Claude.app** — verify_against_app.py can't find the /stats engine markers; engine is unverified vs the app → docs/todos/oracle-extractor-markers.md
- **[P2 conf:0.5] tools/publish.sh:114** — concurrent publishers (two machines, or manual + 10:00 run) race; a rejected push leaves .output diverged → docs/reviews/stats-isolation/round2.md
- **[P2 conf:0.4] collect.py:58** — a corrupted local data/stats.json silently restarts accumulation from zero (recover via --restore) → docs/reviews/stats-isolation/round2.md
- **[P2 conf:0.4] collect.py:24** — overlapping collect runs share one <path>.tmp with no lock → docs/reviews/stats-isolation/round2.md
- **[P2 conf:0.5] accumulate.py:167** — past-day row replaced by a partial fresh row (tokens-only rule) drops that day's hours/cache/sub detail → docs/reviews/stats-isolation/round2.md
- **[P2 conf:0.5] accumulate.py:82** — one-time migration can absorb same-day new sessions into the frozen hour baseline → docs/reviews/stats-isolation/round2.md
- **[P2 conf:0.4] accumulate.py:130** — negative subagent gap at migration stays uncorrected (not present in owner data) → docs/reviews/stats-isolation/round2.md
- **[P2 conf:0.5] accumulate.py:184** — legacy residual double-counts if a pruned day's transcripts ever reappear → docs/reviews/stats-isolation/round2.md
- **[P2 conf:0.5] tools/setup.sh:20** — sed substitution of the checkout path is unescaped (& or | in path breaks the plist) → docs/reviews/stats-isolation/round2.md
- **stats-isolation close-out** — non-codex leftovers of the output-branch arc (failed push never retried) → docs/todos/stats-isolation-close-out.md
