"""Storage capacity, completed-session compaction and resume safety."""
from __future__ import annotations

import gzip
import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import replit_simulator as app
import export_preflop_ranges_v4 as exporter


class StorageCompactionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        patch_out = patch.object(app, "OUT", self.root)
        patch_runs = patch.object(app, "RUNS", {})
        patch_out.start()
        patch_runs.start()
        self.addCleanup(patch_out.stop)
        self.addCleanup(patch_runs.stop)

    def complete(self, run_id, count=2):
        folder = self.root / run_id
        folder.mkdir()
        report = {
            "tournaments_requested": count,
            "tournaments_completed": count,
            "tournaments_unfinished": 0,
            "leaderboard": [{"wins": count}]
        }
        (folder / "tournament_report.json").write_text(json.dumps(report))
        for name in ("performance.json", "metadata.json", "summary_all.csv",
                     "by_hand_169_all.csv", "by_hand_position_169_all.csv",
                     "tournaments.csv", "tournament_players.csv",
                     "leaderboard.csv", "simulation.log", "job.json"):
            (folder / name).write_text("{}" if name.endswith(".json") else "header\n")
        cp = folder / "_checkpoints"
        cp.mkdir()
        (cp / "config.json").write_text('{"config_key":"audited"}')
        for i in range(1, count + 1):
            with gzip.open(cp / f"{i:06d}.json.gz", "wt") as handle:
                json.dump({"task": i, "result": {"n": i}}, handle)
        app.write_integrity_manifest(folder)
        app.RUNS[run_id] = {"id": run_id, "status": "completed"}
        return folder

    def test_preview_and_compact_preserve_exports_and_integrity(self):
        folder = self.complete("20261019_121212_a1b2c3")
        before = app.storage_compaction_preview()
        self.assertEqual(before["checkpoint_files"], 2)
        self.assertGreater(before["reclaimable_bytes"], 0)
        result = app.compact_historical_sessions()
        self.assertEqual(result["files_removed"], 2)
        self.assertEqual(result["bytes_reclaimed"], before["reclaimable_bytes"])
        self.assertEqual(app.storage_compaction_preview()["checkpoint_files"], 0)
        self.assertTrue((folder / "by_hand_169_all.csv").exists())
        self.assertTrue((folder / "tournament_report.json").exists())
        self.assertTrue((folder / "_checkpoints" / "config.json").exists())
        self.assertTrue(app.audit_session(app.RUNS[folder.name])["ok"])
        self.assertEqual(app.audit_session(app.RUNS[folder.name])["checkpoints"], 0)

    def test_never_compact_failed_or_incomplete_sessions(self):
        folder = self.complete("20261019_141414_d4e5f6")
        app.RUNS[folder.name]["status"] = "failed"
        self.assertEqual(app.storage_compaction_preview()["checkpoint_files"], 0)
        self.assertEqual(app.compact_historical_sessions()["files_removed"], 0)
        self.assertEqual(len(list((folder / "_checkpoints").glob("*.json.gz"))), 2)
        app.RUNS[folder.name]["status"] = "completed"
        report = json.loads((folder / "tournament_report.json").read_text())
        report["tournaments_unfinished"] = 1
        (folder / "tournament_report.json").write_text(json.dumps(report))
        self.assertFalse(app.complete_run_outputs(folder))
        self.assertEqual(app.compact_historical_sessions()["files_removed"], 0)

    def test_running_session_blocks_maintenance(self):
        self.complete("20261019_151515_a1b2c3")
        app.RUNS["20261019_161616_b1b2c3"] = {"id": "20261019_161616_b1b2c3", "status": "running"}
        with self.assertRaisesRegex(RuntimeError, "текущую симуляцию"):
            app.compact_historical_sessions()

    def test_low_disk_stops_before_running_uncheckpointed_tournament(self):
        with patch.object(exporter.shutil, "disk_usage",
                          return_value=SimpleNamespace(free=12 * 1024 * 1024)):
            with patch.object(exporter, "run_one", side_effect=AssertionError("Should not execute")):
                with self.assertRaisesRegex(RuntimeError, "резерв 24 МБ"):
                    exporter.task_checkpoint((1, "fixture"), self.root, "digest")

    def test_storage_interface_and_endpoints_present(self):
        page = app.UI.read_text(encoding="utf-8")
        server = (app.ROOT / "replit_simulator.py").read_text(encoding="utf-8")
        for token in ('id="compactCheckpoints"', "$('compactCheckpoints').onclick",
                      "'/api/storage/compact'", "JSON.stringify({confirm:true})"):
            self.assertIn(token, page)
        for token in ('if path == "/api/storage":', 'if path == "/api/storage/compact":',
                      'if payload.get("confirm") is not True:',
                      'compact_completed_checkpoints(output)'):
            self.assertIn(token, server)


if __name__ == "__main__":
    unittest.main()
