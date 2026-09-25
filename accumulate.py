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
- hourCounts / models / subagents are RE-DERIVED from the merged daily[] rows'
  per-day detail (`hours`, `models`, `subModels`) plus a per-tool `legacy` residual,
  so new usage keeps adding up after old transcripts are pruned.
- `legacy` covers what rows published before per-day detail existed can't explain.
  It is computed ONCE, from the first pre-migration snapshot merged (one without a
  `legacy` key), then carried forward unchanged — fixed size, never grows.

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


FIELDS = ("in", "out", "cacheRead", "cacheCreation")


def _sum_detail(daily, key):
    """Σ of rows' per-day `models`/`subModels` detail -> {model: {field: n}}."""
    acc: dict[str, dict] = {}
    for d in daily:
        for m, v in d.get(key, {}).items():
            a = acc.setdefault(m, dict.fromkeys(FIELDS, 0))
            for f in FIELDS:
                a[f] += int(v.get(f, 0))
    return acc


def _sum_hours(daily):
    acc: dict[str, int] = {}
    for d in daily:
        for h, c in d.get("hours", {}).items():
            acc[str(h)] = acc.get(str(h), 0) + int(c)
    return acc


def _model_residual(old_models, detail):
    """Per-field max(0, old − Σdetail) for each model; all-zero entries dropped."""
    out = {}
    for m in old_models:
        det = detail.get(m["model"], {})
        r = {f: max(0, int(m.get(f, 0)) - det.get(f, 0)) for f in FIELDS}
        if any(r.values()):
            out[m["model"]] = r
    return out


def _compute_legacy(old_t, daily):
    """One-time residual for a pre-migration snapshot: whatever its aggregates hold that
    the merged rows' per-day detail can't explain. All-zero entries are omitted."""
    hours = _sum_hours(daily)
    legacy_hours = {}
    for h, c in old_t.get("hourCounts", {}).items():
        r = max(0, int(c) - hours.get(str(h), 0))
        if r:
            legacy_hours[str(h)] = r

    # models: cache fields as a residual; in/out from the byModel tokens of rows that
    # lack detail, split so in+out == Σ byModel exactly and neither field drops below
    # the old snapshot's (closest point to the old in:out ratio; ratio if infeasible).
    detail = _sum_detail(daily, "models")
    legacy_models = _model_residual(old_t.get("models", []), detail)
    for f in ("in", "out"):
        for r in legacy_models.values():
            r[f] = 0
    undetailed: dict[str, int] = {}
    for d in daily:
        if "models" not in d:
            for m, v in d["byModel"].items():
                undetailed[m] = undetailed.get(m, 0) + v
    old_io = {m["model"]: (int(m.get("in", 0)), int(m.get("out", 0))) for m in old_t.get("models", [])}
    for m, total in undetailed.items():
        oi, oo = old_io.get(m, (0, 0))
        leg_in = total * oi // (oi + oo) if oi + oo else 0
        det = detail.get(m, {})
        lo = max(0, oi - det.get("in", 0))
        hi = total - max(0, oo - det.get("out", 0))
        if lo <= hi:
            leg_in = min(max(leg_in, lo), hi)
        r = legacy_models.setdefault(m, dict.fromkeys(FIELDS, 0))
        r["in"], r["out"] = leg_in, total - leg_in
    legacy_models = {m: r for m, r in legacy_models.items() if any(r.values())}

    legacy = {}
    if legacy_hours:
        legacy["hourCounts"] = legacy_hours
    if legacy_models:
        legacy["models"] = legacy_models
    sub_detail = _sum_detail(daily, "subModels")
    sub = _model_residual((old_t.get("subagents") or {}).get("models", []), sub_detail)
    # sub-model totals must add up to Σ subTokens: spread a positive gap over the models
    # in proportion to their totals (each share split by that model's own in:out ratio).
    agg = {m: {f: sub.get(m, {}).get(f, 0) + sub_detail.get(m, {}).get(f, 0) for f in FIELDS}
           for m in set(sub) | set(sub_detail)}
    tot = {m: v["in"] + v["out"] for m, v in agg.items()}
    gap = sum(d.get("subTokens", 0) for d in daily) - sum(tot.values())
    if gap > 0 and sum(tot.values()) > 0:
        shares = {m: gap * t // sum(tot.values()) for m, t in tot.items()}
        shares[max(tot, key=lambda m: (tot[m], m))] += gap - sum(shares.values())
        for m, g in shares.items():
            if not g:
                continue
            a = agg[m]
            g_in = g * a["in"] // (a["in"] + a["out"]) if a["in"] + a["out"] else 0
            r = sub.setdefault(m, dict.fromkeys(FIELDS, 0))
            r["in"] += g_in
            r["out"] += g - g_in
    if sub:
        legacy["subModels"] = sub
    return legacy


def _models_rows(legacy_models, detail, names, grand):
    """Aggregate model rows = legacy + Σ detail; total = in+out."""
    rows = []
    for name in set(legacy_models) | set(detail) | set(names):
        v = {f: legacy_models.get(name, {}).get(f, 0) + detail.get(name, {}).get(f, 0) for f in FIELDS}
        total = v["in"] + v["out"]
        rows.append({"model": name, **v, "total": total,
                     "pct": round(100 * total / grand, 1) if grand else 0.0})
    rows.sort(key=lambda m: (-m["total"], m["model"]))
    return rows


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

    # 3. legacy residual: carried forward, or computed once from a pre-migration snapshot
    legacy = old_t["legacy"] if "legacy" in old_t else _compute_legacy(old_t, daily)

    # 4. hourCounts = legacy + Σ rows' hours -> peak hour
    hours = dict(legacy.get("hourCounts", {}))
    for h, c in _sum_hours(daily).items():
        hours[h] = hours.get(h, 0) + c
    hours = {h: hours[h] for h in sorted(hours, key=int) if hours[h]}
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
        "models": _models_rows(legacy.get("models", {}), _sum_detail(daily, "models"), by_model, total),
        "daily": daily,
        "hourCounts": hours,
    }
    if "subagents" in fresh_t or "subagents" in old_t:
        sub_total = sum(d.get("subTokens", 0) for d in daily)
        merged["subagents"] = {
            "sessions": sum(d.get("subSessions", 0) for d in daily),
            "messages": sum(d.get("subMessages", 0) for d in daily),
            "totalTokens": sub_total,
            "models": _models_rows(legacy.get("subModels", {}), _sum_detail(daily, "subModels"), (), sub_total),
        }
    merged["legacy"] = legacy
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
