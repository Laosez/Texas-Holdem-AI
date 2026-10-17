"""Third shared Poker System sheet: navigation, style and authenticated S100 HTTP."""
import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import replit_simulator as app


class S100ThirdSheetTests(unittest.TestCase):
    def test_every_active_sheet_links_to_the_other_sheets(self):
        main = app.UI.read_text(encoding="utf-8")
        plan = app.PLAN_UI.read_text(encoding="utf-8")
        check = (app.ROOT / "replit_ui/s100.html").read_text(encoding="utf-8")

        for page in (main, plan):
            self.assertIn('<a class="tab" href="/s100"><b>03</b>', page)
            self.assertIn("100 сценариев S100", page)
        self.assertIn('<a class="tab" href="/"><b>01</b>', check)
        self.assertIn('<a class="tab" href="/plan"><b>02</b>', check)
        self.assertIn('<a class="tab current" href="/s100" aria-current="page">', check)
        self.assertEqual(check.count('id="key"'), 1)
        self.assertEqual(check.count('id="connect"'), 1)
        self.assertIn("sessionStorage.getItem('skachkov_key')", check)
        self.assertIn("sessionStorage.setItem('skachkov_key',token())", check)

        shared_tokens = [
            '--bg:#081221', '--line:#314660', '--accent:#7baaf7',
            '.tab.current{background:#1d3b60', '.brand strong{display:block',
            '.panel{min-width:0;background:linear-gradient(140deg,#17283f,#101e30)',
        ]
        for token in shared_tokens:
            with self.subTest(token=token):
                self.assertIn(token, plan)
                self.assertIn(token, check)
        self.assertIn('id="rows"', check)
        self.assertIn('id="inspectorResults"', check)
        self.assertIn('id="count"', check)
        self.assertIn("const auth=()=>({'X-Runner-Key':token()});", check)
        self.assertIn("if(token())connect();else", check)

    def test_third_sheet_and_catalog_http_are_functional(self):
        with patch.object(app, "TOKEN", "s100_test_secret"):
            server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_address[1]}"

            def request(path, *, auth=True, data=None):
                headers = {"X-Runner-Key": "s100_test_secret"} if auth else {}
                if data is not None:
                    headers["Content-Type"] = "application/json"
                req = urllib.request.Request(
                    base + path, headers=headers,
                    data=json.dumps(data).encode() if data is not None else None,
                )
                with urllib.request.urlopen(req, timeout=20) as response:
                    return response.status, response.read()

            try:
                for path in ("/", "/plan", "/s100"):
                    status, document = request(path, auth=False)
                    self.assertEqual(status, 200)
                    self.assertIn(b'STRATEGY EXPERIMENTS', document)
                _, page = request("/s100", auth=False)
                self.assertIn(b'aria-current="page"', page)
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    request("/api/s100", auth=False)
                self.assertEqual(denied.exception.code, 401)

                status, raw_catalog = request("/api/s100")
                rows = json.loads(raw_catalog)["scenarios"]
                self.assertEqual(status, 200)
                self.assertEqual(len(rows), 100)
                self.assertEqual(rows[60]["id"], "S061")

                status, raw = request("/api/s100/inspect", data={
                    "hole": ["As", "Qs"], "board": ["Ad", "Qd", "7c", "7h"],
                    "opponents": 1, "pot": 24, "to_call": 8, "stack": 80,
                })
                decision = json.loads(raw)
                self.assertEqual(status, 200)
                self.assertEqual(decision["scenario"]["id"], "S061")
                self.assertAlmostEqual(sum(decision["actions"].values()), 1)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
