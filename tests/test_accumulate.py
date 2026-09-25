"""Accumulation invariants across log pruning (run: python3 -m unittest discover -s tests -v).

Builds real Claude transcripts / Codex rollouts in a temp dir, runs the engine over
them, "prunes" old logs, and merges the recompute onto the previous snapshot."""
import copy
import json
import os
import shutil
import sys
import tempfile
import unittest
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import accumulate  # noqa: E402
import engine  # noqa: E402

D1, D2, D3, D4 = "2026-01-05", "2026-01-06", "2026-01-07", "2026-01-08"
TODAY = date(2026, 1, 8)
FIELDS = ("in", "out", "cacheRead", "cacheCreation")


def _ts(day: str, hour: int) -> str:
    y, m, d = map(int, day.split("-"))
    return datetime(y, m, d, hour, 15).astimezone().isoformat()  # local wall-clock hour


def _write(path: str, lines: list[dict]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write("\n".join(json.dumps(x) for x in lines) + "\n")


class Logs:
    """Tiny fake ~/.claude + ~/.codex."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="aitb-test-")
        self.claude = os.path.join(self.root, "claude")
        self.codex = os.path.join(self.root, "codex")
        os.makedirs(os.path.join(self.claude, "projects"))
        os.makedirs(os.path.join(self.codex, "sessions"))

    def claude_session(self, name, day, hour, model, i, o, cr=0, cc=0, sub_of=None):
        proj = os.path.join(self.claude, "projects", "proj")
        path = (os.path.join(proj, sub_of, "subagents", f"agent-{name}.jsonl") if sub_of
                else os.path.join(proj, f"{name}.jsonl"))
        ts = _ts(day, hour)
        _write(path, [
            {"type": "user", "timestamp": ts, "message": {"role": "user", "content": "x"}},
            {"type": "assistant", "timestamp": ts, "message": {
                "model": model, "usage": {"input_tokens": i, "output_tokens": o,
                                          "cache_read_input_tokens": cr,
                                          "cache_creation_input_tokens": cc}}},
        ])

    def codex_session(self, name, day, hour, model, i, cached, o):
        path = os.path.join(self.codex, "sessions", day.replace("-", "/"), f"rollout-{name}.jsonl")
        ts = _ts(day, hour)
        _write(path, [
            {"timestamp": ts, "type": "turn_context", "payload": {"model": model}},
            {"timestamp": ts, "type": "event_msg", "payload": {"type": "user_message"}},
            {"timestamp": ts, "type": "event_msg", "payload": {"type": "token_count", "info": {
                "total_token_usage": {"input_tokens": i, "cached_input_tokens": cached,
                                      "output_tokens": o, "total_tokens": i + o}}}},
        ])

    def prune(self, *rel):
        for r in rel:
            p = os.path.join(self.root, r)
            shutil.rmtree(p) if os.path.isdir(p) else os.remove(p)

    def compute(self) -> dict:
        stats = {"generatedAt": "t", "tzOffsetMinutes": 0,
                 "claude": engine.compute_claude(self.claude),
                 "codex": engine.compute_codex(self.codex)}
        return json.loads(json.dumps(stats))  # same str-keyed shape as the file on disk


def _seed_d1_d3(logs: Logs) -> None:
    logs.claude_session("s1", D1, 10, "opus", 100, 50, cr=1000, cc=10)
    logs.claude_session("a1", D1, 10, "haiku", 20, 5, sub_of="s1")
    logs.claude_session("s2", D2, 10, "opus", 200, 20)
    logs.claude_session("s3", D2, 14, "sonnet", 30, 30)
    logs.claude_session("s4", D3, 9, "sonnet", 10, 5)
    logs.claude_session("a2", D3, 9, "haiku", 7, 3, sub_of="s4")
    logs.codex_session("c1", D1, 10, "gpt-5", 1000, 400, 100)
    logs.codex_session("c2", D2, 11, "gpt-5", 500, 100, 50)


def _prune_d1_add_d4(logs: Logs) -> None:
    logs.prune("claude/projects/proj/s1.jsonl", "claude/projects/proj/s1",
               "codex/sessions/2026/01/05")
    logs.claude_session("s5", D4, 10, "opus", 300, 30, cr=500)  # same hour + model as D1
    logs.claude_session("a3", D4, 10, "haiku", 11, 2, sub_of="s5")
    logs.codex_session("c3", D4, 10, "gpt-5", 800, 200, 80)


class InvariantMixin:
    def assert_invariants(self, stats: dict, no_legacy: bool = False) -> None:
        for tool in ("claude", "codex"):
            t = stats[tool]
            daily = t["daily"]
            # I1
            self.assertEqual(sum(d["tokens"] for d in daily), t["overview"]["totalTokens"], tool)
            # I2
            by_model: dict[str, int] = {}
            for d in daily:
                for m, v in d["byModel"].items():
                    by_model[m] = by_model.get(m, 0) + v
            models = {m["model"]: m for m in t["models"]}
            self.assertLessEqual(set(by_model), set(models), tool)
            for name, m in models.items():
                self.assertEqual(m["in"] + m["out"], m["total"], f"{tool} {name}")
                self.assertEqual(m["total"], by_model.get(name, 0), f"{tool} {name}")
            # I3 (the no-legacy half; monotonicity is checked across runs)
            if no_legacy:
                self.assertEqual(sum(t["hourCounts"].values()), sum(d["sessions"] for d in daily), tool)
            # I4
            if tool == "claude":
                s = t["subagents"]
                self.assertEqual(s["totalTokens"], sum(d["subTokens"] for d in daily))
                self.assertEqual(s["sessions"], sum(d["subSessions"] for d in daily))
                self.assertEqual(s["messages"], sum(d["subMessages"] for d in daily))

    def assert_not_shrunk(self, before: dict, after: dict) -> None:
        for tool in ("claude", "codex"):
            b, a = before[tool], after[tool]
            for h, c in b["hourCounts"].items():
                self.assertGreaterEqual(a["hourCounts"].get(h, 0), c, f"{tool} hour {h}")
            am = {m["model"]: m for m in a["models"]}
            for m in b["models"]:
                for f in FIELDS + ("total",):
                    self.assertGreaterEqual(am[m["model"]][f], m[f], f"{tool} {m['model']}.{f}")
            if "subagents" in b:
                bs, as_ = b["subagents"], a["subagents"]
                for f in ("sessions", "messages", "totalTokens"):
                    self.assertGreaterEqual(as_[f], bs[f], f)
                asm = {m["model"]: m for m in as_["models"]}
                for m in bs["models"]:
                    for f in FIELDS:
                        self.assertGreaterEqual(asm[m["model"]][f], m[f], f"sub {m['model']}.{f}")


class EngineDetailTest(unittest.TestCase):
    def test_daily_detail_reconciles_with_aggregates(self):
        logs = Logs()
        self.addCleanup(shutil.rmtree, logs.root)
        _seed_d1_d3(logs)
        stats = logs.compute()
        for tool in ("claude", "codex"):
            t = stats[tool]
            hours: dict[str, int] = {}
            models: dict[str, dict] = {}
            for d in t["daily"]:
                for m, v in d["byModel"].items():
                    self.assertEqual(d["models"][m]["in"] + d["models"][m]["out"], v, tool)
                self.assertEqual(sum(d["hours"].values()), d["sessions"], tool)
                for h, c in d["hours"].items():
                    hours[h] = hours.get(h, 0) + c
                for m, v in d["models"].items():
                    acc = models.setdefault(m, dict.fromkeys(FIELDS, 0))
                    for f in FIELDS:
                        acc[f] += v[f]
            self.assertEqual(hours, t["hourCounts"], tool)
            self.assertEqual(models, {m["model"]: {f: m[f] for f in FIELDS} for m in t["models"]}, tool)
        sub: dict[str, dict] = {}
        for d in stats["claude"]["daily"]:
            for m, v in d["subModels"].items():
                acc = sub.setdefault(m, dict.fromkeys(FIELDS, 0))
                for f in FIELDS:
                    acc[f] += v[f]
        self.assertEqual(sub, {m["model"]: {f: m[f] for f in FIELDS}
                               for m in stats["claude"]["subagents"]["models"]})


class PruningTest(InvariantMixin, unittest.TestCase):
    def test_pruned_day_keeps_counting_new_usage(self):
        logs = Logs()
        self.addCleanup(shutil.rmtree, logs.root)
        _seed_d1_d3(logs)
        old = logs.compute()                 # published snapshot, D1-D3
        _prune_d1_add_d4(logs)
        fresh = logs.compute()               # live window D2-D4, D1 pruned
        merged = accumulate.merge_stats(old, fresh, TODAY)

        self.assert_invariants(merged, no_legacy=True)
        self.assert_not_shrunk(old, merged)
        c = merged["claude"]
        self.assertEqual(c["hourCounts"]["10"], 3)             # s1 + s2 + s5
        opus = next(m for m in c["models"] if m["model"] == "opus")
        self.assertEqual((opus["in"], opus["out"], opus["cacheRead"]), (600, 100, 1500))
        self.assertEqual(c["subagents"]["sessions"], 3)
        self.assertEqual(c["subagents"]["totalTokens"], 25 + 10 + 13)
        haiku = next(m for m in c["subagents"]["models"] if m["model"] == "haiku")
        self.assertEqual((haiku["in"], haiku["out"]), (38, 10))
        x = merged["codex"]
        self.assertEqual(x["hourCounts"], {"10": 2, "11": 1})
        gpt = next(m for m in x["models"] if m["model"] == "gpt-5")
        self.assertEqual((gpt["in"], gpt["out"], gpt["cacheRead"]), (600 + 400 + 600, 230, 700))

        # next run over the same window: idempotent
        again = accumulate.merge_stats(json.loads(json.dumps(merged)), fresh, TODAY)
        self.assert_invariants(again, no_legacy=True)
        for tool in ("claude", "codex"):
            for k in ("hourCounts", "models", "subagents"):
                self.assertEqual(again[tool].get(k), merged[tool].get(k), f"{tool} {k}")


class PreMigrationTest(InvariantMixin, unittest.TestCase):
    def _old_pre_migration(self, logs: Logs) -> dict:
        """Snapshot as published by the old max-merge code: no per-day detail, drifted aggregates."""
        old = copy.deepcopy(logs.compute())
        for tool in ("claude", "codex"):
            t = old[tool]
            t.pop("legacy", None)
            for d in t["daily"]:
                for k in ("hours", "models", "subModels"):
                    d.pop(k, None)
        c = old["claude"]
        c["hourCounts"] = {"3": 4, "10": 1, "14": 1}          # drifted: Σ != sessions
        opus = next(m for m in c["models"] if m["model"] == "opus")
        opus.update({"in": 250, "out": 60})                   # drifted: in+out != total (370)
        c["subagents"]["totalTokens"] = 20                    # drifted below Σ subTokens (35)
        c["subagents"]["models"] = [{"model": "haiku", "in": 40, "out": 12, "cacheRead": 9,
                                     "cacheCreation": 0, "total": 52, "pct": 100.0}]
        return old

    def test_legacy_computed_once_and_nothing_shrinks(self):
        logs = Logs()
        self.addCleanup(shutil.rmtree, logs.root)
        _seed_d1_d3(logs)
        old = self._old_pre_migration(logs)
        _prune_d1_add_d4(logs)
        fresh = logs.compute()
        run1 = accumulate.merge_stats(old, fresh, TODAY)

        self.assert_invariants(run1)
        self.assert_not_shrunk(old, run1)
        leg = run1["claude"]["legacy"]
        # hours: old - Σ detail (detail rows D2,D3,D4 -> 10:2, 14:1, 9:1)
        self.assertEqual(leg["hourCounts"], {"3": 4})
        # opus: D1 row lacks detail -> L = 150, split 250:60 -> in 120, out 30; cache 1000-500
        self.assertEqual(leg["models"]["opus"], {"in": 120, "out": 30, "cacheRead": 500, "cacheCreation": 10})
        # haiku (D1 subagent usage) -> L = 25, split by old 27:8 -> in 19, out 6
        self.assertEqual(leg["models"]["haiku"], {"in": 19, "out": 6, "cacheRead": 0, "cacheCreation": 0})
        # subagent models: old 40/12/9 - Σ subModels (18/5/0)
        self.assertEqual(leg["subModels"]["haiku"], {"in": 22, "out": 7, "cacheRead": 9, "cacheCreation": 0})
        c = run1["claude"]
        self.assertEqual(c["hourCounts"], {"3": 4, "9": 1, "10": 2, "14": 1})
        self.assertEqual(c["subagents"]["totalTokens"], 48)
        self.assertLessEqual(len(leg["hourCounts"]), 24)

        # run 2: D2 pruned too; legacy carried forward unchanged, nothing shrinks
        logs.prune("claude/projects/proj/s2.jsonl", "claude/projects/proj/s3.jsonl",
                   "codex/sessions/2026/01/06")
        logs.claude_session("s6", D4, 3, "opus", 5, 5)
        run2 = accumulate.merge_stats(json.loads(json.dumps(run1)), logs.compute(), TODAY)
        self.assert_invariants(run2)
        self.assert_not_shrunk(run1, run2)
        for tool in ("claude", "codex"):
            self.assertEqual(run2[tool]["legacy"], run1[tool]["legacy"], tool)
        self.assertEqual(run2["claude"]["hourCounts"]["3"], 5)


if __name__ == "__main__":
    unittest.main()
