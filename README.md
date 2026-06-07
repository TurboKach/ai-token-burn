# ai-token-burn

A token **burn-rate graph** for your GitHub profile — like the contribution calendar,
but for your **Claude Code** and **Codex** usage. It mirrors the stats the Claude
desktop app shows in its "What's up next" panel (sessions, messages, total tokens,
active days, streaks, peak hour, favorite model, per-model in/out, and the daily token
heatmap) and extends them to Codex.

> **Why local?** Your real usage lives only in local logs. Claude Code (Max/Pro) and
> Codex (ChatGPT) bill via subscription, and the Anthropic/OpenAI *usage APIs* only
> report API-key-billed usage — so a cloud job would render a graph of ~zero. The data
> has to originate from your machine.

## What it reads

| Tool | Source |
|------|--------|
| Claude Code | `~/.claude/projects/**/*.jsonl` (incl. `subagents/agent-*.jsonl`) |
| Codex | `~/.codex/sessions/**/rollout-*.jsonl` |

Output (`data/stats.json`) is **aggregates only** — counts, tokens, dates, model names,
hour buckets. No prompt text, no file paths. Safe to publish.

## ⚠️ Claude Code silently deletes your history (`cleanupPeriodDays`)

Claude Code **prunes local transcripts** on a rolling window set by `cleanupPeriodDays`,
which **defaults to 30 days** — older `~/.claude/projects/**/*.jsonl` files are deleted on
startup. Since subscription usage exists *nowhere else* (not in any API), anything pruned
before you first run this tool is **gone for good**. Codex rotates its rollouts the same
way. That's why a fresh install shows only the last ~month, however long you've really been
using Claude Code.

Two independent things protect you going forward:

1. **The graph** — `collect.py` **accumulates** (`accumulate.py`): each run merges with the
   previously published `stats.json` (union of days; the higher-token row per day wins), so
   once a day is captured it is never lost, even after its transcript is pruned. Run it at
   least once per retention window — the daily launchd job does — and the dashboard only
   ever grows. Trade-off: accumulated totals can **exceed** what the Claude app shows, since
   the app also only sees the un-pruned window.
2. **The raw transcripts** — if you want the actual conversations kept on disk (to re-read
   or search later), raise the limit in `~/.claude/settings.json`:

   ```json
   { "cleanupPeriodDays": 365 }
   ```

   Disk heads-up: heavy use writes on the order of **~20 MB/day (~7 GB/year)** of Claude
   transcripts, so pick a window that fits your disk rather than an unbounded one.

## Fidelity: reimplement **and** verify

The Claude engine (`engine.py`) is a clean-room reimplementation of the app's `/stats`
computation — *not* a copy of Anthropic's code. It has been validated **byte-for-byte**
against the app's actual extracted code: every displayed metric matches exactly.

(`engine.py` itself stays 1:1 with the app; the *published* `stats.json` then accumulates
across runs — see the retention note above — so the dashboard's all-time totals can exceed
what the app currently displays.)

Rather than depend on the app's minified internals at runtime (the function names change
every release), the installed app is used as a **verification oracle**:

```bash
python3 tools/verify_against_app.py   # extracts the installed app's real EKr, diffs ours
```

If a Claude update ever changes the algorithm, this fails loudly so the engine can be
updated — the graph never silently drifts. (Requires macOS + Claude.app + Node; the
extracted oracle is temp-only and never committed.)

Notable details reproduced: headline **tokens exclude cache** (input+output only); a
session is dated by its first message's local date; subagent transcripts contribute
tokens but not sessions/messages (kept in a separate bucket so the dashboard can toggle
them); line-splitting matches Node's `readline` including **U+2028/U+2029** (which the
app silently drops).

## Usage

```bash
python3 collect.py                 # -> data/stats.json (Claude + Codex), accumulating
python3 collect.py --fresh         # full recompute, ignore the prior snapshot
python3 render_hero.py             # -> assets/overview-{light,dark}.svg
./tools/publish.sh                 # collect -> render -> commit + push (DRY_RUN=1 to preview)
```

A launchd agent (`tools/com.turbokach.aitokenburn.plist`) runs `publish.sh` daily.

## Themes

The dashboard and the README hero share one set of named color themes in
`themes/<id>.json`. Each theme defines a **light + dark** appearance; the web
dashboard switches between them automatically via `prefers-color-scheme`, and the
hero is rendered to both `assets/overview-light.svg` and `assets/overview-dark.svg`.

Built-in themes: **`monospace`** (the active default) and **`ember`**.

To switch theme, regenerate the two outputs that bake it in:

```bash
python3 themes.py --theme ember        # -> docs/themes.css (dashboard CSS variables)
python3 render_hero.py --theme ember   # -> assets/overview-{light,dark}.svg
```

Both renderers read `DEFAULT_THEME` in `themes.py` (currently `monospace`) when no
`--theme` is given — change that constant to make a theme the permanent default so
the daily publish job picks it up without flags.

To add your own theme, drop a `themes/<id>.json` beside `ember.json` with the same
shape — `{id, label, look?, light: {...}, dark: {...}}` — then point the commands
above at your new `<id>`.

## Roadmap

- [x] Validated Claude engine + Codex aggregator → `stats.json`
- [x] Verify-against-installed-app self-test
- [x] Cross-run accumulation so the graph survives log pruning (`accumulate.py`)
- [x] Static hero SVG (combined Claude + Codex: tiles + burn heatmap + split bar), light/dark
- [x] GitHub Pages dashboard: tabs (Claude ⇄ Codex) + All/30d/7d + Overview/Models + subagent toggle
- [x] launchd job: daily `collect.py` → `render_hero.py` → commit + push
- [Live dashboard →](https://turbokach.github.io/ai-token-burn/)
