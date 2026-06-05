#!/usr/bin/env python3
"""Verify engine.compute_claude() matches the INSTALLED Claude desktop app's real
/stats code, on YOUR machine. We extract the app's actual aggregation function
(`EKr` + helpers) from Claude.app, run it under Node over a frozen snapshot of your
logs, and diff our output field-by-field.

This is the "verify" half of the reimplement-and-verify strategy: if a Claude update
ever changes the algorithm, this fails loudly so the engine can be updated — the graph
never silently drifts.

No Anthropic code is committed: the extracted oracle lives only in a temp dir and is
deleted afterwards (and is .gitignored regardless).

Requires: macOS with Claude.app installed, Node, and npx (for @electron/asar).
Exits 0 on full match of every displayed metric, 1 otherwise.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import engine  # noqa: E402

ASAR = "/Applications/Claude.app/Contents/Resources/app.asar"

SHIM = r"""const fs=require('fs'),path=require('path'),os=require('os'),readline=require('readline');
const eA=path,zA=fs,ov=readline,D={info(){},warn(){},error(){}};
function MC(){const e=process.env.CLAUDE_CONFIG_DIR;return e==="~"||e!=null&&e.startsWith("~/")||e!=null&&e.startsWith("~\\")?eA.join(os.homedir(),e.slice(1)):e??eA.join(os.homedir(),".claude")}
"""
RUNNER = "\nEKr().then(r=>process.stdout.write(JSON.stringify(r))).catch(e=>{console.error(e);process.exit(1)});\n"


def build_oracle(workdir: str) -> str:
    if not os.path.exists(ASAR):
        sys.exit(f"Claude.app not found at {ASAR} — install the desktop app to verify.")
    app = os.path.join(workdir, "app")
    subprocess.run(["npx", "--yes", "@electron/asar", "extract", ASAR, app],
                   check=True, capture_output=True)
    data = open(os.path.join(app, ".vite/build/index.js"), errors="replace").read()
    # The /stats helpers are contiguous: from `const oKr="<synthetic>"` to just before EKr ends.
    try:
        start = data.index('const oKr="<synthetic>"')
        end = data.index("let LV=null,ceA=null")
    except ValueError:
        sys.exit("Could not locate the /stats engine markers in this Claude version — "
                 "the extractor needs updating for this release (a controlled failure, not a crash).")
    slab = data[start:end]
    if "function EKr(" not in slab:
        sys.exit("Could not locate EKr in this Claude version — the engine may need updating.")
    slab = slab.replace("const e=await aKr()", "const e=null", 1)  # force full recompute, ignore cache
    path = os.path.join(workdir, "oracle.js")
    open(path, "w").write(SHIM + slab + RUNNER)
    return path


def main() -> int:
    claude_dir = os.environ.get("CLAUDE_CONFIG_DIR") or os.path.expanduser("~/.claude")
    work = tempfile.mkdtemp(prefix="aitb-verify-")
    try:
        # Freeze the logs so the live-mutating files don't differ between the two reads.
        frozen = os.path.join(work, "frozen")
        os.makedirs(frozen)
        shutil.copytree(os.path.join(claude_dir, "projects"), os.path.join(frozen, "projects"))

        oracle_js = build_oracle(work)
        env = dict(os.environ, CLAUDE_CONFIG_DIR=frozen)
        out = subprocess.run(["node", oracle_js], check=True, capture_output=True, text=True, env=env)
        app_stats = json.loads(out.stdout)
        mine = engine.compute_claude(frozen)

        fails = []

        def eq(name, a, b):
            if a != b:
                fails.append(f"{name}: ours={a!r} app={b!r}")

        ov = mine["overview"]
        eq("sessions", ov["sessions"], app_stats["totalSessions"])
        eq("messages", ov["messages"], app_stats["totalMessages"])
        eq("activeDays", ov["activeDays"], app_stats["activeDays"])
        eq("peakHour", ov["peakHour"], app_stats["peakActivityHour"])
        eq("currentStreak", ov["currentStreak"], app_stats["streaks"]["currentStreak"])
        eq("longestStreak", ov["longestStreak"], app_stats["streaks"]["longestStreak"])
        eq("firstSessionDate", ov["firstSessionDate"], app_stats["firstSessionDate"])
        eq("lastSessionDate", ov["lastSessionDate"], app_stats["lastSessionDate"])
        app_total = sum(v["inputTokens"] + v["outputTokens"] for v in app_stats["modelUsage"].values())
        eq("totalTokens", ov["totalTokens"], app_total)

        ours_mu = {m["model"]: m for m in mine["models"]}
        # Symmetric model set — catch extra/missing models, not just per-model values.
        eq("model set", sorted(ours_mu), sorted(app_stats["modelUsage"]))
        for model, v in app_stats["modelUsage"].items():
            m = ours_mu.get(model, {})
            eq(f"{model}.in", m.get("in"), v["inputTokens"])
            eq(f"{model}.out", m.get("out"), v["outputTokens"])
            eq(f"{model}.cacheRead", m.get("cacheRead"), v["cacheReadInputTokens"])
            eq(f"{model}.cacheCreation", m.get("cacheCreation"), v["cacheCreationInputTokens"])
        app_fav = (max(app_stats["modelUsage"],
                       key=lambda k: app_stats["modelUsage"][k]["inputTokens"] + app_stats["modelUsage"][k]["outputTokens"])
                   if app_stats["modelUsage"] else None)
        eq("favoriteModel", ov["favoriteModel"], app_fav)

        # Daily token heatmap — values AND date coverage (symmetric).
        ours_by_date = {d["date"]: d for d in mine["daily"]}
        for d in app_stats["dailyModelTokens"]:
            eq(f"daily tokens {d['date']}", ours_by_date.get(d["date"], {}).get("byModel"), d["tokensByModel"])
        eq("dailyModelTokens date set",
           sorted(d["date"] for d in mine["daily"] if d["byModel"]),
           sorted(d["date"] for d in app_stats["dailyModelTokens"]))

        # Daily activity (messages/sessions), which the SVG/dashboard also render.
        for da in app_stats["dailyActivity"]:
            row = ours_by_date.get(da["date"], {})
            eq(f"daily messages {da['date']}", row.get("messages"), da["messageCount"])
            eq(f"daily sessions {da['date']}", row.get("sessions"), da["sessionCount"])

        if fails:
            print(f"❌ MISMATCH ({len(fails)}):")
            for f in fails[:30]:
                print("   ", f)
            return 1
        print(f"✅ PERFECT 1:1 MATCH — engine equals installed Claude "
              f"({ov['sessions']} sessions, {ov['totalTokens']/1e6:.1f}M tokens, "
              f"{len(app_stats['modelUsage'])} models, {ov['activeDays']} active days).")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)


if __name__ == "__main__":
    raise SystemExit(main())
