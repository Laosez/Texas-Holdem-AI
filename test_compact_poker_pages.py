"""Compact page 1/page 3 contract, archived bots and audit output boundaries."""
import json
import unittest
from pathlib import Path

import replit_simulator as app


ROOT=Path(__file__).resolve().parent


class CompactPokerPagesTests(unittest.TestCase):
    def test_exactly_twelve_visible_postflop_models_and_archived_replay(self):
        catalog=app.strategy_catalog()
        active=catalog["postflop_strategies"]
        archived=catalog["postflop_archived"]
        self.assertEqual(len(active),12)
        self.assertEqual(len(set(active)),12)
        self.assertEqual(len([x for x in archived if x.startswith("gto_postflop_") or x in
                              ("s100_postflop_v1","chaser_postflop_v1","trapper_postflop_v1")]),20)
        self.assertTrue(set(active).isdisjoint(archived))
        for needed in ("gto_postflop_41_5","gto_postflop_531_5",
                       "gto_postflop_54_step15","gto_postflop_541_step15",
                       "random"):
            self.assertIn(needed,active)
        for historic in ("gto_postflop_30_5","gto_postflop_31_5",
                         "gto_postflop_32_5","gto_postflop_40_5",
                         "gto_postflop_50_5","gto_postflop_54_step10",
                         "gto_postflop_54_step20"):
            self.assertIn(historic,archived)
            self.assertTrue(app.available_postflop(historic))
        self.assertEqual(len(app.DEFAULT_BOT_ROWS),9)
        self.assertTrue(all(r["post"] in active for r in app.DEFAULT_BOT_ROWS))
        self.assertTrue(all(r["pre"]=="a17_preflop" for r in app.DEFAULT_BOT_ROWS))

    def test_screen_one_has_compact_controls_and_no_visible_100_hand_trace(self):
        ui=app.UI.read_text(encoding="utf-8")
        self.assertIn('id="modelArchiveInfo"',ui)
        self.assertIn('id="technicalLogPanel"',ui)
        self.assertIn('id="log"',ui)
        self.assertIn('id="gto5ShadowPanel"',ui)
        self.assertNotIn('id="gto30TracePanel"',ui)
        self.assertNotIn('id="gto30TraceDepth"',ui)
        self.assertNotIn('function renderGTO30Trace()',ui)
        self.assertNotIn('id="gto31Matrix"',ui)
        self.assertNotIn('id="gto32Matrix"',ui)
        self.assertNotIn('id="gto40Matrix"',ui)
        self.assertIn('function renderIndependentAuditor(',ui)
        self.assertIn("aggression.by_bot_action",ui)
        self.assertIn('postflopArchivedValues',ui.replace('archivedPostflopValues','postflopArchivedValues'))
        self.assertIn('id="analysisFrame"',ui)

    def test_page_three_keeps_all_classes_but_removes_repeated_columns(self):
        ui=(ROOT/"replit_ui/river_board.html").read_text(encoding="utf-8")
        self.assertIn('colspan="7"',ui)
        self.assertNotIn('colspan="11"',ui)
        self.assertNotIn("<th>Парность</th>",ui)
        self.assertNotIn("<th>Стрит-флеш</th>",ui)
        self.assertIn("2 598 960",ui)
        self.assertIn("36",ui)
        for inp in ("filterP","filterS","filterF","filterSF"):
            self.assertIn('id="'+inp+'"',ui)

if __name__=="__main__":
    unittest.main()
