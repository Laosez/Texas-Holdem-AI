"""Automatic 200 MB limit for recomputable Plan Equity / Postflop EV cache."""
import os
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import planner_api as api


class PlanCacheRetentionTests(unittest.TestCase):
    def test_removes_oldest_completed_results_and_preserves_latest(self):
        with tempfile.TemporaryDirectory() as td, \
             patch.object(api, "CACHE_PATH", Path(td)), \
             patch.object(api, "CACHE_MAX_BYTES", 200):
            items = [Path(td) / (f"{i:064x}.json") for i in (1, 2, 3)]
            for i, (file, size) in enumerate(zip(items, (90, 80, 60))):
                file.write_bytes(b"x" * size)
                os.utime(file, (100 + i, 100 + i))
            report = api.enforce_cache_limit()
            self.assertEqual(report["before_bytes"], 230)
            self.assertEqual(report["after_bytes"], 140)
            self.assertEqual(report["removed_files"], 1)
            self.assertFalse(items[0].exists())
            self.assertTrue(items[1].exists())
            self.assertTrue(items[2].exists())

    def test_recently_published_result_is_protected(self):
        with tempfile.TemporaryDirectory() as td, \
             patch.object(api, "CACHE_PATH", Path(td)), \
             patch.object(api, "CACHE_MAX_BYTES", 180):
            items = [Path(td) / (f"{i:064x}.json") for i in (1, 2, 3)]
            for i, file in enumerate(items):
                file.write_bytes(b"x" * 90)
                os.utime(file, (100 + i, 100 + i))
            report = api.enforce_cache_limit(protected=items[0].name)
            self.assertEqual(report["after_bytes"], 180)
            self.assertTrue(items[0].exists())
            self.assertFalse(items[1].exists())
            self.assertTrue(items[2].exists())

    def test_unrelated_files_and_live_partials_are_never_deleted(self):
        with tempfile.TemporaryDirectory() as td, \
             patch.object(api, "CACHE_PATH", Path(td)), \
             patch.object(api, "CACHE_MAX_BYTES", 50):
            path = Path(td)
            unknown = path / "user_document.json"
            unknown.write_bytes(b"v" * 100)
            live = path / ("a" * 64 + ".bbbbbbbbbbbb.partial")
            live.write_bytes(b"p" * 80)
            old = path / ("c" * 64 + ".dddddddddddd.partial")
            old.write_bytes(b"q" * 80)
            old_ns = time.time_ns() - 7_200_000_000_000
            os.utime(old, ns=(old_ns, old_ns))
            result = api.enforce_cache_limit()
            self.assertEqual(result["removed_files"], 0)
            self.assertTrue(unknown.exists())
            self.assertTrue(live.exists())
            self.assertFalse(old.exists())

    def test_writer_enforces_cap_for_postflop_and_range_results(self):
        with tempfile.TemporaryDirectory() as td, \
             patch.object(api, "CACHE_PATH", Path(td)), \
             patch.object(api, "CACHE_MAX_BYTES", 300):
            first = Path(td) / ("a" * 64 + ".json")
            second = Path(td) / ("range_" + "b" * 64 + ".json")
            payload = {"equity": {"AA": 50}, "note": "x" * 170}
            api._publish_cache_result(first, payload)
            self.assertTrue(first.exists())
            api._publish_cache_result(second, payload)
            self.assertFalse(first.exists())
            self.assertTrue(second.exists())
            self.assertEqual(len(list(Path(td).glob("*.partial"))), 0)
            huge = Path(td) / ("c" * 64 + ".json")
            api._publish_cache_result(huge, {"equity": {"AA": 50}, "large": "X" * 301})
            self.assertFalse(huge.exists())

    def test_completed_in_memory_job_survives_disk_eviction(self):
        with tempfile.TemporaryDirectory() as td, \
             patch.object(api, "CACHE_PATH", Path(td)), \
             patch.object(api, "CACHE_MAX_BYTES", 200), \
             ThreadPoolExecutor(max_workers=1) as pool:
            ids = ("d" * 64, "e" * 64)
            try:
                for key in ids:
                    api._schedule(key, lambda update: {"equity": {"AA": 50},
                                  "note": "x" * 100}, 1, executor=pool)
                    deadline = time.monotonic() + 5
                    while api.get_task(key)["status"] != "completed" and time.monotonic() < deadline:
                        time.sleep(0.01)
                    self.assertEqual(api.get_task(key)["status"], "completed")
                self.assertFalse((Path(td) / (ids[0] + ".json")).exists())
                self.assertTrue((Path(td) / (ids[1] + ".json")).exists())
                self.assertEqual(api.get_task(ids[0])["result"]["equity"]["AA"], 50)
            finally:
                with api.LOCK:
                    for key in ids:
                        api.EQUITY_TASKS.pop(key, None)


if __name__ == "__main__":
    unittest.main()
