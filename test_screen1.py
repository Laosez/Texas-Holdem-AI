"""Screen 1: per-seat strategy validation, session restore and ZIP lifecycle."""
import csv
import io
import json
import tempfile
import unittest
import zipfile
from collections import deque
from pathlib import Path
from unittest.mock import patch

import replit_simulator as app


def archive_with(files):
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as archive:
        for name, data in files.items():
            archive.writestr(name, data)
    return b.getvalue()


class ScreenOneTests(unittest.TestCase):
    def test_complete_a17_bot_and_duplicate_profiles(self):
        rows = [{"pre": "gto", "post": "gto"},
                {"pre": "gto", "post": "gto"},
                {"pre": "a17_preflop", "post": "tag_punisher"}]
        result = app.validate_config({"bots": rows})
        self.assertEqual(len(result["players"]), 3)
        self.assertEqual(result["players"][0], "P1=split:gto:gto")
        self.assertEqual(result["players"][1], "P2=split:gto:gto")
        self.assertEqual(result["players"][2], "P3=split:a17_preflop:tag_punisher")
        self.assertEqual(result["bots"], rows)

    def test_blank_pre_or_post_blocks_submission(self):
        base = [{"pre": "gto", "post": "gto"}, {"pre": "gto", "post": "gto"}]
        for i, which in [(0, "pre"), (1, "post")]:
            bad = [dict(b) for b in base]
            bad[i][which] = ""
            with self.subTest(i=i, which=which), self.assertRaisesRegex(ValueError, "обязательны"):
                app.validate_config({"bots": bad})

    def test_reject_unknown_strategy_and_bad_rows(self):
        base = [{"pre": "gto", "post": "gto"}, {"pre": "gto", "post": "gto"}]
        for bad in ([{}, base[1]], [{"pre": "bad-bot", "post": "gto"}, base[1]]):
            with self.assertRaises(ValueError):
                app.validate_config({"bots": bad})
        for count in (1, 10):
            with self.assertRaises(ValueError):
                app.validate_config({"bots": base * count})

    def test_source_label_preserves_strategy_identity(self):
        import bots
        for label in ("P1=split:gto:gto", "P2=split:gto:gto"):
            profile = label.split("=", 1)[1]
            self.assertIsNotNone(bots.create_bot(profile))

    def test_stats_from_exported_csv(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            (d / "summary_all.csv").write_text(
                "bot,hands_observed,vpip_pct,pfr_pct,rfi_pct,threebet_pct,fourbet_pct\n"
                "P1=split:gto:gto,100,20,10,9,8,7\n", encoding="utf-8"
            )
            (d / "tournament_players.csv").write_text(
                "bot,position,completed\n"
                "P1=split:gto:gto,1,1\nP1=split:gto:gto,4,1\n"
                "P1=split:gto:gto,2,1\nP1=split:gto:gto,9,0\n", encoding="utf-8"
            )
            stats = app.stats_for_folder(d)["P1=split:gto:gto"]
            self.assertEqual(stats["hands_observed"], 100)
            self.assertEqual(stats["top3_pct"], 66.67)
            self.assertEqual(stats["median_position"], 2)
            self.assertEqual(stats["vpip"], 20)

    def test_zip_import_download_delete_roundtrip(self):
        with tempfile.TemporaryDirectory() as td, patch.object(app, "OUT", Path(td)):
            report = {"leaderboard": [{"bot": "P1=split:gto:gto", "wins": 1}],
                      "tournaments_completed": 2, "tournaments_requested": 2}
            config = app.validate_config({"bots": [
                {"pre": "gto", "post": "gto"}, {"pre": "gto", "post": "gto"}]})
            zipped = archive_with({
                "tournament_report.json": json.dumps(report),
                "session_manifest.json": json.dumps({"config": config}),
                "summary_all.csv": "bot,hands_observed,vpip_pct\nP1=split:gto:gto,19,20\n"
            })
            with app.MUTEX:
                old = dict(app.RUNS)
                app.RUNS.clear()
            try:
                imported = app.import_session(zipped)
                self.assertEqual(imported["status"], "imported")
                self.assertEqual(imported["config"]["bots"], config["bots"])
                again = app.zip_results(app.RUNS[imported["id"]])
                self.assertIn("tournament_report.json", zipfile.ZipFile(io.BytesIO(again)).namelist())
                self.assertIn("session_manifest.json", zipfile.ZipFile(io.BytesIO(again)).namelist())
                self.assertEqual(json.loads(zipfile.ZipFile(io.BytesIO(again)).read("tournament_report.json")), report)
                app.delete_session(imported["id"])
                self.assertNotIn(imported["id"], app.RUNS)
                self.assertFalse((Path(td) / imported["id"]).exists())
            finally:
                with app.MUTEX:
                    app.RUNS.clear()
                    app.RUNS.update(old)

    def test_zip_path_traversal_and_missing_report_blocked(self):
        for payload in [
            archive_with({"../outside.txt": "unsafe", "tournament_report.json": "{}"}),
            archive_with({"evil.py": "raise SystemExit", "tournament_report.json": "{}"}),
            archive_with({"summary_all.csv": "bot,hands_observed\n"}),
        ]:
            with self.subTest(payload=len(payload)), self.assertRaises(ValueError):
                app.import_session(payload)

    def test_running_run_not_deletable(self):
        with tempfile.TemporaryDirectory() as td, patch.object(app, "OUT", Path(td)):
            id_ = "running_test"
            app.RUNS[id_] = {"id": id_, "status": "running"}
            try:
                with self.assertRaises(RuntimeError):
                    app.delete_session(id_)
            finally:
                app.RUNS.pop(id_, None)


if __name__ == "__main__":
    unittest.main()
