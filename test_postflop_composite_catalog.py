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

    def test_sheet_three_catalog_stays_separate_from_action_sampling(self):
        html=(app.ROOT/"replit_ui/s100.html").read_text(encoding="utf-8")
        for marker in ('id="compositeCatalog"','id="catalogRows"',
                       'id="catalogBoardFilter"','id="catalogHeroFilter"',
                       'id="catalogReviewFilter"','id="catalogSearch"',
                       'id="catalogReset"','catalogMarkStorage',
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
