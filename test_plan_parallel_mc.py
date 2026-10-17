"""Parallel Plan postflop Monte Carlo preserves per-hand EV and statistics."""
import unittest

import planner_postflop_ev as post


def sample():
    return {
        "model": "selected", "trials": 50, "cycles": 1,
        "hero_postflop": "gto2", "hero_position": "3", "hero_stack_bb": 20,
        "opponents": [{
            "profile": "builtin:any_two", "position": "9", "scenario": "rfi",
            "players": 9, "selector": "active", "entry_mode": "manual",
            "entry_pct": 8, "postflop": "lag"
        }]
    }


class ParallelPlanMCTests(unittest.TestCase):
    def test_parallel_matches_legacy_per_hand_ev_and_equity(self):
        req = sample()
        old = post.calculate(req)
        updates = []
        new = post.calculate_parallel(req, workers=2, chunk_size=7,
                                      progress=lambda done, total: updates.append((done, total)))
        self.assertEqual(len(old["ev_bb"]), 169)
        self.assertEqual(old["equity"], new["equity"])
        self.assertEqual(old["ev_bb"], new["ev_bb"])
        self.assertEqual(old["ev_ci95_bb"], new["ev_ci95_bb"])
        self.assertEqual(old["showdown_pct"], new["showdown_pct"])
        self.assertEqual(old["fold_win_pct"], new["fold_win_pct"])
        self.assertEqual(old["entry_n_samples"], new["entry_n_samples"])
        self.assertEqual(old["entry_counts_pct"], new["entry_counts_pct"])
        self.assertEqual(old["entry_pot_bb"], new["entry_pot_bb"])
        for a, b in zip(old["entry_ev_sd_bb"], new["entry_ev_sd_bb"]):
            if a is None or b is None:
                self.assertEqual(a,b)
            else:
                self.assertAlmostEqual(a,b,places=4)
        self.assertEqual(sum(new["entry_n_samples"]), 169 * 50)
        self.assertEqual(updates[-1], (169,169))
        self.assertEqual([i for i,_ in updates], sorted(i for i,_ in updates))
        self.assertNotIn("_raw_stats",new)

    def test_single_hand_still_generates_decomposition(self):
        req = {**sample(), "hand": "K4s"}
        old = post.calculate(req)
        new = post.calculate_parallel(req, workers=2)
        self.assertEqual(old,new)
        self.assertEqual(new["decomposition"]["samples"], 50)

    def test_background_api_uses_spawned_workers_and_persistent_cache(self):
        import tempfile
        import time
        from pathlib import Path
        from unittest.mock import patch
        import planner_api as api
        import replit_simulator
        request = sample()
        request["opponents"][0]["entry_pct"] = 9.25
        with tempfile.TemporaryDirectory() as td, \
             patch.object(api, "CACHE_PATH", Path(td)), \
             patch.object(replit_simulator, "max_safe_workers", return_value=2):
            job = api.start_postflop_ev(request)
            deadline = time.monotonic() + 30
            while job["status"] in ("queued", "running") and time.monotonic() < deadline:
                time.sleep(.1)
                job = api.get_task(job["id"])
            self.assertEqual(job["status"], "completed", job.get("error"))
            self.assertEqual(len(job["result"]["ev_bb"]),169)
            self.assertEqual(sum(job["result"]["entry_n_samples"]),8450)
            cached = api.start_postflop_ev(request)
            self.assertTrue(cached["cached"])
            self.assertEqual(job["result"], cached["result"])

    def test_deep_selected_hand_parallel_is_bitwise_equivalent(self):
        request={**sample(),"hand":"K4s","trials":2500}
        request["opponents"][0]["entry_pct"]=65
        baseline=post.calculate(request)
        increments=[]
        multi=post.calculate_parallel(
            request, workers=3, progress=lambda done,total:increments.append((done,total)))
        self.assertEqual(baseline, multi)
        self.assertEqual(multi["decomposition"]["samples"],2500)
        self.assertEqual(increments[-1],(2500,2500))
        self.assertEqual([n for n,_ in increments],sorted(n for n,_ in increments))

    def test_single_hand_equity_only_parallel(self):
        request={**sample(),"hand":"AA","trials":2500,
                 "hero_postflop":"none"}
        request["opponents"][0]["postflop"]="none"
        a=post.calculate(request)
        b=post.calculate_parallel(request,workers=2)
        self.assertEqual(a,b)
        self.assertIsNone(b["ev_bb"]["AA"])

    def test_background_cpu_budgets_never_overallocate(self):
        import planner_api as api
        self.assertEqual(api.postflop_cpu_budgets(8),(5,3))
        self.assertEqual(api.postflop_cpu_budgets(4),(2,2))
        self.assertEqual(api.postflop_cpu_budgets(2),(1,1))
        self.assertEqual(api.postflop_cpu_budgets(1),(1,1))

    def test_invalid_parallel_worker_count(self):
        with self.assertRaisesRegex(ValueError,"1–8"):
            post.calculate_parallel(sample(),workers=9)


if __name__ == "__main__":
    unittest.main()
