"""Unit tests for the Replit simulator boundary; no simulations needed."""
import json
import tempfile
import unittest
from collections import deque
from pathlib import Path
from unittest.mock import patch

import replit_simulator as app


class InputTests(unittest.TestCase):
    def test_reference_control_run(self):
        c = app.validate_config({})
        self.assertEqual(c["players"], app.DEFAULT_PLAYERS)
        self.assertEqual((len(c["players"]), c["tournaments"], c["seed"]), (9, 90, 2042))
        self.assertEqual((c["chips"], c["sb"], c["bb"]), (500, 1, 2))
        self.assertEqual((c["blind_increase_every"], c["seat_mode"], c["parallel"]), (50, "rotate", 1))

    def test_railway_process_count_respects_memory_budget(self):
        with patch.dict(app.os.environ, {"RAILWAY_PROJECT_ID":"test"},clear=False):
            with patch.dict(app.os.environ, {"POKER_MAX_WORKERS":""},clear=False):
                for gib, expected in ((None,1),(1.0,1),(2.25,2),(3.35,3),(4.5,4)):
                    with self.subTest(gib=gib):
                        with patch.object(app,"_container_memory_limit_gb",return_value=gib):
                            self.assertEqual(app.max_safe_workers(),expected)
            with patch.dict(app.os.environ,{"POKER_MAX_WORKERS":"2"},clear=False):
                self.assertEqual(app.max_safe_workers(),2)
            with patch.dict(app.os.environ, {"POKER_MAX_WORKERS":""},clear=False), \
                 patch.object(app,"_container_memory_limit_gb",return_value=1.0):
                with self.assertRaisesRegex(ValueError,"не более 1 процессов"):
                    app.validate_config({"parallel":2})

    def test_a17_tag_and_all_control_bots_known(self):
        self.assertTrue(all(app.valid_bot(x) for x in app.DEFAULT_PLAYERS))
        self.assertTrue(app.valid_bot("a17_tag"))
        self.assertTrue(app.valid_bot("gto_fixed"))

    def test_reject_malformed_and_unknown_players(self):
        for value in ["smart;rm -rf /", "split:gto:evil", "../../bots", "split:a17_tag:gto"]:
            with self.subTest(value=value):
                with self.assertRaises(ValueError):
                    app.validate_config({"players": ["a17_tag", value]})

    def test_reject_duplicate_and_excess_players(self):
        for value in [
            {"players": ["gto", "gto"]},
            {"players": ["gto"]},
            {"players": ["gto"] * 10},
        ]:
            with self.assertRaises(ValueError):
                app.validate_config(value)

    def test_reject_tournaments_outside_limit(self):
        for value in (0, -1, 3001, "one", 1.5, True):
            with self.subTest(value=value), self.assertRaises(ValueError):
                app.validate_config({"tournaments": value})

    def test_reject_bad_blind_and_seat_mode(self):
        for settings in [{"sb": 4, "bb": 2}, {"seat_mode": "sideways"}]:
            with self.assertRaises(ValueError):
                app.validate_config(settings)

    def test_accept_two_bots(self):
        c = app.validate_config({"players": "a17_tag,gto", "parallel": 1})
        self.assertEqual(c["players"], ["a17_tag", "gto"])

    def test_manifest_persists_only_serializable_data(self):
        with tempfile.TemporaryDirectory() as td, patch.object(app, "OUT", Path(td)):
            job = {
                "id": "test_1", "status": "completed", "created": app.now(),
                "updated": app.now(), "config": app.validate_config({}),
                "log": deque(["hello"]), "report": {"tournaments_completed": 1},
                "returncode": 0,
            }
            (Path(td) / job["id"]).mkdir()
            app.persist(job)
            d = json.loads((Path(td) / job["id"] / "job.json").read_text())
            self.assertNotIn("log", d)
            self.assertEqual(d["report"]["tournaments_completed"], 1)


if __name__ == "__main__":
    unittest.main()
