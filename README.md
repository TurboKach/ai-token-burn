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

## Fidelity: reimplement **and** verify

The Claude engine (`engine.py`) is a clean-room reimplementation of the app's `/stats`
computation — *not* a copy of Anthropic's code. It has been validated **byte-for-byte**
against the app's actual extracted code: every displayed metric matches exactly.

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
python3 collect.py                 # -> data/stats.json  (Claude + Codex)
python3 collect.py --out x.json    # custom path
```

## Roadmap

- [x] Validated Claude engine + Codex aggregator → `stats.json`
- [x] Verify-against-installed-app self-test
- [ ] Static hero SVG (Overview: tiles + token heatmap) for the README, light/dark
- [ ] GitHub Pages dashboard: tabs (Claude ⇄ Codex) + All/30d/7d + Overview/Models + subagent toggle
- [ ] GitHub Action: render hero on push
- [ ] launchd job: daily `collect.py` → commit + push
