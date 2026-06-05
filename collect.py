#!/usr/bin/env python3
"""Collect Claude Code + Codex usage into a single stats.json for the profile graph.

Output is aggregates only — token counts, dates, model names, hour buckets. No prompt
text, no file paths, nothing sensitive. Safe to commit to a public repo.
"""
import argparse
import json
import os
from datetime import datetime, timezone

import engine

# Default output sits next to this script (repo/data/stats.json), so a launchd job that
# runs `python3 /path/to/collect.py` writes to the repo regardless of its working directory.
_DEFAULT_OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stats.json")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=_DEFAULT_OUT, help="output path")
    ap.add_argument("--claude-dir", default=None, help="override ~/.claude")
    ap.add_argument("--codex-dir", default=None, help="override ~/.codex")
    args = ap.parse_args()

    stats = {
        "generatedAt": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "claude": engine.compute_claude(args.claude_dir),
        "codex": engine.compute_codex(args.codex_dir),
    }

    # Atomic write: dump to a temp file in the same dir (allow_nan=False guarantees the
    # output is valid JSON for every consumer), then os.replace so an interrupted run
    # never leaves the profile graph reading a truncated file.
    out_dir = os.path.dirname(args.out) or "."
    os.makedirs(out_dir, exist_ok=True)
    tmp = f"{args.out}.tmp"
    with open(tmp, "w") as fh:
        json.dump(stats, fh, indent=2, allow_nan=False)
    os.replace(tmp, args.out)

    for tool in ("claude", "codex"):
        o = stats[tool]["overview"]
        print(f"{tool:7s} {o['sessions']:>5} sessions  {o['messages']:>7} msgs  "
              f"{o['totalTokens']/1e6:>7.1f}M tokens  {o['activeDays']:>3} active days  "
              f"streak {o['currentStreak']}/{o['longestStreak']}  fav {o['favoriteModel']}")
    combined = stats["claude"]["overview"]["totalTokens"] + stats["codex"]["overview"]["totalTokens"]
    print(f"combined burn: {combined/1e6:.1f}M tokens  ->  {args.out}")


if __name__ == "__main__":
    main()
