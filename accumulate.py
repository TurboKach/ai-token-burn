#!/usr/bin/env python3
"""Accumulate usage stats across runs so the burn graph never shrinks.

Claude Code prunes local transcripts (`cleanupPeriodDays`, default 30) and Codex
rotates its rollouts, so engine.compute_*() over the *live* logs only ever covers
a rolling recent window. collect.py recomputes that window each run; this module
merges it with the previously published stats.json so a day we have already
captured is retained even after its raw transcript is deleted.

Merge rule (per tool):
- daily[]: union by date, keeping the row with the larger `tokens`. A past day is
  immutable once it ends, so a partially-pruned recompute is smaller and the
  retained snapshot wins; today's row is still growing, so the fresh row wins.
- overview totals are RE-DERIVED from the merged daily[] (so Σdaily == overview
  stays true, which the SPA and hero both rely on).
- hourCounts / models / subagents hold data not present in daily[] (hour-of-day
  histogram, per-model in/out/cache split), so they are max-merged field by field
  and therefore never decrease.

Consequence: accumulated totals intentionally exceed what the Claude app shows
(the app also only sees the un-pruned window). engine.py stays a faithful 1:1
reimplementation; accumulation is layered on top at publish time only.
"""
from __future__ import annotations

from datetime import date, timedelta


def _streaks(dates: list[str], today: date) -> tuple[int, int]:
    """(current, longest) consecutive-day runs; current ends at `today`."""
    if not dates:
        return 0, 0
    days = sorted(date.fromisoformat(d) for d in dates)
    longest = run = 1
    for prev, cur in zip(days, days[1:]):
        run = run + 1 if (cur - prev).days == 1 else 1
        longest = max(longest, run)
    dset = set(days)
    cur, d = 0, today
    while d in dset:
        cur += 1
        d -= timedelta(days=1)
    return cur, longest


def _max_merge_models(old_models, fresh_models, by_model, grand):
    """Union of models; per-field max keeps the in/out/cache split monotonic. `total`
    comes from the merged daily byModel sums when present (authoritative), else max."""
    om = {m["model"]: m for m in old_models}
    fm = {m["model"]: m for m in fresh_models}
    rows = []
    for name in set(om) | set(fm) | set(by_model):
        o, f = om.get(name, {}), fm.get(name, {})
        total = by_model.get(name)
        if total is None:
            total = max(o.get("total", 0), f.get("total", 0))
        rows.append({
            "model": name,
            "in": max(o.get("in", 0), f.get("in", 0)),
            "out": max(o.get("out", 0), f.get("out", 0)),
            "cacheRead": max(o.get("cacheRead", 0), f.get("cacheRead", 0)),
            "cacheCreation": max(o.get("cacheCreation", 0), f.get("cacheCreation", 0)),
            "total": total,
            "pct": round(100 * total / grand, 1) if grand else 0.0,
        })
    rows.sort(key=lambda m: (-m["total"], m["model"]))
    return rows


def _merge_subagents(old_s, fresh_s):
    if not old_s:
        return fresh_s
    if not fresh_s:
        return old_s
    total = max(old_s["totalTokens"], fresh_s["totalTokens"])
    return {
        "sessions": max(old_s["sessions"], fresh_s["sessions"]),
        "messages": max(old_s["messages"], fresh_s["messages"]),
        "totalTokens": total,
        "models": _max_merge_models(old_s.get("models", []), fresh_s.get("models", []), {}, total),
    }


def _merge_tool(old_t, fresh_t, today: date):
    if not old_t:
        return fresh_t

    # 1. daily union — keep the higher-token row per date
    by_date = {d["date"]: d for d in old_t.get("daily", [])}
    for d in fresh_t["daily"]:
        cur = by_date.get(d["date"])
        if cur is None or d["tokens"] >= cur["tokens"]:
            by_date[d["date"]] = d
    daily = [by_date[k] for k in sorted(by_date)]

    # 2. re-derive overview from the merged daily
    by_model: dict[str, int] = {}
    for d in daily:
        for m, v in d["byModel"].items():
            by_model[m] = by_model.get(m, 0) + v
    total = sum(d["tokens"] for d in daily)
    fav = max(by_model, key=lambda m: (by_model[m], m)) if by_model else None
    cur_streak, long_streak = _streaks([d["date"] for d in daily], today)
    fo, fr = old_t["overview"], fresh_t["overview"]
    firsts = [x for x in (fo.get("firstSessionDate"), fr.get("firstSessionDate")) if x]
    lasts = [x for x in (fo.get("lastSessionDate"), fr.get("lastSessionDate")) if x]

    # 3. hourCounts max-merge -> peak hour (histogram is relative, so max never shrinks)
    hours = {str(h): int(c) for h, c in old_t.get("hourCounts", {}).items()}
    for h, c in fresh_t.get("hourCounts", {}).items():
        hours[str(h)] = max(hours.get(str(h), 0), int(c))
    peak = max(hours, key=lambda h: (hours[h], -int(h))) if hours else None

    merged = {
        "tool": fresh_t["tool"],
        "overview": {
            "sessions": sum(d["sessions"] for d in daily),
            "messages": sum(d["messages"] for d in daily),
            "totalTokens": total,
            "activeDays": len(daily),
            "peakHour": int(peak) if peak is not None else None,
            "favoriteModel": fav,
            "firstSessionDate": min(firsts) if firsts else None,
            "lastSessionDate": max(lasts) if lasts else None,
            "currentStreak": cur_streak,
            "longestStreak": long_streak,
        },
        "models": _max_merge_models(old_t.get("models", []), fresh_t.get("models", []), by_model, total),
        "daily": daily,
        "hourCounts": hours,
    }
    if "subagents" in fresh_t or "subagents" in old_t:
        merged["subagents"] = _merge_subagents(old_t.get("subagents"), fresh_t.get("subagents"))
    return merged


def merge_stats(old: dict | None, fresh: dict, today: date) -> dict:
    """Merge a freshly-computed stats dict with the previously published one.

    `today` anchors the recomputed current-streak (use the machine's local date,
    matching the engine's local-TZ behaviour). Returns `fresh` unchanged when there
    is no prior snapshot."""
    if not old:
        return fresh
    return {
        "generatedAt": fresh["generatedAt"],
        "tzOffsetMinutes": fresh.get("tzOffsetMinutes"),
        "claude": _merge_tool(old.get("claude"), fresh["claude"], today),
        "codex": _merge_tool(old.get("codex"), fresh["codex"], today),
    }
