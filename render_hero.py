#!/usr/bin/env python3
"""Render the static hero SVG (light + dark) for the README from data/stats.json.

Combined Claude Code + Codex token burn: one headline number, six stat tiles, a
GitHub-contribution-style daily heatmap of combined burn, and a Claude/Codex
split bar (so the two-tool story still shows in a static, JS-free image). The
interactive Claude<->Codex tabs / window toggles live on the Pages dashboard.

Pure static SVG (system fonts only, no <script>, no web fonts) so it embeds in
the profile README via <picture>/<img> and renders identically on GitHub.

Usage:  python3 render_hero.py            # -> assets/overview-{light,dark}.svg
        python3 render_hero.py --stats path/to/stats.json --out-dir assets
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date, timedelta
from html import escape

from themes import DEFAULT_THEME, load_theme, resolve_look

ROOT = os.path.dirname(os.path.abspath(__file__))
GATSBY_TOKENS = 62_000  # ~tokens in The Great Gatsby (mirrors the app's easter egg)


def _utc_label(minutes) -> str:
    """Compact UTC offset for the static peak-hour label, e.g. 'UTC+8' / 'UTC-5:30'.
    The hero is a fixed image, so it can't follow the viewer's timezone like the
    dashboard does — it shows peak hour in the collector's zone, labeled."""
    if minutes is None:
        return ""
    sign = "+" if minutes >= 0 else "-"
    h, m = divmod(abs(int(minutes)), 60)
    return f"UTC{sign}{h}" + (f":{m:02d}" if m else "")


# --------------------------------------------------------------------------- #
# combined data
# --------------------------------------------------------------------------- #
def build_combined(stats: dict, today: date) -> dict:
    """Fold Claude + Codex stats into the single combined view the hero draws."""
    tools = [stats["claude"], stats["codex"]]

    # merged daily token totals (union of dates, summed)
    day_tokens: dict[str, int] = {}
    for t in tools:
        for row in t["daily"]:
            day_tokens[row["date"]] = day_tokens.get(row["date"], 0) + row["tokens"]

    active_dates = sorted(day_tokens)

    # combined hour-of-day histogram -> peak hour (tie -> earlier hour)
    hours: dict[int, int] = {}
    for t in tools:
        for h, c in t["hourCounts"].items():
            hours[int(h)] = hours.get(int(h), 0) + int(c)
    peak_hour = max(hours, key=lambda h: (hours[h], -h)) if hours else None

    # favorite model = single model with the most (in+out) across both tools
    best = None
    for t in tools:
        for m in t["models"]:
            if best is None or m["total"] > best["total"]:
                best = m
    favorite_model = best["model"] if best else None

    cur_streak, longest_streak = _streaks(active_dates, today)

    claude_total = stats["claude"]["overview"]["totalTokens"]
    codex_total = stats["codex"]["overview"]["totalTokens"]
    combined_total = claude_total + codex_total

    # hottest single day (for the heatmap callout)
    hottest_date, hottest_tokens = max(
        day_tokens.items(), key=lambda kv: (kv[1], kv[0])
    ) if day_tokens else (None, 0)

    return {
        "totalTokens": combined_total,
        "sessions": sum(t["overview"]["sessions"] for t in tools),
        "messages": sum(t["overview"]["messages"] for t in tools),
        "activeDays": len(active_dates),
        "currentStreak": cur_streak,
        "longestStreak": longest_streak,
        "peakHour": peak_hour,
        "tzLabel": _utc_label(stats.get("tzOffsetMinutes")),
        "favoriteModel": favorite_model,
        "gatsby": combined_total / GATSBY_TOKENS,
        "dayTokens": day_tokens,
        "hottestDate": hottest_date,
        "hottestTokens": hottest_tokens,
        "split": [
            {"tool": "Claude Code", "tokens": claude_total},
            {"tool": "Codex", "tokens": codex_total},
        ],
        "firstDate": active_dates[0] if active_dates else None,
        "lastDate": active_dates[-1] if active_dates else None,
    }


def _streaks(active_dates: list[str], today: date) -> tuple[int, int]:
    """(current, longest) consecutive-calendar-day runs over the active-day union.

    current = run ending today (0 if no burn today); matches the app's "up to today".
    """
    if not active_dates:
        return 0, 0
    days = sorted(date.fromisoformat(d) for d in active_dates)
    longest = run = 1
    for prev, cur in zip(days, days[1:]):
        run = run + 1 if (cur - prev).days == 1 else 1
        longest = max(longest, run)

    dset = set(days)
    current, d = 0, today
    while d in dset:
        current += 1
        d -= timedelta(days=1)
    return current, longest


# --------------------------------------------------------------------------- #
# formatting
# --------------------------------------------------------------------------- #
def human_tokens(n: int) -> str:
    """255_628_000 -> '255.6M', 9_400 -> '9.4K', 940 -> '940'."""
    n = float(n)
    for div, suffix in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(n) >= div:
            return f"{n / div:.1f}{suffix}"
    return f"{int(n)}"


def human_hour(h) -> str:
    return "—" if h is None else f"{int(h):02d}:00"


def pretty_model(name: str | None) -> str:
    """'claude-opus-4-7' -> 'Opus 4.7'; 'gpt-5.5' -> 'GPT-5.5'; codex variants kept."""
    if not name:
        return "—"
    n = name
    if n.startswith("claude-"):
        n = n[len("claude-") :]
        # opus-4-7 -> Opus 4.7 ; haiku-4-5-20251001 -> Haiku 4.5
        parts = n.split("-")
        fam = parts[0].capitalize()
        nums = [p for p in parts[1:] if p.isdigit()]
        ver = ".".join(nums[:2]) if nums else ""
        return f"{fam} {ver}".strip()
    if n.startswith("gpt-"):
        return "GPT-" + n[len("gpt-") :]
    return n


def short_date(iso: str | None) -> str:
    if not iso:
        return ""
    d = date.fromisoformat(iso)
    return d.strftime("%b %-d")


# --------------------------------------------------------------------------- #
# themes
# --------------------------------------------------------------------------- #
def theme_appearances(theme_id: str = DEFAULT_THEME) -> list[dict]:
    """The light + dark appearance dicts for a theme (themes/<id>.json), each
    tagged with `name` (for the filename) and the resolved `look` tokens. The
    single source of truth is shared with the web CSS via themes.py."""
    theme = load_theme(theme_id)
    look = resolve_look(theme)
    appearances = []
    for name in ("light", "dark"):
        appearance = dict(theme[name])
        appearance["name"] = name
        appearance["look"] = look
        appearances.append(appearance)
    return appearances


# --------------------------------------------------------------------------- #
# heatmap geometry
# --------------------------------------------------------------------------- #
def heatmap_grid(day_tokens: dict[str, int], today: date):
    """Return (first_sunday, n_weeks). Columns are weeks (Sunday-start, GitHub
    layout); rows are day-of-week (row 0 = Sunday). Capped at trailing 53 weeks."""
    dates = sorted(date.fromisoformat(d) for d in day_tokens)
    start, last = dates[0], dates[-1]
    end = max(today, last)
    first_sun = start - timedelta(days=(start.weekday() + 1) % 7)  # Sun on/before start
    n_weeks = (end - first_sun).days // 7 + 1
    if n_weeks > 53:
        anchor = end - timedelta(days=53 * 7 - 1)
        first_sun = anchor - timedelta(days=(anchor.weekday() + 1) % 7)
        n_weeks = (end - first_sun).days // 7 + 1
    return first_sun, n_weeks


def make_bucketer(values):
    """4-level intensity by quartiles of non-zero daily burn (GitHub-style)."""
    nz = sorted(v for v in values if v > 0)
    if not nz:
        return lambda v: 0
    q = [nz[min(len(nz) - 1, int(len(nz) * p))] for p in (0.25, 0.5, 0.75)]

    def level(v: int) -> int:
        if v <= 0:
            return 0
        if v <= q[0]:
            return 1
        if v <= q[1]:
            return 2
        if v <= q[2]:
            return 3
        return 4

    return level


# --------------------------------------------------------------------------- #
# SVG rendering
# --------------------------------------------------------------------------- #
def _txt(x, y, s, size, fill, *, weight=400, anchor="start", spacing=None, opacity=None):
    extra = ""
    if weight != 400:
        extra += f' font-weight="{weight}"'
    if anchor != "start":
        extra += f' text-anchor="{anchor}"'
    if spacing is not None:
        extra += f' letter-spacing="{spacing}"'
    if opacity is not None:
        extra += f' opacity="{opacity}"'
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" fill="{fill}"'
        f"{extra}>{escape(str(s))}</text>"
    )


def render_svg(combined: dict, theme: dict, today: date) -> str:
    t = theme
    look = t.get("look", {})
    FONT = look.get("svgFont") or (
        "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, "
        "'Liberation Sans', sans-serif"
    )

    # look-driven geometry. `rad` scales every corner radius (1 = original card
    # look, 0 = square/monospace); `sw` is the stroke-width attribute, emitted
    # only when thicker than the default 1px so Ember's SVG stays byte-identical;
    # `up` uppercases grid captions when the theme asks for it.
    _rs = look.get("radiusScale", 1)
    _bw = int(str(look.get("borderWidth", "1px")).rstrip("px"))
    rad = lambda base: round(base * _rs)
    sw = "" if _bw == 1 else f' stroke-width="{_bw}"'
    up = (lambda s: s.upper()) if look.get("uppercase") else (lambda s: s)

    # ---- heatmap geometry first; it drives canvas width -------------------- #
    first_sun, n_weeks = heatmap_grid(combined["dayTokens"], today)
    CELL, GAP = 11, 3
    PITCH = CELL + GAP
    hm_w = n_weeks * PITCH - GAP

    P = 30  # outer padding
    DAY_GUTTER = 26  # left labels (Mon/Wed/Fri) for the heatmap
    hm_x = P + DAY_GUTTER
    # right-side panel (split bar + legend) sits beside the heatmap
    PANEL_W = 232
    W = hm_x + hm_w + 28 + PANEL_W + P
    W = max(W, 720)
    H = 392

    parts: list[str] = []
    parts.append(
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
        f'viewBox="0 0 {W} {H}" font-family="{FONT}" role="img" '
        f'aria-label="Token burn — Claude Code + Codex">'
    )
    # card background (square when the theme's radius scale is 0)
    parts.append(
        f'<rect x="0.5" y="0.5" width="{W-1}" height="{H-1}" rx="{rad(14)}" '
        f'fill="{t["bg"]}" stroke="{t["stroke"]}"{sw}/>'
    )

    # ---- header ------------------------------------------------------------ #
    hy = 42
    # flame mark
    parts.append(
        f'<g transform="translate({P},{hy-15})">'
        f'<path d="M9 0 C13 5 7 6 10 12 C16 10 17 3 14 -1 '
        f'C20 3 21 14 12 19 C4 19 1 12 5 6 C6 9 8 8 9 0 Z" '
        f'fill="{t["accent"]}"/></g>'
    )
    parts.append(_txt(P + 26, hy, "TOKEN BURN", 21, t["text"], weight=800, spacing="1.5"))
    parts.append(
        _txt(W - P, hy - 4, "Claude Code + Codex", 13, t["muted"], anchor="end")
    )
    subtitle = "token burn-rate · all-time"
    if combined.get("tzLabel"):
        subtitle += f' · times in {combined["tzLabel"]}'
    parts.append(_txt(W - P, hy + 11, subtitle, 10.5, t["faint"], anchor="end"))
    parts.append(
        f'<line x1="{P}" y1="{hy+22}" x2="{W-P}" y2="{hy+22}" '
        f'stroke="{t["stroke"]}"{sw}/>'
    )

    # ---- hero number + gatsby --------------------------------------------- #
    big = human_tokens(combined["totalTokens"])
    ny = 116
    parts.append(_txt(P, ny, big, 54, t["accent"], weight=800))
    # rough advance for unit placement; fixed-width fonts run ~0.6em/char wider
    big_adv = 33 if look.get("mono") else 30
    big_w = len(big) * big_adv + 6
    parts.append(_txt(P + big_w, ny, up("tokens"), 20, t["muted"], weight=600))
    gatsby = f"≈ {combined['gatsby']:,.0f} × The Great Gatsby  ·  {combined['totalTokens']:,} tokens burned"
    parts.append(_txt(P + 2, ny + 24, gatsby, 12.5, t["muted"]))

    # ---- stat tiles -------------------------------------------------------- #
    tiles = [
        (human_tokens(combined["sessions"]) if combined["sessions"] >= 100000
         else f"{combined['sessions']:,}", "sessions"),
        (f"{combined['messages']:,}", "messages"),
        (f"{combined['activeDays']}", "active days"),
        (f"{combined['currentStreak']} / {combined['longestStreak']}", "streak cur / max"),
        (human_hour(combined["peakHour"]), "peak hour"),
        (pretty_model(combined["favoriteModel"]), "top model"),
    ]
    tile_y = 168
    tile_w = (W - 2 * P) / len(tiles)
    for i, (val, lab) in enumerate(tiles):
        cx = P + i * tile_w
        # value: shrink font if it's a long string (model name)
        vsize = 20 if len(val) <= 9 else (15 if len(val) <= 13 else 13)
        parts.append(_txt(cx, tile_y, val, vsize, t["text"], weight=700))
        parts.append(_txt(cx, tile_y + 16, up(lab), 10.5, t["muted"]))
        if i > 0:
            parts.append(
                f'<line x1="{cx-12:.1f}" y1="{tile_y-16}" x2="{cx-12:.1f}" '
                f'y2="{tile_y+18}" stroke="{t["stroke"]}"{sw} opacity="0.7"/>'
            )

    # ---- heatmap ----------------------------------------------------------- #
    hm_top = 224
    bucket = make_bucketer(combined["dayTokens"].values())
    # month labels: place each month at the first column that actually contains a
    # day of that month (handles mid-week month starts + trailing partial months);
    # drop a leading month only if it crowds the next, and keep a 2-col min gap.
    month_y = hm_top - 6
    first_active = date.fromisoformat(combined["firstDate"])
    last_active = date.fromisoformat(combined["lastDate"])
    months_first_col: dict[tuple[int, int], int] = {}
    for w in range(n_weeks):
        for row in range(7):
            d = first_sun + timedelta(days=w * 7 + row)
            if d < first_active or d > last_active:
                continue
            key = (d.year, d.month)
            if key not in months_first_col:
                months_first_col[key] = w
    placed = []
    entries = sorted(months_first_col.items(), key=lambda kv: kv[1])
    for i, ((yy, mm), w) in enumerate(entries):
        nxt = entries[i + 1][1] if i + 1 < len(entries) else n_weeks
        # drop a leading partial month only when a *next* month exists and would crowd it
        if i == 0 and i + 1 < len(entries) and nxt - w < 2:
            continue
        if placed and w - placed[-1] < 2:  # too close to previous label
            continue
        parts.append(_txt(hm_x + w * PITCH, month_y, up(date(yy, mm, 1).strftime("%b")), 9.5, t["faint"]))
        placed.append(w)
    # day-of-week labels (Mon / Wed / Fri -> rows 1,3,5)
    for row, lab in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        parts.append(
            _txt(P + DAY_GUTTER - 6, hm_top + row * PITCH + CELL - 2, up(lab), 9,
                 t["faint"], anchor="end")
        )
    # cells
    cells = [f'<g shape-rendering="crispEdges">']
    for iso, tok in combined["dayTokens"].items():
        d = date.fromisoformat(iso)
        if d < first_sun:
            continue
        col = (d - first_sun).days // 7
        row = (d.weekday() + 1) % 7  # Sun=0
        x = hm_x + col * PITCH
        y = hm_top + row * PITCH
        lvl = bucket(tok)
        fill = t["empty"] if lvl == 0 else t["ramp"][lvl - 1]
        cells.append(
            f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="{rad(2)}" fill="{fill}"/>'
        )
    # fill the empty cells in the spanned range so the grid reads as a calendar
    spanned = {date.fromisoformat(d) for d in combined["dayTokens"]}
    grid_end = max(today, date.fromisoformat(combined["lastDate"]))
    for w in range(n_weeks):
        for row in range(7):
            d = first_sun + timedelta(days=w * 7 + row)
            if d in spanned or d > grid_end:
                continue
            x = hm_x + w * PITCH
            y = hm_top + row * PITCH
            cells.append(
                f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="{rad(2)}" '
                f'fill="{t["empty"]}"/>'
            )
    cells.append("</g>")
    parts.append("".join(cells))

    # ---- right panel: split bar + hottest day + legend --------------------- #
    px = hm_x + hm_w + 28
    pw = W - P - px
    total = sum(s["tokens"] for s in combined["split"]) or 1
    colors = {"Claude Code": t["claude"], "Codex": t["codex"]}

    # split bar
    parts.append(_txt(px, 222, "CLAUDE vs CODEX", 10, t["faint"], weight=700, spacing="0.6"))
    bar_y, bar_h = 232, 16
    cx = px
    for i, s in enumerate(combined["split"]):
        seg = pw * s["tokens"] / total
        r_left = rad(4) if i == 0 else 0
        r_right = rad(4) if i == len(combined["split"]) - 1 else 0
        parts.append(_rounded_seg(cx, bar_y, seg, bar_h, r_left, r_right, colors[s["tool"]]))
        cx += seg
    # split labels (Claude left, Codex right)
    ly = bar_y + bar_h + 17
    for i, s in enumerate(combined["split"]):
        pct = 100 * s["tokens"] / total
        if i == 0:
            parts.append(
                f'<rect x="{px}" y="{ly-9}" width="9" height="9" rx="{rad(2)}" fill="{colors[s["tool"]]}"/>'
            )
            parts.append(_txt(px + 13, ly,
                              f'{s["tool"]}  {human_tokens(s["tokens"])} · {pct:.0f}%',
                              11, t["text"]))
        else:
            parts.append(
                f'<rect x="{px+pw-9:.1f}" y="{ly-9}" width="9" height="9" rx="{rad(2)}" fill="{colors[s["tool"]]}"/>'
            )
            parts.append(_txt(px + pw - 13, ly,
                              f'{s["tool"]}  {human_tokens(s["tokens"])} · {pct:.0f}%',
                              11, t["text"], anchor="end"))

    # hottest day callout
    if combined["hottestDate"]:
        parts.append(_txt(px, 292, "HOTTEST DAY", 10, t["faint"], weight=700, spacing="0.6"))
        parts.append(
            _txt(px, 311,
                 f'{short_date(combined["hottestDate"])} — {human_tokens(combined["hottestTokens"])} tokens',
                 13, t["text"], weight=600)
        )

    # intensity legend (less -> more)
    leg_y = 342
    parts.append(_txt(px, leg_y, up("Less"), 9.5, t["muted"]))
    lx = px + 28
    for c in [t["empty"]] + t["ramp"]:
        parts.append(
            f'<rect x="{lx}" y="{leg_y-9}" width="{CELL}" height="{CELL}" rx="{rad(2)}" fill="{c}"/>'
        )
        lx += PITCH
    parts.append(_txt(lx + 2, leg_y, up("More"), 9.5, t["muted"]))

    # ---- footer ------------------------------------------------------------ #
    fy = H - 18
    parts.append(
        _txt(P, fy,
             f'{short_date(combined["firstDate"])} {date.fromisoformat(combined["firstDate"]).year}'
             f' → today  ·  {combined["activeDays"]} active days',
             10.5, t["faint"])
    )
    parts.append(
        _txt(W - P, fy, "interactive dashboard → turbokach.github.io/ai-token-burn",
             10.5, t["faint"], anchor="end")
    )

    parts.append("</svg>")
    return "\n".join(parts)


def _rounded_seg(x, y, w, h, r_left, r_right, fill):
    """A bar segment with optional rounded left/right corners (px units)."""
    if w <= 0:
        return ""
    x2 = x + w
    rl = min(r_left, w / 2, h / 2)
    rr = min(r_right, w / 2, h / 2)
    d = (
        f"M{x+rl:.2f},{y} H{x2-rr:.2f} "
        + (f"A{rr:.2f},{rr:.2f} 0 0 1 {x2:.2f},{y+rr:.2f} " if rr else f"L{x2:.2f},{y} ")
        + f"V{y+h-rr:.2f} "
        + (f"A{rr:.2f},{rr:.2f} 0 0 1 {x2-rr:.2f},{y+h:.2f} " if rr else f"L{x2:.2f},{y+h:.2f} ")
        + f"H{x+rl:.2f} "
        + (f"A{rl:.2f},{rl:.2f} 0 0 1 {x:.2f},{y+h-rl:.2f} " if rl else f"L{x:.2f},{y+h:.2f} ")
        + f"V{y+rl:.2f} "
        + (f"A{rl:.2f},{rl:.2f} 0 0 1 {x+rl:.2f},{y:.2f} " if rl else f"L{x:.2f},{y:.2f} ")
        + "Z"
    )
    return f'<path d="{d}" fill="{fill}"/>'


# --------------------------------------------------------------------------- #
# main
# --------------------------------------------------------------------------- #
def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stats", default=os.path.join(ROOT, "data", "stats.json"))
    ap.add_argument("--out-dir", default=os.path.join(ROOT, "assets"))
    ap.add_argument("--theme", default=DEFAULT_THEME, help="theme id in themes/")
    args = ap.parse_args()

    with open(os.path.expanduser(args.stats)) as f:
        stats = json.load(f)

    # "today" = local date of the stats generation, so the heatmap/streak anchor
    # matches when collect ran (mirrors the app's local-TZ behavior).
    gen = stats.get("generatedAt", "")
    today = date.fromisoformat(gen[:10]) if gen[:10] else date.today()

    combined = build_combined(stats, today)
    if not combined["dayTokens"]:
        print("render_hero: no usage data in stats.json — nothing to render")
        return

    out_dir = os.path.expanduser(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    for theme in theme_appearances(args.theme):
        svg = render_svg(combined, theme, today)
        path = os.path.join(out_dir, f"overview-{theme['name']}.svg")
        tmp = path + ".tmp"
        with open(tmp, "w") as f:
            f.write(svg)
        os.replace(tmp, path)
        print(f"wrote {path}  ({len(svg):,} bytes)")

    print(
        f"combined: {human_tokens(combined['totalTokens'])} tokens · "
        f"{combined['sessions']:,} sessions · {combined['activeDays']} active days · "
        f"streak {combined['currentStreak']}/{combined['longestStreak']} · "
        f"hottest {short_date(combined['hottestDate'])} "
        f"{human_tokens(combined['hottestTokens'])}"
    )


if __name__ == "__main__":
    main()
