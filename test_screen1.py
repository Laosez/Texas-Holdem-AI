"""Screen 1: per-seat strategy validation, session restore and ZIP lifecycle."""
import csv
import io
import json
import tempfile
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
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
    def test_user_saved_plans_share_catalog_and_are_real_preflop_bots(self):
        import os
        from types import SimpleNamespace
        from unittest.mock import patch as mock_patch
        import planner_core as core
        from bots import create_bot
        from bots.saved_plan_bot import token_for, saved_document, SavedPlanPreflopBot

        with tempfile.TemporaryDirectory() as tmp, mock_patch.object(
                core,"STORE",Path(tmp)/"strategy_plans"):
            base=core.preset("builtin:a17_v5","9","rfi",9)
            base["name"]="Моя A17 · тест"
            base["hands"]["AA"]={"fold":100}
            first=core.save_plan(base)
            btn=core.preset(first["ref"],"3","rfi",9)
            btn["hands"]["AA"]={"open":100}
            second=core.save_plan(btn,parent=first["ref"])
            token=token_for(second["ref"])
            self.assertNotIn(":",token)
            catalog=app.strategy_catalog()
            row=next(x for x in catalog["saved_preflop"] if x["token"]==token)
            self.assertEqual(row["ref"],second["ref"])
            self.assertEqual(row["name"],"Моя A17 · тест")
            self.assertIn(token,catalog["preflop_strategies"])
            self.assertIn(token,catalog["strategies"])
            self.assertTrue(app.existing_saved_token(token))
            config=app.validate_config({"bots":[
                {"pre":token,"post":"tag_punisher"},
                {"pre":"gto","post":"gto"}]})
            self.assertEqual(config["players"][0],f"P1=split:{token}:tag_punisher")
            with self.assertRaisesRegex(ValueError,"префлоп"):
                app.validate_config({"bots":[{"pre":"plan_fake_v1","post":"gto"},
                                          {"pre":"gto","post":"gto"}]})
            with self.assertRaisesRegex(ValueError,"постфлоп"):
                app.validate_config({"bots":[{"pre":"gto","post":token},
                                          {"pre":"gto","post":"gto"}]})
            view=SimpleNamespace(
                me="P1",street="preflop",position="9",
                hole_cards=[("A","s"),("A","h")],board=[],pot=3,
                to_call=2,legal_actions=[{"type":"fold"},{"type":"call"},
                        {"type":"raise","min":4,"max":200}],
                stacks={f"P{i}":200 for i in range(1,10)},history=[])
            bot=create_bot(f"split:{token}:tag_punisher")
            self.assertIsInstance(bot.preflop_bot,SavedPlanPreflopBot)
            self.assertEqual(bot.act(view).type,"fold")
            view.position="3"
            self.assertEqual(bot.act(view).type,"raise")
            # Missing individual range or context is delegated, not folded.
            view.position="8"
            bot.preflop_bot.base_bot.act=lambda _:__import__("core.bot_api",fromlist=["Action"]).Action("call")
            self.assertEqual(bot.act(view).type,"call")
            # Each run keeps an immutable copy even if its source disappears.
            folder=Path(tmp)/"run_snapshot"
            folder.mkdir()
            app.pin_saved_plans(config,folder)
            copy=(folder/"plan_snapshots"/f"{token}.json").read_bytes()
            with mock_patch.dict(os.environ,{"POKER_PLAN_SNAPSHOT_DIR":str(folder/"plan_snapshots")}):
                self.assertEqual(saved_document(token)["name"],"Моя A17 · тест")
                (core.STORE/second["id"]/f"v{second['version']:05}.json").unlink()
                self.assertEqual(saved_document(token)["ref"],second["ref"])
                self.assertEqual((folder/"plan_snapshots"/f"{token}.json").read_bytes(),copy)
                self.assertEqual(create_bot(token).act(view).type in ("fold","call","raise","check"),True)

    def test_saved_street_strategy_catalog_frontend_sync(self):
        page=app.UI.read_text(encoding="utf-8")
        self.assertIn('id="syncStrategies"',page)
        self.assertIn("catalog.saved_preflop||[]",page)
        self.assertIn("names[saved.token]=saved.name+",page)
        self.assertIn("preflopValues=['',...defaults.filter",page)
        self.assertIn("$('syncStrategies').onclick=",page)
        self.assertIn('href="/plan"',page)

    def test_pc_gto_80bb_preset_registered(self):
        import bots
        from bots.pc_gto_80bb_ranges import HANDS, RAISE, rfi_actions, weighted_rfi, chart_position
        import planner_core
        self.assertEqual(len(HANDS),169)
        self.assertEqual(set(RAISE),{"UTG","UTG1","LJ","HJ","CO","BTN","SB"})
        self.assertEqual(chart_position("3",9),"BTN")
        self.assertEqual(chart_position("4",9),"CO")
        self.assertEqual(chart_position("9",9),"UTG")
        self.assertIsNone(chart_position("BB",9))
        chart=planner_core.preset("builtin:pc_gto_80bb",position="3",players=9)
        self.assertEqual(len(chart["hands"]),169)
        self.assertEqual(chart["hands"]["AA"],{"fold":0,"open":100})
        self.assertEqual(rfi_actions("AA","3",9),{"fold":0,"open":100})
        self.assertEqual(rfi_actions("72o","9",9),{"fold":100,"open":0})
        sb=planner_core.preset("builtin:pc_gto_80bb",position="SB",players=9)
        self.assertTrue(any(x.get("limp",0)>0 for x in sb["hands"].values()))
        for name,want in (("UTG",16.20),("UTG1",18.80),("LJ",22.05),
                          ("HJ",27.86),("CO",35.31),("BTN",53.89)):
            self.assertLess(abs(weighted_rfi(name)["raise"]-want),0.5,name)
        self.assertLess(abs(weighted_rfi("SB")["raise"]-8.16),1.5)
        self.assertLess(abs(weighted_rfi("SB")["limp"]-82.72),1.5)
        for name in RAISE:
            self.assertEqual(round(sum(weighted_rfi(name).values()),6),100)
        chosen=app.validate_config({"bots":[{"pre":"pc_gto_80bb","post":"gto"},
                                           {"pre":"gto","post":"gto"}]})
        self.assertEqual(chosen["players"][0],"P1=split:pc_gto_80bb:gto")
        self.assertIsNotNone(bots.create_bot(chosen["players"][0].split("=",1)[1]))

    def test_pc_80bb_bot_uses_real_quarter_mixes_and_correct_rfi_sizing(self):
        from types import SimpleNamespace
        from core.bot_api import Action
        from bots.gto_fixed_bot import FixedGTOPreflopBot
        from bots.pc_gto_80bb_bot import PCGTO80bbBot
        from bots.pc_gto_80bb_ranges import rfi_actions
        import bots.pc_gto_80bb_bot as policy
        bot=PCGTO80bbBot()
        players={str(i):500 for i in range(9)}
        state=SimpleNamespace(stacks=players,history=[],me="0")
        legal=[{"type":"fold"},{"type":"call"},{"type":"raise","min":4,"max":500}]
        with patch.object(policy.random,"randrange",return_value=0):
            aa=bot._preflop([("A","s"),("A","h")],"9",3,2,legal,state)
            self.assertEqual((aa.type,aa.amount),("raise",5))  # 2.3bb at 1/2 blinds
            sb=bot._preflop([("A","s"),("K","s")],"SB",3,1,legal,state)
            self.assertEqual((sb.type,sb.amount),("raise",7))  # SB 3.5bb
        with patch.object(policy.random,"randrange",return_value=99):
            sb=bot._preflop([("A","s"),("K","s")],"SB",3,1,legal,state)
            self.assertEqual(sb.type,"call")
            weak=bot._preflop([("7","s"),("2","h")],"9",3,2,legal,state)
            self.assertEqual(weak.type,"fold")
        state.history=[{"street":"preflop","type":"raise","pid":"1"}]
        with patch.object(FixedGTOPreflopBot,"_preflop",return_value=Action("fold")) as base:
            action=bot._preflop([("A","s"),("A","h")],"9",10,6,legal,state)
            self.assertEqual(action.type,"fold")
            base.assert_called_once()
        self.assertEqual(rfi_actions("AKs","SB",9),{"fold":0,"open":75,"limp":25})

    def test_btn_chart_is_not_utg_and_is_available_to_tournaments(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        import bots
        import planner_core
        import bots.pc_gto_80bb_bot as source
        from bots.pc_gto_80bb_ranges import rfi_actions, chart_position, weighted_rfi
        self.assertEqual({chart_position("3", n) for n in range(3, 10)}, {"BTN"})
        self.assertEqual(chart_position("4", 9), "CO")
        btn = planner_core.preset("builtin:pc_gto_80bb", "3", "rfi", 9, 80)
        self.assertEqual(len(btn["hands"]), 169)
        self.assertEqual(btn["hands"]["K2s"]["open"], 100)
        self.assertEqual(rfi_actions("K2s", "9", 9)["open"], 0)
        self.assertAlmostEqual(weighted_rfi("BTN")["raise"], 53.89, delta=0.5)
        state = SimpleNamespace(stacks={str(i): 500 for i in range(9)},
                                history=[], me="0")
        legal = [{"type": "fold"}, {"type": "call"},
                 {"type": "raise", "min": 4, "max": 500}]
        bot = bots.create_bot("split:pc_gto_80bb:tag_punisher")
        with patch.object(source.random, "randrange", return_value=99):
            btn_move = bot.preflop_bot.bot._preflop(
                [("K", "s"), ("2", "s")], "3", 3, 2, legal, state
            )
            utg_move = bot.preflop_bot.bot._preflop(
                [("K", "s"), ("2", "s")], "9", 3, 2, legal, state
            )
        self.assertEqual(btn_move.type, "raise")
        self.assertEqual(utg_move.type, "fold")

    def test_screen1_only_offers_three_preflop_charts_and_one_random(self):
        catalog = app.strategy_catalog()
        self.assertEqual(set(catalog["preflop_strategies"]),
                         {"a17_preflop", "gto", "pc_gto_80bb"})
        self.assertIn("tag_punisher", catalog["postflop_strategies"])
        self.assertEqual(catalog["postflop_strategies"].count("random"), 1)
        for pre in ("tag_punisher", "smart", "random", "gto_fixed"):
            with self.subTest(pre=pre), self.assertRaisesRegex(ValueError, "префлоп"):
                app.validate_config({"bots": [
                    {"pre": pre, "post": "gto"},
                    {"pre": "gto", "post": "tag_punisher"}]})
        for post in ("pc_gto_80bb", "a17_preflop"):
            with self.subTest(post=post), self.assertRaisesRegex(ValueError, "постфлоп"):
                app.validate_config({"bots": [
                    {"pre": "gto", "post": post},
                    {"pre": "a17_preflop", "post": "gto"}]})
        result = app.validate_config({"bots": [
            {"pre": "pc_gto_80bb", "post": "tag_punisher"},
            {"pre": "gto", "post": "random"},
            {"pre": "a17_preflop", "post": "random"},
            {"pre": "gto", "post": "random_9"},
        ]})
        self.assertEqual([x["post"] for x in result["bots"]],
                         ["tag_punisher", "random", "random_2", "random_3"])
        self.assertEqual(result["players"][0], "P1=split:pc_gto_80bb:tag_punisher")
        import bots
        self.assertTrue(all(bots.create_bot(p.split("=", 1)[1])
                            for p in result["players"]))
        page = app.UI.read_text(encoding="utf-8")
        self.assertIn("let preflopValues=['','a17_preflop','gto','pc_gto_80bb'];", page)
        self.assertIn("BTN (позиция 3; ~53,9% Raise)", page)
        self.assertIn("row.append(botOptions(b.pre", page)
        self.assertIn("'pre'));", page)
        self.assertIn("'post'));", page)
        self.assertIn("preflop_strategies", page)
        self.assertNotIn("values=['','gto','gto_fixed'", page)

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

    def test_explicit_trash_panel_has_individual_restore_and_purge_consent(self):
        page=app.UI.read_text(encoding="utf-8")
        for part in ('id="trashPanel" hidden','id="trashItems"',
                     'id="trashConfirm" type="checkbox"','id="purgeTrash"',
                     'id="trashReload"','async function reloadTrash()',
                     "$('trashConfirm').onchange=","if(!result.ok)throw Error(",
                     "const data=await get('/api/trash',{method:'DELETE'});",
                     "const result=await get('/api/runs/'+id,{method:'DELETE'});"):
            self.assertIn(part,page)
        self.assertNotIn("ID сессии для восстановления из корзины",page)
        self.assertNotIn("confirmation!=='УДАЛИТЬ'",page)
        self.assertIn("if(result.id!==id)throw Error(",page)

    def test_trash_restore_and_purge_file_lifecycle(self):
        with tempfile.TemporaryDirectory() as td, patch.object(app,"OUT",Path(td)):
            run_id="test_trash_450"
            folder=Path(td)/run_id
            folder.mkdir()
            snapshot={"id":run_id,"status":"completed",
                      "created":app.now(),"updated":app.now(),"config":{},
                      "log":[],"returncode":0}
            (folder/"job.json").write_text(json.dumps(snapshot),encoding="utf-8")
            with app.MUTEX:
                old=dict(app.RUNS);app.RUNS.clear();app.RUNS[run_id]=snapshot
            try:
                app.delete_session(run_id)
                self.assertTrue((Path(td)/".trash"/run_id/"job.json").is_file())
                self.assertNotIn(run_id,app.RUNS)
                restored=app.restore_deleted(run_id)
                self.assertEqual(restored["id"],run_id)
                self.assertTrue((Path(td)/run_id/"job.json").is_file())
                app.delete_session(run_id)
                # Trash is independent of the live tournament directories.
                active_id="ongoing_live_job"
                app.RUNS[active_id]={"id":active_id,"status":"running"}
                try:
                    self.assertEqual(app.purge_trash(),1)
                    self.assertIn(active_id,app.RUNS)
                finally:
                    app.RUNS.pop(active_id,None)
                self.assertFalse((Path(td)/".trash"/run_id).exists())
                self.assertEqual(app.purge_trash(),0)
            finally:
                with app.MUTEX:
                    app.RUNS.clear();app.RUNS.update(old)

    def test_trash_http_delete_list_restore_and_permanent_purge(self):
        with tempfile.TemporaryDirectory() as td, patch.object(app,"OUT",Path(td)), \
             patch.object(app,"TOKEN","test_trash_key"):
            run_id="test_http_trash_run"
            folder=Path(td)/run_id
            folder.mkdir()
            record={"id":run_id,"status":"completed","created":app.now(),
                    "updated":app.now(),"config":{},"log":[],
                    "returncode":0}
            (folder/"job.json").write_text(json.dumps(record),encoding="utf-8")
            with app.MUTEX:
                old=dict(app.RUNS);app.RUNS.clear();app.RUNS[run_id]=record
            server=ThreadingHTTPServer(("127.0.0.1",0),app.Handler)
            thread=threading.Thread(target=server.serve_forever,daemon=True)
            thread.start()
            url=f"http://127.0.0.1:{server.server_address[1]}"
            def request(path,method="GET",body=None,authorized=True):
                headers={"X-Runner-Key":"test_trash_key"} if authorized else {}
                if body is not None:headers["Content-Type"]="application/json"
                req=urllib.request.Request(url+path,method=method,headers=headers,
                                           data=body.encode() if body is not None else None)
                with urllib.request.urlopen(req,timeout=10) as response:
                    return response.status,json.loads(response.read())
            try:
                with self.assertRaises(urllib.error.HTTPError) as unauthorized:
                    request("/api/trash",authorized=False)
                self.assertEqual(unauthorized.exception.code,401)
                code,deleted=request("/api/runs/"+run_id,method="DELETE")
                self.assertEqual(code,200)
                self.assertTrue(deleted["ok"])
                _,trash=request("/api/trash")
                self.assertEqual(trash["deleted"],[run_id])
                _,restored=request("/api/trash/"+run_id+"/restore",method="POST",body="{}")
                self.assertEqual(restored["id"],run_id)
                _,empty=request("/api/trash")
                self.assertEqual(empty["deleted"],[])
                request("/api/runs/"+run_id,method="DELETE")
                code,purged=request("/api/trash",method="DELETE")
                self.assertEqual(code,200)
                self.assertEqual(purged["purged"],1)
                _,empty=request("/api/trash")
                self.assertEqual(empty["deleted"],[])
                self.assertFalse((Path(td)/".trash"/run_id).exists())
            finally:
                server.shutdown();server.server_close();thread.join(timeout=5)
                with app.MUTEX:
                    app.RUNS.clear();app.RUNS.update(old)


if __name__ == "__main__":
    unittest.main()
