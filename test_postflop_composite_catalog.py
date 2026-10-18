"""Ledger regression: exactly 1,019 real board×HERO composite scenarios.

Static JSON precomputed offline; the live app must never enumerate 2M
suit-equivalence representatives just to display the 03 catalog.
"""
from collections import Counter
from pathlib import Path
import json
import threading
import unittest
import urllib.request
import urllib.error
from http.server import ThreadingHTTPServer
from unittest.mock import patch

from postflop_composite_classifier import classify_composite_flop
from postflop_catalog_metrics import POSITIONS, hand_class, calculate_example_metrics, calculate_goal_metrics, HERO_GOALS, VILLAIN_GOALS, RANGE_KEYS
import replit_simulator as app


CATALOG_PATH = Path(__file__).resolve().parent / "data" / "postflop_composite_catalog.json"


class CompositeCatalogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
        cls.rows = cls.catalog["rows"]

    def test_exact_catalog_is_reachable_deduplicated_and_reconciles(self):
        rows = self.rows
        self.assertEqual(len(rows), 1019)
        self.assertEqual(len({r["id"] for r in rows}), len(rows))
        self.assertEqual(len({r["board_group"] for r in rows}), 46)
        self.assertEqual(len({r["hero_class"] for r in rows}), 82)
        self.assertEqual(sum(r["deals"] for r in rows), 25989600)
        self.assertEqual(self.catalog["physical_deals"],25989600)
        self.assertEqual(self.catalog["board_groups"],46)
        for row in rows:
            with self.subTest(code=row["id"]):
                self.assertTrue(row["deals"] > 0)
                self.assertEqual(row["id"], "F|"+row["board_group"]+"|"+row["hero_class"][2:])
                self.assertTrue(row["board_name"] and row["hero_name"])
                classified=classify_composite_flop(row["hero"],row["board"])
                self.assertEqual(classified["id"],row["id"])
                self.assertEqual(classified["hero_state"]["name"],row["hero_name"])
                h=tuple((int(tok[:-1]),tok[-1]) for tok in row["hero"].split("-"))
                self.assertEqual(row["hole_name"],hand_class(h))
                self.assertTrue(0<=row["hero_improve"]<=1)
                self.assertEqual(set(row["opp_contact"]),{"any",*POSITIONS})
                self.assertTrue(all(x is not None and 0<=x<=1 for x in row["opp_contact"].values()))
                self.assertEqual(set(row["hero_goals"]),set(HERO_GOALS))
                self.assertEqual(set(row["villain_goals"]),set(VILLAIN_GOALS))
                self.assertAlmostEqual(row["hero_goals"]["improve_category"],row["hero_improve"],places=7)
                self.assertEqual(set(row["villain_goals"]["pair_or_draw"]),set(RANGE_KEYS))
                for pos in RANGE_KEYS:
                    self.assertAlmostEqual(row["villain_goals"]["pair_or_draw"][pos],row["opp_contact"][pos],places=7)
                    self.assertAlmostEqual(row["villain_goals"]["no_contact"][pos]+row["villain_goals"]["pair_or_draw"][pos],1,places=7)
                    for goal in VILLAIN_GOALS:
                        prob=row["villain_goals"][goal][pos]
                        self.assertTrue(prob is None or 0<=prob<=1)
                for goal in HERO_GOALS:
                    self.assertTrue(0<=row["hero_goals"][goal]<=1)

    def test_sampled_probabilities_reconcile_with_exact_runout_and_range_engagement(self):
        # Recalculate across all 46 board groups and diverse HERO classes.
        chosen={}
        for row in self.rows:
            chosen.setdefault(row["board_group"],row)
        for row in self.rows[::43]:
            chosen[row["id"]]=row
        self.assertGreaterEqual(len(chosen),46)
        for row in chosen.values():
            with self.subTest(id=row["id"]):
                recomputed=calculate_example_metrics(row["hero"],row["board"])
                self.assertAlmostEqual(row["hero_improve"],recomputed["hero_improve"],places=7)
                for key,expected in recomputed["opponent_contact"].items():
                    self.assertAlmostEqual(row["opp_contact"][key],expected,places=7)

    def test_recomputed_selectable_goals_cover_all_46_board_types(self):
        first_by_board={}
        for row in self.rows:
            first_by_board.setdefault(row["board_group"],row)
        for row in self.rows[::109]:
            first_by_board[row["id"]]=row
        self.assertGreaterEqual(len(first_by_board),46)
        for row in first_by_board.values():
            with self.subTest(id=row["id"]):
                exact=calculate_goal_metrics(row["hero"],row["board"])
                for goal in HERO_GOALS:
                    self.assertAlmostEqual(exact["hero_goals"][goal],row["hero_goals"][goal],places=7)
                for goal in VILLAIN_GOALS:
                    for pos in RANGE_KEYS:
                        expected=exact["villain_goals"][goal][pos]
                        actual=row["villain_goals"][goal][pos]
                        if expected is None: self.assertIsNone(actual)
                        else: self.assertAlmostEqual(expected,actual,places=7)

    def test_sheet_three_catalog_stays_separate_from_action_sampling(self):
        html=(app.ROOT/"replit_ui/s100.html").read_text(encoding="utf-8")
        for marker in ('id="compositeCatalog"','id="catalogRows"',
                       'id="catalogBoardFilter"','id="catalogHeroFilter"',
                       'id="catalogReviewFilter"','id="catalogSearch"',
                       'id="catalogReset"','id="catalogOpponentRange"',
                       'id="catalogHeroGoal"','id="catalogVillainGoal"',
                       'Карманная рука HERO','Название борда',
                       'Цель HERO · к риверу','Оппонент · на флопе',
                       'id="catalogHeroGoal"','id="catalogVillainGoal"',
                       'catalogMarkStorage',
                       'localStorage.setItem','/api/postflop/composite-catalog'):
            self.assertIn(marker,html)
        self.assertIn('id="scenarioLedger"',html)
        # Existing comparison remains limited to 102 example situations, not 1,019.
        self.assertIn("rows:rows.map((r)=>({hole:r[1],board:r[2]}))",html)
        self.assertNotIn("rows:compositeCatalogRows.map",html)

    def test_catalog_endpoint_is_authenticated_and_matches_on_disk(self):
        with patch.object(app,"TOKEN","catalog_1019_key"):
            server=ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            url=f"http://127.0.0.1:{server.server_address[1]}/api/postflop/composite-catalog"
            try:
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(url,timeout=15)
                self.assertEqual(denied.exception.code,401)
                request=urllib.request.Request(url,headers={"X-Runner-Key":"catalog_1019_key"})
                with urllib.request.urlopen(request,timeout=15) as response:
                    data=json.load(response)
                    self.assertEqual(response.status,200)
                    self.assertEqual(len(data["rows"]),1019)
                    self.assertEqual(sum(r["deals"] for r in data["rows"]),25989600)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
