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

    def test_universal_bb_vs_open_for_all_builtin_and_inherited_profiles(self):
        profiles=("builtin:a17_v5","builtin:a17_legacy",
                  "builtin:pc_gto_80bb","builtin:gto_heuristic")
        for profile in profiles:
            for players in (2, 6, 9):
                with self.subTest(profile=profile,players=players):
                    chart=core.preset(profile,"BB","vs_open",players,80)
                    alias=core.preset(profile,"BB","vs_sb_open",players,80)
                    self.assertEqual(chart["range_origin"],"bb_generic_pc_btn_proxy_v1")
                    self.assertEqual(chart["hands"],alias["hands"])
                    self.assertEqual(len(chart["hands"]),169)
                    self.assertEqual(chart["hands"]["AA"],
                                     {"fold":0,"call":0,"threebet":100})
                    self.assertEqual(chart["hands"]["72o"],
                                     {"fold":100,"call":0,"threebet":0})
                    self.assertEqual(chart["hands"]["AKs"]["threebet"],75)
                    self.assertTrue(all(abs(sum(row.values())-100)<.001
                                        for row in chart["hands"].values()))
                    self.assertEqual(len(core.validate_plan(chart)["hands"]),169)
                    weights=core.range_weights(chart)
                    share=100*sum(core.COMBOS[h]*weights.get(h,0)
                                  for h in core.HANDS)/1326
                    self.assertAlmostEqual(share,55.7918552,places=5)
        # BB has no RFI and the existing vs-threebet response is unaffected.
        self.assertEqual(core.preset("builtin:a17_v5","BB","rfi",9)["hands"],{})
        self.assertEqual(core.preset("builtin:a17_v5","BB","vs_threebet",9)
                         ["hands"]["AA"],{"call":50,"fourbet":50})

    def test_generic_bb_upgrade_is_not_silently_applied_to_saved_explicit_slots(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(core,"STORE",Path(folder)):
            doc=core.preset("builtin:a17_v5","BB","vs_open",9,80)
            doc["hands"]["99"]={"fold":0,"call":100,"threebet":0}
            saved=core.save_plan(doc)
            restored=core.preset(saved["ref"],"BB","vs_open",9,80)
            self.assertEqual(restored["hands"]["99"],{"fold":0,"call":100,"threebet":0})

    def test_bb_vs_sb_alias_retained_for_old_saved_contexts(self):
        source=core.preset("builtin:a17_v5","BB","vs_sb_open",9,80)
        self.assertEqual(source["range_origin"],"bb_generic_pc_btn_proxy_v1")
        self.assertEqual(source["hands"]["AA"]["threebet"],100)
        generic=core.preset("builtin:a17_v5","BB","vs_open",9,80)
        self.assertEqual(source["hands"],generic["hands"])
        with self.assertRaisesRegex(ValueError,"только на BB"):
            core.preset("builtin:pc_gto_80bb","SB","vs_sb_open",9,80)

    def test_one_saved_strategy_contains_multiple_positions(self):
        with tempfile.TemporaryDirectory() as td, patch.object(core, "STORE", Path(td)):
            utg=core.preset("builtin:a17_v5", "9", "rfi", 9)
            utg["hands"]["AA"]={"fold": 100}
            first=core.save_plan(utg)
            self.assertEqual(first["format"], "SKACHKOV_PLAN_V2")
            self.assertEqual(len(first["contexts"]), 1)
            # A saved ID can now resolve BTN without resetting to its old UTG.
            btn=core.preset(first["ref"], "3", "rfi", 9)
            self.assertEqual(btn["position"], "3")
            self.assertEqual(btn["hands"]["AA"], {"open": 100})
            self.assertFalse(btn["context_saved"])
            btn["hands"]["AA"]={"fold": 25, "open": 75}
            second=core.save_plan(btn, parent=first["ref"])
            self.assertEqual(second["id"], first["id"])
            self.assertEqual(second["version"], 2)
            self.assertEqual(len(second["contexts"]), 2)
            # Saved UTG work survives editing BTN and later switching back.
            utg_restored=core.preset(second["ref"], "9", "rfi", 9)
            self.assertEqual(utg_restored["hands"]["AA"], {"fold": 100.0})
            btn_restored=core.preset(second["ref"], "3", "rfi", 9)
            self.assertEqual(btn_restored["hands"]["AA"],
                             {"fold": 25.0, "open": 75.0})
            self.assertEqual(core.get_saved(first["ref"])["hands"]["AA"],
                             {"fold": 100.0})
            self.assertEqual(core.get_saved(first["ref"])["contexts"].keys(),
                             {core.context_key(9, "9", "rfi")})
            # Equity opponent selection respects the requested position,
            # not just the saved document's last-active metadata.
            rfi_op={"profile": second["ref"], "scenario": "rfi",
                    "players": 9, "selector": "active"}
            a,pa=eq.build_ranges([{**rfi_op, "position": "9"}])
            b,pb=eq.build_ranges([{**rfi_op, "position": "3"}])
            self.assertEqual(pa[0]["position"], "9")
            self.assertEqual(pb[0]["position"], "3")
            self.assertNotEqual(a[0].total, b[0].total)

    def test_old_v1_saved_strategy_migrates_non_destructively(self):
        with tempfile.TemporaryDirectory() as td, patch.object(core, "STORE", Path(td)):
            old=core.preset("builtin:a17_v5", "9", "rfi", 9)
            old["name"]="Legacy single-seat save"
            old["hands"]["AA"]={"fold":100}
            old["id"]="abcdefabcdef"
            old["version"]=1
            old["ref"]="saved:abcdefabcdef@v1"
            old["format"]="SKACHKOV_PLAN_V1"
            old.pop("contexts", None)
            old.pop("base_profile", None)
            location=core._file(old["id"], 1)
            location.parent.mkdir(parents=True)
            location.write_text(json.dumps(old),encoding="utf-8")
            original=location.read_text(encoding="utf-8")
            loaded=core.get_saved(old["ref"])
            self.assertEqual(len(loaded["contexts"]), 1)
            self.assertEqual(loaded["hands"]["AA"], {"fold":100})
            other=core.preset(old["ref"],"4","rfi",9)
            newer=core.save_plan(other,parent=old["ref"])
            self.assertEqual(newer["version"], 2)
            self.assertEqual(len(newer["contexts"]), 2)
            self.assertEqual(location.read_text(encoding="utf-8"), original)

    def test_multi_position_validation_rejects_invalid_or_foreign_hands(self):
        original=core.preset("builtin:a17_v5","9","rfi",9)
        original["contexts"]={"9|3|rfi":{"hands":{"AA":{"open":100}}, "stack_bb":80},
                              "9|BB|vs_open":{"hands":{"AKs":{"call":50,"threebet":50}}, "stack_bb":80}}
        clean=core.validate_plan(original)
        self.assertEqual(len(clean["contexts"]),3)
        original["contexts"]["9|BB|vs_open"]["hands"]["AKs"]={"open":100}
        with self.assertRaisesRegex(ValueError, "несовместимо"):
            core.validate_plan(original)
        original["contexts"]={"9|2|rfi":{"hands":{}, "stack_bb":80}}
        with self.assertRaises(ValueError):
            core.validate_plan(original)

    def test_inline_live_hero_range_for_reverse_opponent_hu(self):
        import planner_equity as eq
        import planner_api as api
        live={"AA":1.0, "AKs":0.25, "72o":0.0}
        request={"model":"selected","trials":50,"cycles":1,
                 "opponents":[{"profile":"inline:hero","position":"9",
                               "scenario":"rfi","players":9,"selector":"active",
                               "weights":live}]}
        validated=api._validate_request(request)
        self.assertEqual(validated["opponents"][0]["weights"],
                         {"AA":1.0,"AKs":0.25})
        ranges,provenance=eq.build_ranges(validated["opponents"])
        self.assertAlmostEqual(ranges[0].total,7.0)
        self.assertEqual(provenance[0]["profile"],"inline:hero")
        self.assertEqual(provenance[0]["weights"]["AKs"],0.25)
        self.assertTrue(0<=eq.simulate_hand("KK",ranges,trials=50,seed=43)<=100)
        k1=api._query_identity(validated)
        request["opponents"][0]["weights"]={"AA":0.75,"AKs":0.25}
        k2=api._query_identity(api._validate_request(request))
        self.assertNotEqual(k1,k2)
        for bad in ({"ZZs":1}, {"AA":-0.1}, {"AA":1.01},
                    {"AA":float("nan")}, {"AA":"1"}, {"AA":True},
                    {"AA":0.0}):
            request["opponents"][0]["weights"]=bad
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                api._validate_request(request)
        request["opponents"][0]["weights"]={"AA":1.0}
        request["model"]="any_two"
        with self.assertRaises(ValueError):
            api._validate_request(request)

    def test_opponent_entry_probability_automatic_uses_1326_and_hero_blockers(self):
        only_aces=eq.WeightedRange({"AA": 1.0})
        self.assertAlmostEqual(only_aces.dealt_frequency(),6/1326)
        hero_aces=eq.HAND_COMBOS["AA"][0]
        hero_kings=eq.HAND_COMBOS["KK"][0]
        self.assertAlmostEqual(only_aces.probability_versus_hero(hero_aces),1/1225)
        self.assertAlmostEqual(only_aces.probability_versus_hero(hero_kings),6/1225)
        half=eq.WeightedRange({"AA":0.5})
        self.assertAlmostEqual(half.dealt_frequency(),3/1326)
        self.assertAlmostEqual(half.probability_versus_hero(hero_aces),0.5/1225)
        full=eq.WeightedRange({h:1 for h in core.HANDS})
        self.assertAlmostEqual(full.dealt_frequency(),1.0)
        self.assertAlmostEqual(full.probability_versus_hero(hero_aces),1.0)

    def test_multi_opponent_marginal_entry_mixture_includes_zero_and_conditional_equity(self):
        ranges=[eq.WeightedRange({"AA":1.0}),eq.WeightedRange({"KK":1.0})]
        specs=[{"entry_mode":"manual","entry_pct":20},
               {"entry_mode":"manual","entry_pct":50}]
        masses,choices=eq.entry_distributions("72o",ranges,specs)
        self.assertEqual(len(choices),12)
        for found,expected in zip(masses,[0.4,0.5,0.1]):
            self.assertAlmostEqual(found,expected)
        value,pot,counts=eq.simulate_hand_variable("72o",ranges,specs,trials=50,seed=42)
        self.assertTrue(0<=value<=100)
        self.assertTrue(0<=pot<=3)
        self.assertAlmostEqual(sum(counts),1.0)
        none=[{"entry_mode":"manual","entry_pct":0},
              {"entry_mode":"manual","entry_pct":0}]
        value,pot,counts=eq.simulate_hand_variable("72o",ranges,none,trials=50,seed=42)
        self.assertIsNone(value);self.assertIsNone(pot)
        self.assertEqual([round(x,8) for x in counts],[1.0,0.0,0.0])
        one=[{"entry_mode":"manual","entry_pct":100},
             {"entry_mode":"manual","entry_pct":0}]
        value,pot,counts=eq.simulate_hand_variable("72o",ranges,one,trials=50,seed=42)
        self.assertIsNotNone(value)
        self.assertEqual([round(x,8) for x in counts],[0.0,1.0,0.0])

    def test_api_entry_chance_validation_and_cache_identity(self):
        opp={"profile":"builtin:any_two","position":"9","scenario":"rfi",
             "players":9,"selector":"active","entry_mode":"manual","entry_pct":25.0}
        req={"model":"selected","trials":50,"opponents":[opp]}
        cleaned=api._validate_request(req)
        self.assertEqual(cleaned["opponents"][0]["entry_pct"],25.0)
        a=api._query_identity(cleaned)
        opp["entry_pct"]=45.0
        b=api._query_identity(api._validate_request(req))
        self.assertNotEqual(a,b)
        opp["entry_mode"]="range"
        c=api._query_identity(api._validate_request(req))
        self.assertNotEqual(b,c)
        for bad in (-1,101,float("nan"),float("inf"),True,"25"):
            opp["entry_pct"]=bad
            with self.subTest(bad=bad),self.assertRaises(ValueError):
                api._validate_request(req)
        opp["entry_pct"]=25
        opp["entry_mode"]="invalid"
        with self.assertRaises(ValueError):
            api._validate_request(req)
        opp.pop("entry_mode")
        legacy=api._validate_request(req)
        self.assertEqual(legacy["opponents"][0]["entry_mode"],"always")

    def test_eight_opponents_zero_and_guaranteed_entry_modes(self):
        eight=[{"profile":"builtin:any_two","position":([*map(str,range(9,2,-1)),"SB"])[i],"scenario":"rfi",
                "players":9,"selector":"active","entry_mode":"never"} for i in range(8)]
        cleaned=api._validate_request({"opponents":eight,"trials":50,"cycles":1})
        self.assertEqual(len(cleaned["opponents"]),8)
        self.assertTrue(all(x["entry_mode"]=="never" for x in cleaned["opponents"]))
        sources,specs=eq.build_ranges(eight)
        self.assertEqual(len(sources),8)
        counts,choices=eq.entry_distributions("AKs",sources,specs)
        self.assertEqual(len(counts),9)
        self.assertAlmostEqual(counts[0],1.0)
        self.assertTrue(all(p==0 for p in counts[1:]))
        equity,pot,counts=eq.simulate_hand_variable("AKs",sources,specs,trials=50)
        self.assertIsNone(equity)
        self.assertIsNone(pot)
        eight[2]["entry_mode"]="always"
        counts,_=eq.entry_distributions("AKs",*eq.build_ranges(eight))
        self.assertAlmostEqual(counts[1],1.0)
        self.assertAlmostEqual(counts[0],0.0)
        eighth=api._validate_request({"opponents":eight,"trials":50,"cycles":1})
        self.assertEqual(eighth["opponents"][2]["entry_mode"],"always")
        with self.assertRaisesRegex(ValueError,"1–8"):
            api._validate_request({"opponents":eight+[eight[0]],"trials":50})
        with self.assertRaises(ValueError):
            eq.build_ranges(eight+[eight[0]])
        self.assertAlmostEqual(eq._player_entry_probability(
            sources[0],{"entry_mode":"never"},eq.HAND_COMBOS["AKs"][0]),0.0)
        self.assertAlmostEqual(eq._player_entry_probability(
            sources[0],{"entry_mode":"always"},eq.HAND_COMBOS["AKs"][0]),1.0)
        # BB RFI has no opening range. An explicitly inactive seat
        # cannot make an otherwise valid multiway calculation fail.
        inactive={"profile":"builtin:pc_gto_80bb","position":"BB",
                  "scenario":"rfi","players":9,"entry_mode":"never"}
        skipped,prov=eq.build_ranges([inactive])
        self.assertEqual(prov[0]["entry_mode"],"never")
        self.assertAlmostEqual(eq._player_entry_probability(
            skipped[0],prov[0],eq.HAND_COMBOS["AKs"][0]),0.0)

    def test_entry_probability_complete_matrix_and_no_showdown(self):
        opts=[
          {"profile":"builtin:any_two","position":"9","scenario":"rfi",
           "players":9,"entry_mode":"manual","entry_pct":0},
        ]
        out=eq.calculate_matrix(opts,trials=50,cycles=1)
        self.assertEqual(len(out["equity"]),169)
        self.assertTrue(all(x is None for x in out["equity"].values()))
        self.assertEqual(out["entry_counts_pct"],[100,0.0])
        self.assertTrue(all(x is None for x in out["pot_multiple"].values()))
        opts[0]["entry_pct"]=100
        out=eq.calculate_matrix(opts,trials=50,cycles=1)
        self.assertTrue(all(x is not None for x in out["equity"].values()))
        self.assertEqual(out["entry_counts_pct"],[0.0,100.0])

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

    def test_box_pool_allows_empty_boxes_but_keeps_all_169_classes(self):
        doc = core.preset("builtin:a17_v5","3","rfi")
        for hand in core.HANDS:
            if doc["boxes"][hand] == 17:
                doc["boxes"][hand] = 0
        clean = core.validate_plan(doc)
        self.assertEqual(set(clean["boxes"]),set(core.HANDS))
        self.assertNotIn(17,clean["boxes"].values())
        self.assertIn(0,clean["boxes"].values())
        self.assertEqual(clean["hands"],core.validate_plan(doc)["hands"])
        self.assertEqual(set(core.boxes_v5().values()),set(range(1,18)))
        doc["boxes"]["AA"] = -1
        with self.assertRaisesRegex(ValueError,"Номер коробки"):
            core.validate_plan(doc)
        doc["boxes"]["AA"] = True
        with self.assertRaisesRegex(ValueError,"Номер коробки"):
            core.validate_plan(doc)
        doc["boxes"].pop("AA")
        with self.assertRaisesRegex(ValueError,"169"):
            core.validate_plan(doc)

    def test_visual_box_reorder_persists_with_unassigned_pool(self):
        with tempfile.TemporaryDirectory() as td, patch.object(core,"STORE",Path(td)):
            base = core.preset("builtin:a17_v5","3","rfi")
            original_hands = base["hands"].copy()
            old_box = base["boxes"]["AQs"]
            base["boxes"]["AQs"] = 0
            base["box_order"] = [17,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16]
            first = core.save_plan(base)
            self.assertEqual(first["box_order"][0],17)
            self.assertEqual(first["boxes"]["AQs"],0)
            self.assertEqual(first["hands"],core.validate_plan(base)["hands"])
            self.assertEqual(core.get_saved(first["ref"])["box_order"],base["box_order"])
            self.assertEqual(core.get_saved(first["ref"])["boxes"]["AQs"],0)
            second = core.save_plan(first,parent=first["ref"])
            self.assertEqual(second["version"],2)
            self.assertEqual(second["box_order"][0],17)
            self.assertEqual(core.boxes_v5()["AQs"],old_box)
            bad = dict(base,box_order=[1]*17)
            with self.assertRaisesRegex(ValueError,"повторяться"):
                core.validate_plan(bad)
            bad["box_order"] = [1,2]
            with self.assertRaisesRegex(ValueError,"17 номеров"):
                core.validate_plan(bad)
            legacy = dict(base)
            legacy.pop("box_order")
            self.assertEqual(core.validate_plan(legacy)["box_order"],list(range(1,18)))

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

    def test_direct_range_equity_joint_distribution_and_split_pots(self):
        anytwo=eq.WeightedRange(core.range_weights(core.preset("builtin:any_two")))
        hero=core.range_weights(core.preset("builtin:any_two"))
        hu=eq.simulate_range_equity(hero,[anytwo],trials=500,seed=91)
        multi=eq.simulate_range_equity(hero,[anytwo,anytwo,anytwo],trials=500,seed=91)
        self.assertEqual(hu["method"],"joint_range_multiway_MC_V1")
        self.assertTrue(42<=hu["equity_pct"]<=58)
        self.assertTrue(16<=multi["equity_pct"]<=34)
        self.assertEqual(multi["trials"],500)

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

    def test_full_archive_preserves_versioned_strategies(self):
        import replit_simulator as service
        with tempfile.TemporaryDirectory() as td:
            location=Path(td)
            with patch.object(service,"OUT",location),patch.object(core,"STORE",location/"strategy_plans"):
                created=core.save_plan(core.preset("builtin:a17_v5","3","rfi"))
                with tempfile.TemporaryFile() as stream:
                    summary=service.write_full_backup(stream)
                    self.assertEqual(summary["strategy_revisions"],1)
                    stream.seek(0)
                    self.assertIn("reference/saved_strategies.json",__import__("zipfile").ZipFile(stream).namelist())
                    stream.seek(0)
                    import tempfile as temporary
                    with temporary.NamedTemporaryFile(suffix=".zip") as back:
                        back.write(stream.read())
                        back.flush()
                        restored=service.import_full_backup(back.name)
                self.assertEqual(restored["strategies_restored"],1)
                self.assertEqual(restored["strategy_revisions_restored"],1)
                self.assertEqual(len(core.list_saved()),2)
                self.assertEqual(core.get_saved(created["ref"])["boxes"]["JTo"],14)

    def test_initial_multiway_opponents_have_nonempty_defined_ranges(self):
        """On first launch the three default opponent policies must be calculable."""
        opponents=[
            {"profile":"builtin:gto_heuristic","position":"9","scenario":"rfi","players":9,"selector":"active"},
            {"profile":"builtin:any_two","position":"4","scenario":"rfi","players":9,"selector":"active"},
            {"profile":"builtin:a17_v5","position":"6","scenario":"rfi","players":9,"selector":"active"},
        ]
        for model in ("selected","any_two","gto_heuristic"):
            ranges, provenance = eq.build_ranges(opponents,model)
            self.assertEqual(len(ranges),3)
            self.assertTrue(all(r.total>0 for r in ranges))
            self.assertEqual(len(provenance),3)
        # A17 BB RFI remains genuinely undefined; don't invent a range to hide errors.
        opponents[2]["position"]="BB"
        with self.assertRaisesRegex(ValueError,"пустой диапазон"):
            eq.build_ranges(opponents,"selected")

    def test_endpoint_request_rejects_unsupported_scenarios(self):
        req={"model":"selected","trials":100,"opponents":[{
            "profile":"builtin:a17_v5","position":"9","scenario":"vs_open","players":9,
            "selector":"active"}]}
        with self.assertRaisesRegex(ValueError,"пустой диапазон"):
            api.start_equity(req)
        req["opponents"][0]["scenario"]="rfi"
        with self.assertRaises(RuntimeError):
            api.start_equity(req,busy=True)

    def test_independent_mc_cycles_aggregate_and_progress(self):
        opponents=[{"profile":"builtin:any_two","position":"3","scenario":"rfi",
                    "players":9,"selector":"active"}]
        samples=[]
        def fake(hand, ranges, trials, seed):
            samples.append((hand,trials,seed))
            return 40.0 if len(samples)%2 else 60.0
        progress=[]
        with patch.object(eq,"simulate_hand",side_effect=fake):
            result=eq.calculate_matrix(opponents,trials=100,cycles=2,
                                       progress=lambda done,total:progress.append((done,total)))
        self.assertEqual(result["simulations_per_hand"],200)
        self.assertEqual(result["cycles"],2)
        self.assertEqual(result["trials_per_cycle"],100)
        self.assertEqual(len(samples),338)
        self.assertEqual(result["equity"]["AA"],50.0)
        self.assertEqual(progress[-1],(338,338))
        self.assertNotEqual(samples[0][2],samples[1][2])
        with self.assertRaisesRegex(ValueError,"Циклов"):
            eq.calculate_matrix(opponents,trials=100,cycles=5)

    def test_box_equity_is_joint_showdown_not_threshold_coverage(self):
        import time
        opponents=[{"profile":"builtin:any_two","position":"3","scenario":"rfi",
                    "players":9,"selector":"active"}]
        boxes=core.boxes_v5()
        box17=[h for h in core.HANDS if boxes[h]==17]
        for h in box17:boxes[h]=0
        seen=[]
        def fake_range(weights,sources,trials,seed):
            seen.append((dict(weights),trials,seed))
            return {"equity_pct":37.5,"trials":trials}
        with tempfile.TemporaryDirectory() as td, \
             patch.object(api,"CACHE_PATH",Path(td)), \
             patch.object(api,"EQUITY_TASKS",{}), \
             patch.object(eq,"simulate_range_equity",side_effect=fake_range):
            job=api.start_box_equity({"boxes":boxes,"opponents":opponents,
                                     "trials":100,"cycles":2})
            for _ in range(150):
                job=api.get_task(job["id"])
                if job["status"]=="completed":break
                time.sleep(0.01)
            self.assertEqual(job["status"],"completed",job.get("error"))
            result=job["result"]
            self.assertIsNone(result["equity"]["17"])
            self.assertEqual(result["equity"]["1"],37.5)
            self.assertEqual(result["trials_per_box"],400)
            self.assertEqual(len(seen),32)
            self.assertEqual(set(seen[0][0]),{h for h in core.HANDS if boxes[h]==1})
            self.assertTrue(all(v==1.0 for v in seen[0][0].values()))
            self.assertTrue(all(trials==200 for _,trials,_ in seen))
            again=api.start_box_equity({"boxes":boxes,"opponents":opponents,
                                        "trials":100,"cycles":2})
            self.assertEqual(again["status"],"completed")
            self.assertTrue(again["cached"])
            self.assertEqual(len(seen),32)

    def test_two_parallel_mc_jobs_and_third_queued(self):
        import threading,time
        gate=threading.Event()
        started=threading.Event()
        active=[]
        state_lock=threading.Lock()
        def work(key):
            def compute(progress):
                with state_lock:
                    active.append(key)
                    if len(active)>=2:started.set()
                if not gate.wait(5):raise RuntimeError("test timeout")
                progress(1,1)
                return {"equity":{h:51.0 for h in core.HANDS}}
            return compute
        with tempfile.TemporaryDirectory() as td, \
             patch.object(api,"CACHE_PATH",Path(td)), \
             patch.object(api,"EQUITY_TASKS",{}):
            try:
                jobs=[api._schedule(str(i)*64,work(str(i)),1) for i in range(3)]
                self.assertTrue(started.wait(3),"two workers did not start")
                self.assertEqual(api.get_task(jobs[2]["id"])["status"],"queued")
                self.assertEqual(len(active),2)
                same=api._schedule("0"*64,work("repeat"),1)
                self.assertEqual(same["id"],jobs[0]["id"])
            finally:
                gate.set()
            for _ in range(150):
                statuses=[api.get_task(job["id"])["status"] for job in jobs]
                if statuses==["completed"]*3:break
                time.sleep(0.01)
            self.assertEqual(statuses,["completed"]*3)


if __name__ == "__main__":
    unittest.main()
