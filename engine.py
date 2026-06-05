"""
ai-token-burn — usage aggregation engine.

`compute_claude()` is a clean-room reimplementation of the Claude desktop app's
/stats engine ("What's up next" panel), validated byte-for-byte against the app's
actual extracted code (see tools/verify_against_app.py): Sessions, Messages, Active
days, Total tokens, every per-model in/out/cache figure, Peak hour, both streaks,
first/last session date, Favorite model, and the daily token heatmap all match.
(The app's internal `toolCallCount` is FS-order-dependent and not shown in the panel,
so it is intentionally not reproduced.)

Fidelity notes:
  * tokens reported in the headline EXCLUDE cache (input+output only).
  * a "session" is a non-subagent transcript with >=1 non-sidechain user/assistant
    message, dated by its first message's LOCAL date — so this must run on the user's
    machine (same timezone as the app), which is exactly where the launchd job runs.
  * subagent transcripts contribute tokens but never sessions/messages/active-days/
    streaks (kept in a separate bucket so a dashboard can toggle them on).
  * line-splitting for Claude matches Node's readline including U+2028/U+2029 (the app
    silently drops records containing them). Codex has no such app to mirror, so it
    uses standard JSONL splitting.
  * JSON parsing rejects NaN/Infinity exactly like JS `JSON.parse` does.
"""
from __future__ import annotations
import json
import os
import re
from datetime import datetime, timedelta

SYNTHETIC = "<synthetic>"
# Claude only: U+2028/U+2029 must split lines (Node readline does; the app drops such
# records). \r\n|\r|\n are already handled by Python's universal-newline file iteration.
_CLAUDE_EXTRA_SPLIT = re.compile("[\u2028\u2029]")


def _reject_nonfinite(_value):
    """Make json.loads reject NaN/Infinity/-Infinity, matching JS JSON.parse."""
    raise ValueError("non-finite JSON constant")


def _int(value) -> int:
    """Coerce a token field to a non-negative int; anything weird becomes 0.

    Guards against strings/floats/NaN/None/negative junk in malformed logs poisoning the
    totals or crashing `+=`. Real token fields are always ints, so this is a no-op on
    valid data.
    """
    return value if type(value) is int and value >= 0 else 0


def _parse_jsonl(path: str, extra_split: "re.Pattern | None") -> list[dict]:
    """Stream a transcript line-by-line and return its JSON object records.

    Memory is bounded by the longest line, not the file size. Non-object JSON values
    (`[]`, `null`, `"x"`) and NaN/Infinity-bearing lines are skipped, not crashed on.
    """
    out: list[dict] = []
    try:
        fh = open(path, encoding="utf-8", errors="replace", newline="")
    except OSError:
        return out
    with fh:
        for line in fh:  # universal newlines: splits on \n, \r, \r\n
            pieces = extra_split.split(line) if extra_split else (line,)
            for piece in pieces:
                piece = piece.strip()
                if not piece:
                    continue
                try:
                    obj = json.loads(piece, parse_constant=_reject_nonfinite)
                except ValueError:
                    continue
                if isinstance(obj, dict):
                    out.append(obj)
    return out


def _local_date_hour(ts) -> tuple[str, int]:
    """Local YYYY-MM-DD and hour for an ISO timestamp. Raises ValueError on junk."""
    if not isinstance(ts, str):
        raise ValueError("non-string timestamp")
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone()
    return dt.strftime("%Y-%m-%d"), dt.hour


def _claude_transcripts(projects_dir: str) -> list[str]:
    """Mirror of the app's `gKr`: project/*.jsonl + project/<session>/subagents/agent-*.jsonl.

    Sorted for deterministic output; unreadable subtrees are skipped, not fatal.
    """
    files: list[str] = []
    try:
        projects = os.listdir(projects_dir)
    except OSError:
        return files
    for proj in projects:
        pdir = os.path.join(projects_dir, proj)
        if not os.path.isdir(pdir):
            continue
        try:
            names = os.listdir(pdir)
        except OSError:
            continue
        for name in names:
            full = os.path.join(pdir, name)
            if os.path.isfile(full) and name.endswith(".jsonl"):
                files.append(full)
            elif os.path.isdir(full):
                sub = os.path.join(full, "subagents")
                try:
                    subs = os.listdir(sub)
                except OSError:
                    continue
                files += [
                    os.path.join(sub, x) for x in subs
                    if x.endswith(".jsonl") and x.startswith("agent-")
                ]
    return sorted(files)


def _codex_rollouts(sessions_dir: str) -> list[str]:
    out: list[str] = []
    for root, _dirs, files in os.walk(sessions_dir):
        for n in files:
            if n.startswith("rollout-") and n.endswith(".jsonl"):
                out.append(os.path.join(root, n))
    return sorted(out)


def _streaks(active_dates: set[str]) -> dict:
    if not active_dates:
        return {"currentStreak": 0, "longestStreak": 0}
    today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    cur = 0
    d = today
    while d.strftime("%Y-%m-%d") in active_dates:
        cur += 1
        d -= timedelta(days=1)
    arr = sorted(active_dates)
    longest = run = 1
    for i in range(1, len(arr)):
        p = datetime.strptime(arr[i - 1], "%Y-%m-%d")
        q = datetime.strptime(arr[i], "%Y-%m-%d")
        if round((q - p).total_seconds() / 86400) == 1:
            run += 1
        else:
            longest = max(longest, run)
            run = 1
    return {"currentStreak": cur, "longestStreak": max(longest, run)}


def _peak_hour(hour_counts: dict) -> "int | None":
    """Most common hour; ties broken deterministically by the lower hour (the app breaks
    ties by FS-enumeration order, which isn't reproducible — we prefer a stable result)."""
    best, best_count = None, 0
    for h in sorted(hour_counts):
        if hour_counts[h] > best_count:
            best_count, best = hour_counts[h], h
    return best


def _new_model_bucket() -> dict:
    return {"inputTokens": 0, "outputTokens": 0, "cacheReadInputTokens": 0, "cacheCreationInputTokens": 0}


def _models_list(usage: dict) -> list[dict]:
    total = sum(v["inputTokens"] + v["outputTokens"] for v in usage.values()) or 1
    rows = [{
        "model": m, "in": v["inputTokens"], "out": v["outputTokens"],
        "cacheRead": v["cacheReadInputTokens"], "cacheCreation": v["cacheCreationInputTokens"],
        "total": v["inputTokens"] + v["outputTokens"],
        "pct": round(100 * (v["inputTokens"] + v["outputTokens"]) / total, 1),
    } for m, v in usage.items()]
    return sorted(rows, key=lambda r: (-r["total"], r["model"]))  # stable, deterministic


def compute_claude(claude_dir: str | None = None, since_days: int | None = None) -> dict:
    """Aggregate Claude Code usage. `since_days` caps history (None = all on disk)."""
    claude_dir = claude_dir or os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    projects = os.path.join(claude_dir, "projects")
    floor = ((datetime.now().astimezone() - timedelta(days=since_days)).strftime("%Y-%m-%d")
             if since_days is not None else None)
    sub_marker = f"{os.sep}subagents{os.sep}"

    sessions = messages = sub_sessions = sub_messages = 0
    first_ts = last_ts = None
    hour_counts: dict[int, int] = {}
    model_usage: dict[str, dict] = {}        # app-identical (includes subagent tokens)
    model_usage_sub: dict[str, dict] = {}    # subagent-only portion
    daily_act: dict[str, dict] = {}          # date -> {messages, sessions}  (non-subagent → activeDays/streaks)
    daily_sub: dict[str, dict] = {}          # date -> {messages, sessions}  (subagent only)
    daily_model: dict[str, dict] = {}        # date -> {model: in+out}       (app-identical, incl subagent)
    daily_model_sub: dict[str, dict] = {}    # subagent-only

    for path in _claude_transcripts(projects):
        entries = _parse_jsonl(path, _CLAUDE_EXTRA_SPLIT)
        msgs = [e for e in entries if e.get("type") in ("user", "assistant")]
        if not msgs:
            continue
        is_sub = sub_marker in path
        kept = msgs if is_sub else [e for e in msgs if not e.get("isSidechain")]
        if not kept:
            continue
        ts0 = kept[0].get("timestamp")
        try:
            date, hour = _local_date_hour(ts0)
        except (ValueError, TypeError):
            continue
        if floor is not None and date < floor:
            continue

        if is_sub:
            sub_sessions += 1
            sub_messages += len(kept)
            d = daily_sub.setdefault(date, {"messages": 0, "sessions": 0})
            d["messages"] += len(kept)
            d["sessions"] += 1
        else:
            sessions += 1
            messages += len(kept)
            d = daily_act.setdefault(date, {"messages": 0, "sessions": 0})
            d["messages"] += len(kept)
            d["sessions"] += 1
            hour_counts[hour] = hour_counts.get(hour, 0) + 1
            if first_ts is None or ts0 < first_ts:
                first_ts = ts0
            if last_ts is None or ts0 > last_ts:
                last_ts = ts0

        for e in kept:
            if e.get("type") != "assistant":
                continue
            usage = (e.get("message") or {}).get("usage")
            if not isinstance(usage, dict):
                continue
            model = (e.get("message") or {}).get("model") or "unknown"
            if model == SYNTHETIC:
                continue
            i, o = _int(usage.get("input_tokens")), _int(usage.get("output_tokens"))
            cr, cc = _int(usage.get("cache_read_input_tokens")), _int(usage.get("cache_creation_input_tokens"))
            bucket = model_usage.setdefault(model, _new_model_bucket())
            bucket["inputTokens"] += i
            bucket["outputTokens"] += o
            bucket["cacheReadInputTokens"] += cr
            bucket["cacheCreationInputTokens"] += cc
            burn = i + o
            if burn > 0:
                daily_model.setdefault(date, {})
                daily_model[date][model] = daily_model[date].get(model, 0) + burn
            if is_sub:
                sb = model_usage_sub.setdefault(model, _new_model_bucket())
                sb["inputTokens"] += i
                sb["outputTokens"] += o
                sb["cacheReadInputTokens"] += cr
                sb["cacheCreationInputTokens"] += cc
                if burn > 0:
                    daily_model_sub.setdefault(date, {})
                    daily_model_sub[date][model] = daily_model_sub[date].get(model, 0) + burn

    # Active days / streaks count NON-subagent days only (matches the app's `r` set).
    active = set(daily_act)
    models = _models_list(model_usage)
    total_tokens = sum(v["inputTokens"] + v["outputTokens"] for v in model_usage.values())

    all_dates = sorted(set(daily_act) | set(daily_sub) | set(daily_model) | set(daily_model_sub))
    daily_rows = [{
        "date": d,
        "tokens": sum(daily_model.get(d, {}).values()),
        "byModel": daily_model.get(d, {}),
        "messages": daily_act.get(d, {}).get("messages", 0),
        "sessions": daily_act.get(d, {}).get("sessions", 0),
        "subTokens": sum(daily_model_sub.get(d, {}).values()),
        "subMessages": daily_sub.get(d, {}).get("messages", 0),
        "subSessions": daily_sub.get(d, {}).get("sessions", 0),
    } for d in all_dates]

    return {
        "tool": "claude",
        "overview": {
            "sessions": sessions,
            "messages": messages,
            "totalTokens": total_tokens,
            "activeDays": len(active),
            "peakHour": _peak_hour(hour_counts),
            "favoriteModel": models[0]["model"] if models else None,
            "firstSessionDate": first_ts,
            "lastSessionDate": last_ts,
            **_streaks(active),
        },
        "models": models,
        "daily": daily_rows,
        "hourCounts": {str(h): c for h, c in sorted(hour_counts.items())},
        "subagents": {
            "sessions": sub_sessions,
            "messages": sub_messages,
            "totalTokens": sum(v["inputTokens"] + v["outputTokens"] for v in model_usage_sub.values()),
            "models": _models_list(model_usage_sub),
        },
    }


def compute_codex(codex_dir: str | None = None, since_days: int | None = None) -> dict:
    """Aggregate OpenAI Codex CLI usage from ~/.codex/sessions/**/rollout-*.jsonl.

    Codex resends full context each turn, so per-event `last_token_usage` is not a clean
    delta — the authoritative session total is the `token_count` event with the largest
    cumulative `total_tokens` (robust to out-of-order/appended events). Codex's own
    `total_tokens` == input + output (reasoning is reported separately and excluded), so
    to mirror Claude's cache-excluded headline:
        in  = input_tokens - cached_input_tokens   (non-cached input)
        out = output_tokens                         (reasoning excluded, matching total_tokens)
        cacheRead = cached_input_tokens
    Sessions are single-model in practice (verified across all rollouts); tokens are
    attributed to the session's model.
    """
    codex_dir = codex_dir or os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
    sessions_dir = os.path.join(codex_dir, "sessions")
    floor = ((datetime.now().astimezone() - timedelta(days=since_days)).strftime("%Y-%m-%d")
             if since_days is not None else None)

    sessions = messages = 0
    first_ts = last_ts = None
    hour_counts: dict[int, int] = {}
    model_usage: dict[str, dict] = {}
    daily: dict[str, dict] = {}
    daily_model: dict[str, dict] = {}

    for path in _codex_rollouts(sessions_dir):
        entries = _parse_jsonl(path, None)  # standard JSONL — no U+2028/U+2029 splitting
        if not entries:
            continue
        sess_first = model = None
        umsg = amsg = 0
        best_total, best_total_val = None, -1
        for o in entries:
            ts = o.get("timestamp")
            if sess_first is None and isinstance(ts, str):
                sess_first = ts
            payload = o.get("payload") or {}
            etype = o.get("type")
            if etype == "turn_context" and model is None and payload.get("model"):
                model = payload["model"]
            elif etype == "session_meta" and model is None:
                model = payload.get("model") or (payload.get("payload") or {}).get("model")
            elif etype == "event_msg":
                pt = payload.get("type")
                if pt == "user_message":
                    umsg += 1
                elif pt == "agent_message":
                    amsg += 1
                elif pt == "token_count":
                    tot = (payload.get("info") or {}).get("total_token_usage")
                    if isinstance(tot, dict):
                        tv = _int(tot.get("total_tokens"))
                        if tv >= best_total_val:
                            best_total_val, best_total = tv, tot
        if umsg + amsg == 0:  # require >=1 message, matching the Claude session rule
            continue
        try:
            date, hour = _local_date_hour(sess_first)
        except (ValueError, TypeError):
            continue
        if floor is not None and date < floor:
            continue
        model = model or "unknown"

        sessions += 1
        messages += umsg + amsg
        d = daily.setdefault(date, {"messages": 0, "sessions": 0})
        d["sessions"] += 1
        d["messages"] += umsg + amsg
        hour_counts[hour] = hour_counts.get(hour, 0) + 1
        if first_ts is None or sess_first < first_ts:
            first_ts = sess_first
        if last_ts is None or sess_first > last_ts:
            last_ts = sess_first

        if best_total:
            cached = _int(best_total.get("cached_input_tokens"))
            in_nc = max(_int(best_total.get("input_tokens")) - cached, 0)
            out = _int(best_total.get("output_tokens"))
            bucket = model_usage.setdefault(model, _new_model_bucket())
            bucket["inputTokens"] += in_nc
            bucket["outputTokens"] += out
            bucket["cacheReadInputTokens"] += cached
            burn = in_nc + out
            if burn > 0:
                daily_model.setdefault(date, {})
                daily_model[date][model] = daily_model[date].get(model, 0) + burn

    models = _models_list(model_usage)
    all_dates = sorted(set(daily) | set(daily_model))
    daily_rows = [{
        "date": d,
        "tokens": sum(daily_model.get(d, {}).values()),
        "byModel": daily_model.get(d, {}),
        "messages": daily.get(d, {}).get("messages", 0),
        "sessions": daily.get(d, {}).get("sessions", 0),
    } for d in all_dates]

    return {
        "tool": "codex",
        "overview": {
            "sessions": sessions,
            "messages": messages,
            "totalTokens": sum(v["inputTokens"] + v["outputTokens"] for v in model_usage.values()),
            "activeDays": len(daily),
            "peakHour": _peak_hour(hour_counts),
            "favoriteModel": models[0]["model"] if models else None,
            "firstSessionDate": first_ts,
            "lastSessionDate": last_ts,
            **_streaks(set(daily)),
        },
        "models": models,
        "daily": daily_rows,
        "hourCounts": {str(h): c for h, c in sorted(hour_counts.items())},
    }
