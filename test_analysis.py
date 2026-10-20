"""Regression tests for dedicated tournament analysis and exact stage aggregation."""
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import replit_simulator as app
from export_preflop_ranges_v4 import TrackedBot


def write(folder, filename, content):
    (folder / filename).write_text(content, encoding="utf-8")


class TournamentAnalysisTests(unittest.TestCase):
    def test_new_workspace_route_is_registered_and_ui_safe(self):
        source = Path(app.__file__).read_text(encoding="utf-8")
        html = app.ANALYSIS_UI.read_text(encoding="utf-8")
        self.assertIn('"/analysis"', source)
        self.assertIn('id="sessionA"', html)
        self.assertIn('id="sessionB"', html)
        self.assertIn('id="stage"', html)
        self.assertIn('id="compareNotice"', html)
        self.assertIn('id="comparePositions"', html)
        self.assertIn('function compatibility(a,b,pa,pb)', html)
        self.assertIn("if(a.strategy_fingerprint!==b.strategy_fingerprint)", html)
        self.assertIn("poolA.slice().sort().join('|')!==poolB.slice().sort().join('|')", html)
        self.assertIn('if(st===', html)
        self.assertIn("function scopeRecord(run,bot){", html)
        self.assertIn("function countTitle(record,metric){", html)
        self.assertIn("run.report.tournaments_completed", html)
        self.assertNotIn("eval(", html)
        realization = app.ROOT.joinpath("replit_ui/index.html").read_text(encoding="utf-8")
        self.assertIn('id="analysisDetails"', realization)
        self.assertIn('id="analysisFrame"', realization)
        self.assertIn("loadAnalysisSession(selected?.id||'')", realization)
        self.assertIn("flop_fold_to_cbet", html)
        self.assertIn("turn_fold_to_cbet", html)
        self.assertIn("river_fold_to_cbet", html)
        self.assertNotIn('<a class="tab" href="/analysis">', realization)

    def test_preflop_stage_and_position_scopes_from_real_counts(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)
            header=("bot,position,hand,combos,hands_observed,"
                    "vpip_n,pfr_n,rfi_n,rfi_opportunities,threebet_n,"
                    "threebet_opportunities,fourbet_n,fourbet_opportunities,"
                    "vpip_pct,pfr_pct,rfi_pct,threebet_pct,fourbet_pct\n")
            # Percentages are read as facts; numerators, not percentages,
            # support future aggregation and sample audits.
            write(path,"summary_all.csv",header +
                  "P1,ALL,*,,50,10,8,5,20,2,10,1,5,20,16,25,20,20\n")
            write(path,"summary_position_all.csv",header +
                  "P1,3,*,,30,9,8,4,12,1,5,1,3,30,26.67,33.33,20,33.33\n")
            write(path,"summary_n3.csv",header +
                  "P1,ALL,*,,30,12,10,6,18,1,4,1,4,40,33.33,33.33,25,25\n")
            write(path,"summary_position_n3.csv",header +
                  "P1,3,*,,10,4,3,2,6,1,4,0,3,40,30,33.33,25,0\n"
                  "P1,SB,*,,20,8,7,4,12,0,0,1,1,40,35,33.33,,100\n")
            stats=app.stats_for_folder(path)["P1"]
            self.assertEqual(stats["hands_observed"],50)
            self.assertEqual(stats["positions"]["3"]["rfi"],33.33)
            self.assertEqual(stats["stages"]["3"]["total"]["hands_observed"],30)
            self.assertEqual(stats["stages"]["3"]["total"]["pre_raw"]["rfi_n"],6)
            self.assertEqual(stats["stages"]["3"]["positions"]["3"]["threebet"],25)
            self.assertIsNone(stats["stages"]["3"]["positions"]["SB"]["threebet"])
            self.assertEqual(stats["stages"]["3"]["positions"]["SB"]["fourbet"],100)

    def test_postflop_stage_total_is_ratio_of_sums_not_average(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)
            write(p,"summary_n3.csv","bot,hands_observed,vpip_pct,pfr_pct,rfi_pct,threebet_pct,fourbet_pct\n"
                  "P1,30,40,20,10,5,1\n")
            write(p,"summary_position_n3.csv","bot,position,hands_observed,vpip_pct,pfr_pct,rfi_pct,threebet_pct,fourbet_pct\n"
                  "P1,3,10,40,20,10,5,1\nP1,SB,20,40,20,10,5,1\n")
            cols=("bot,position,table_size,flop_af,turn_af,river_af,"
                  "flop_cbet,turn_cbet,river_cbet,cbet,net_bb_100,"
                  "flop_aggressive,flop_calls,flop_cbet_n,flop_cbet_opp,"
                  "turn_aggressive,turn_calls,turn_cbet_n,turn_cbet_opp,"
                  "river_aggressive,river_calls,river_cbet_n,river_cbet_opp,"
                  "cbet_n,cbet_opp,net_bb_units,net_hands\n")
            write(p,"postflop_position_stage_summary.csv",cols +
                  "P1,3,3,4,2,1,100,100,50,100,100,8,2,2,2,4,2,1,1,1,1,1,2,2,10,10\n"
                  "P1,SB,3,1,2,1,50,25,0,50,-50,2,2,1,2,2,2,1,4,1,1,0,1,1,2,-10,20\n")
            stats=app.stats_for_folder(p)["P1"]["stages"]["3"]
            total=stats["total"]
            # (2 + 1) / (2 + 2) = 75%, not (100% + 50%) / 2.
            self.assertEqual(total["flop_cbet"],75)
            self.assertAlmostEqual(total["turn_cbet"],40.0)
            self.assertAlmostEqual(total["river_cbet"],100/3,places=4)
            self.assertAlmostEqual(total["flop_af"],2.5)
            self.assertAlmostEqual(total["net_bb_100"],0)
            self.assertEqual(total["post_raw"]["flop_cbet_opp"],4)
            self.assertEqual(stats["positions"]["3"]["flop_cbet"],100)
            self.assertEqual(stats["positions"]["SB"]["net_bb_100"],-50)

    def test_fold_to_cbet_stage_aggregation_is_ratio_of_sums(self):
        with tempfile.TemporaryDirectory() as folder:
            p = Path(folder)
            write(p, "summary_n3.csv", "bot,hands_observed\\nP1,30\\n".replace("\\\\n", "\\n"))
            write(p, "summary_position_n3.csv",
                  "bot,position,hands_observed\\nP1,3,10\\nP1,SB,20\\n".replace("\\\\n", "\\n"))
            cols = ("bot,position,table_size,"
                    "flop_fold_to_cbet_n,flop_fold_to_cbet_opp,"
                    "turn_fold_to_cbet_n,turn_fold_to_cbet_opp,"
                    "river_fold_to_cbet_n,river_fold_to_cbet_opp\\n")
            write(p, "postflop_position_stage_summary.csv", cols +
                  "P1,3,3,1,2,0,1,1,1\\n"
                  "P1,SB,3,2,8,2,3,0,1\\n")
            total = app.stats_for_folder(p)["P1"]["stages"]["3"]["total"]
            self.assertAlmostEqual(total["flop_fold_to_cbet"], 30)
            self.assertAlmostEqual(total["turn_fold_to_cbet"], 50)
            self.assertAlmostEqual(total["river_fold_to_cbet"], 50)
            self.assertEqual(total["post_raw"]["flop_fold_to_cbet_n"], 3)
            self.assertEqual(total["post_raw"]["flop_fold_to_cbet_opp"], 10)

    def test_absent_street_opportunities_are_missing_not_zero(self):
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)
            write(p,"summary_all.csv","bot,hands_observed,vpip_pct,pfr_pct,rfi_pct,threebet_pct,fourbet_pct\n"
                  "P1,40,20,11,,,\n")
            write(p,"postflop_summary.csv","bot,flop_cbet,turn_cbet,river_cbet\n"
                  "P1,45,,\n")
            d=app.stats_for_folder(p)["P1"]
            self.assertEqual(d["flop_cbet"],45)
            self.assertIsNone(d["turn_cbet"])
            self.assertIsNone(d["river_cbet"])
            self.assertNotIn("stages",d)
            self.assertIsNone(d.get("flop_fold_to_cbet"))
            self.assertIsNone(d.get("turn_fold_to_cbet"))
            self.assertIsNone(d.get("river_fold_to_cbet"))

    def test_stage_postflop_observer_preserves_full_and_seat_counters(self):
        bot=TrackedBot(object(),"P1")
        bot.player_id="P1"
        bot.observe_deal(12,[("A","s"),("K","s")],"SB",2)
        view=SimpleNamespace(street="flop",history=[
            {"street":"preflop","pid":"P1","type":"raise"}],me="P1",
            hand_id=12,to_call=0,legal_actions=[{"type":"check"},{"type":"bet"}])
        bot.observe_postflop(view,SimpleNamespace(type="bet"))
        self.assertEqual(bot.postflop_counts["flop_cbet_n"],1)
        self.assertEqual(bot.postflop_position_counts["SB"]["flop_cbet_n"],1)
        self.assertEqual(bot.postflop_stage_counts[("SB",2)]["flop_cbet_n"],1)
        bot.observe_hand_end(12,{"P1":6},2,(),())
        self.assertEqual(bot.postflop_stage_counts[("SB",2)]["net_bb_units"],3)


if __name__=="__main__":
    unittest.main()
