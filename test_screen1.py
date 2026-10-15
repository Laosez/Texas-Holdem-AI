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
        for rows in ([base[0]], base * 5):
            with self.assertRaises(ValueError):
                app.validate_config({"bots": rows})

    def test_preflop_picker_only_accepts_preflop_strategies(self):
        self.assertEqual(app.PREFLOP_CHOICES, {"a17_preflop", "gto"})
        for pre in ("smart", "tag_punisher", "random", "pressure_filler", "gto_fixed"):
            with self.subTest(pre=pre), self.assertRaisesRegex(ValueError, "префлоп"):
                app.validate_config({"bots": [
                    {"pre": pre, "post": "tag_punisher"},
                    {"pre": "gto", "post": "gto"},
                ]})

    def test_postflop_picker_only_accepts_postflop_strategies(self):
        for post in ("a17_preflop", "gto_fixed", "pc_gto_80bb"):
            with self.subTest(post=post), self.assertRaisesRegex(ValueError, "постфлоп"):
                app.validate_config({"bots": [
                    {"pre": "gto", "post": post},
                    {"pre": "a17_preflop", "post": "tag_punisher"},
                ]})

    def test_single_random_option_auto_assigns_distinct_opponents(self):
        config = app.validate_config({"bots": [
            {"pre": "gto", "post": "random"},
            {"pre": "a17_preflop", "post": "tag_punisher"},
            {"pre": "gto", "post": "random"},
            {"pre": "gto", "post": "random_9"},  # restored historical session
        ]})
        self.assertEqual([b["post"] for b in config["bots"]],
                         ["random", "tag_punisher", "random_2", "random_3"])
        self.assertEqual(config["players"][2], "P3=split:gto:random_2")
        self.assertEqual(config["players"][3], "P4=split:gto:random_3")
        import bots
        for profile in config["players"]:
            self.assertIsNotNone(bots.create_bot(profile.split("=", 1)[1]))

    def test_pc_gto_not_silently_replaced_by_different_bot(self):
        with self.assertRaisesRegex(ValueError, "PC GTO 80bb"):
            app.validate_config({"bots": [
                {"pre": "pc_gto_80bb", "post": "tag_punisher"},
                {"pre": "gto", "post": "gto"},
            ]})

    def test_html_has_street_specific_menus_and_one_random_option(self):
        html = (Path(__file__).resolve().parent / "replit_ui" / "index.html").read_text(encoding="utf-8")
        self.assertIn("const preflopValues=['','a17_preflop','gto','pc_gto_80bb']", html)
        self.assertIn("const postflopValues=", html)
        self.assertIn("row.append(botOptions(b.pre", html)
        self.assertIn("'pre'));", html)
        self.assertIn("'post'));", html)
        self.assertIn("if(v==='pc_gto_80bb'){o.disabled=true", html)
        self.assertNotIn("const values=['','gto'", html)

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
