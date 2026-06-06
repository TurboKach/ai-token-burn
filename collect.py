#!/usr/bin/env python3
"""Collect Claude Code + Codex usage into a single stats.json for the profile graph.

Output is aggregates only — token counts, dates, model names, hour buckets. No prompt
text, no file paths, nothing sensitive. Safe to commit to a public repo.
"""
import argparse
import json
import os
from datetime import date, datetime, timezone

import accumulate
import engine

_ROOT = os.path.dirname(os.path.abspath(__file__))
# Default output sits next to this script (repo/data/stats.json), so a launchd job that
# runs `python3 /path/to/collect.py` writes to the repo regardless of its working directory.
_DEFAULT_OUT = os.path.join(_ROOT, "data", "stats.json")
# The GitHub Pages SPA can only fetch files under docs/, so mirror stats.json there too
# (script-relative) — the daily collect keeps the dashboard's data current.
_DOCS_OUT = os.path.join(_ROOT, "docs", "data", "stats.json")


def _atomic_write_json(stats: dict, path: str) -> None:
    """Dump to a temp file in the same dir then os.replace, so an interrupted run never
    leaves a consumer reading a truncated file. allow_nan=False => always valid JSON."""
    out_dir = os.path.dirname(path) or "."
    os.makedirs(out_dir, exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w") as fh:
        json.dump(stats, fh, indent=2, allow_nan=False)
    os.replace(tmp, path)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=_DEFAULT_OUT, help="output path")
    ap.add_argument("--claude-dir", default=None, help="override ~/.claude")
    ap.add_argument("--codex-dir", default=None, help="override ~/.codex")
    ap.add_argument("--fresh", action="store_true",
                    help="ignore the existing snapshot — full recompute, no accumulation")
    args = ap.parse_args()
    args.out = os.path.expanduser(args.out)  # launchd does no shell expansion of a literal ~

    fresh = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        # Minutes east of UTC of the machine that bucketed hourCounts/peakHour
        # into local hours (engine.py uses .astimezone()). The dashboard rotates
        # the hour histogram to the viewer's own timezone using this offset.
        "tzOffsetMinutes": int(datetime.now().astimezone().utcoffset().total_seconds() // 60),
        "claude": engine.compute_claude(args.claude_dir),
        "codex": engine.compute_codex(args.codex_dir),
    }

    # Accumulate onto the previously published snapshot so days already captured
    # survive even after Claude/Codex prune their raw logs. --fresh skips this.
    old = None
    if not args.fresh and os.path.exists(args.out):
        try:
            with open(args.out) as fh:
                old = json.load(fh)
        except (json.JSONDecodeError, OSError):
            old = None  # unreadable snapshot -> just publish the fresh compute
    stats = accumulate.merge_stats(old, fresh, date.today())

    _atomic_write_json(stats, args.out)
    # Mirror into the Pages dir so the dashboard always reads the freshest data. Only when
    # writing the default location (a custom --out, e.g. a test path, shouldn't publish).
    if os.path.abspath(args.out) == os.path.abspath(_DEFAULT_OUT):
        _atomic_write_json(stats, _DOCS_OUT)

    for tool in ("claude", "codex"):
        o = stats[tool]["overview"]
        print(f"{tool:7s} {o['sessions']:>5} sessions  {o['messages']:>7} msgs  "
              f"{o['totalTokens']/1e6:>7.1f}M tokens  {o['activeDays']:>3} active days  "
              f"streak {o['currentStreak']}/{o['longestStreak']}  fav {o['favoriteModel']}")
    combined = stats["claude"]["overview"]["totalTokens"] + stats["codex"]["overview"]["totalTokens"]
    print(f"combined burn: {combined/1e6:.1f}M tokens  ->  {args.out}")


if __name__ == "__main__":
    main()
