"""Screen 2: real strategy data, versioning and blocker-safe multiway equity."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import planner_core as core
import planner_equity as eq
import planner_api as api


class PlanTests(unittest.TestCase):
    def test_canonical_169_class_1326_combos(self):
        self.assertEqual(len(core.HANDS),169)
        self.assertEqual(set(core.HANDS),set(core.boxes_v5()))
        self.assertEqual(sum(core.COMBOS.values()),1326)
        self.assertEqual(set(core.boxes_v5().values()),set(range(1,18)))

    def test_jto_j9o_corrected_but_legacy_kept(self):
        v5=core.preset("builtin:a17_v5","6","rfi")
        old=core.preset("builtin:a17_legacy","6","rfi")
        for h in ("JTo","J9o"):
            self.assertEqual(v5["boxes"][h],14)
            self.assertEqual(old["boxes"][h],10)
            self.assertEqual(v5["hands"][h],{"fold":100})
            self.assertEqual(old["hands"][h],{"open":100})

    def test_blank_not_fold_and_boxes_independent(self):
        doc=core.preset("builtin:a17_v5","3","vs_open")
        self.assertFalse(doc["hands"])
        initial=core.boxes_v5()
        doc["boxes"]["AQs"]=7
        self.assertFalse(doc["hands"])
        self.assertNotEqual(doc["boxes"]["AQs"],initial["AQs"])
        self.assertEqual(core.boxes_v5(),initial)

    def test_frequency_validation(self):
        doc=core.preset("builtin:a17_v5","3","rfi")
        doc["hands"]["AKs"]={"open":70,"fold":30}
        self.assertEqual(core.validate_plan(doc)["hands"]["AKs"],{"open":70.0,"fold":30.0})
        doc["hands"]["AKs"]={"open":80,"limp":30}
        with self.assertRaisesRegex(ValueError,"превышает"):
            core.validate_plan(doc)
        doc["hands"]["AKs"]={"fourbet":100}
        with self.assertRaisesRegex(ValueError,"несовместимо"):
            core.validate_plan(doc)

    def test_box_classification_protects_last_member(self):
        doc=core.preset("builtin:a17_v5","3","rfi")
        for h in core.HANDS:
            if doc["boxes"][h]==17:
                doc["boxes"][h]=16
        with self.assertRaisesRegex(ValueError,"Все 17"):
            core.validate_plan(doc)

    def test_gto_heuristic_label_and_range(self):
        doc=core.preset("builtin:gto_heuristic","9","rfi")
        self.assertIn("эвристика",doc["name"])
        self.assertEqual(len(doc["hands"]),169)
        self.assertAlmostEqual(sum(doc["hands"]["AA"].values()),100)
        self.assertEqual(doc["hands"]["AA"]["open"],90)

    def test_versioned_save_preserves_immutable_history(self):
        with tempfile.TemporaryDirectory() as td, patch.object(core,"STORE",Path(td)):
            base=core.preset("builtin:a17_v5","3","rfi")
            original=base["hands"]["AQs"].copy()
            first=core.save_plan(base)
            self.assertEqual(first["version"],1)
            self.assertTrue(first["ref"].startswith("saved:"))
            first["boxes"]["AQs"]=7
            first["hands"]["AQs"]={"open":50,"fold":50}
            second=core.save_plan(first,parent=first["ref"])
            self.assertEqual(second["version"],2)
            self.assertEqual(core.get_saved(second["ref"])["hands"]["AQs"],{"open":50.0,"fold":50.0})
            self.assertEqual(core.get_saved(second["ref"])["boxes"]["AQs"],7)
            self.assertEqual(core.get_saved(first["ref"])["hands"]["AQs"],original)
            self.assertEqual(len(core.list_saved()),1)
            with self.assertRaisesRegex(RuntimeError,"другом окне"):
                core.save_plan(first,parent=first["ref"])

    def test_comparison_exact_weighted_jaccard(self):
        first=core.preset("builtin:a17_v5","3","rfi")
        second=core.preset("builtin:a17_v5","3","rfi")
        self.assertEqual(core.compare_docs(first,second)["overlap_pct"],100)
        second["hands"]={}
        result=core.compare_docs(first,second)
        self.assertEqual(result["overlap_pct"],0)
        self.assertGreater(result["hero_pct"],0)
        self.assertEqual(result["villain_pct"],0)

    def test_score_7_straight_flush_wheel_quads(self):
        def card(rank,suit):return ("23456789TJQKA".index(rank))*4+"cdhs".index(suit)
        royal=[card(r,"s") for r in "TJQKA"]+[card("2","c"),card("3","d")]
        quads=[card("A",s) for s in "cdhs"]+[card("K","d"),card("Q","c"),card("J","c")]
        wheel=[card("A","s"),card("2","d"),card("3","c"),card("4","c"),card("5","h"),card("K","h"),card("Q","d")]
        self.assertEqual(eq.score_seven(royal)[0],8)
        self.assertEqual(eq.score_seven(quads)[0],7)
        self.assertEqual(eq.score_seven(wheel),(4,5))
        self.assertGreater(eq.score_seven(royal),eq.score_seven(quads))

    def test_concrete_combo_counts(self):
        for hand in core.HANDS:
            self.assertEqual(len(eq.HAND_COMBOS[hand]),core.COMBOS[hand])
            for pair in eq.HAND_COMBOS[hand]:
                self.assertEqual(len(set(pair)),2)

    def test_random_anytwo_equity_and_multiway_split(self):
        anytwo=eq.WeightedRange(core.range_weights(core.preset("builtin:any_two")))
        hu=eq.simulate_hand("AA",[anytwo],trials=360,seed=7)
        three=eq.simulate_hand("AA",[anytwo,anytwo],trials=360,seed=7)
        self.assertGreater(hu,75)
        self.assertLess(hu,95)
        self.assertGreater(three,50)
        self.assertLess(three,hu)

    def test_impossible_3_pocket_aces_no_card_collision(self):
        aa=eq.WeightedRange({"AA":1})
        with self.assertRaisesRegex(ValueError,"несовместимы"):
            eq.simulate_hand("AA",[aa,aa],trials=50,seed=1)

    def test_4_way_equity_is_not_heads_up_average(self):
        anytwo=eq.WeightedRange(core.range_weights(core.preset("builtin:any_two")))
        hu=eq.simulate_hand("AKs",[anytwo],trials=350,seed=111)
        multi=eq.simulate_hand("AKs",[anytwo,anytwo,anytwo],trials=350,seed=111)
        self.assertLess(multi,hu)

    def test_five_different_ranges(self):
        people=[
            {"profile":"builtin:any_two","position":"3","scenario":"rfi","players":9,"selector":"active"},
            {"profile":"builtin:a17_v5","position":"9","scenario":"rfi","players":9,"selector":"active"},
            {"profile":"builtin:a17_v5","position":"4","scenario":"rfi","players":9,"selector":"active"},
            {"profile":"builtin:gto_heuristic","position":"5","scenario":"rfi","players":9,"selector":"active"},
            {"profile":"builtin:a17_legacy","position":"6","scenario":"rfi","players":9,"selector":"active"},
        ]
        ranges,prov=eq.build_ranges(people)
        self.assertEqual(len(ranges),5)
        self.assertEqual(len(prov),5)
        result=eq.simulate_hand("AKs",ranges,trials=50,seed=8)
        self.assertTrue(0<=result<=100)

    def test_endpoint_request_rejects_unsupported_scenarios(self):
        req={"model":"selected","trials":100,"opponents":[{
            "profile":"builtin:a17_v5","position":"9","scenario":"vs_open","players":9,
            "selector":"active"}]}
        with self.assertRaisesRegex(ValueError,"пустой диапазон"):
            api.start_equity(req)
        req["opponents"][0]["scenario"]="rfi"
        with self.assertRaises(RuntimeError):
            api.start_equity(req,busy=True)


if __name__ == "__main__":
    unittest.main()
