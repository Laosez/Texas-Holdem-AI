"""Contract tests for selected workbook Board16 overlay."""
import json
import unittest
from pathlib import Path

from postflop_board150 import classify_request, classify_board, parse_physical_board
from postflop_compact16 import LABELS

ROOT = Path(__file__).resolve().parent


class CompactBoard16Tests(unittest.TestCase):
    def classify(self, cards):
        return classify_request({"board": cards})

    def test_exactly_16_selected_features(self):
        self.assertEqual(len(LABELS), 16)
        self.assertNotIn("P0", LABELS)
        self.assertNotIn("S4-1", LABELS)
        self.assertNotIn("SF4-2", LABELS)

    def test_sheet_sample_covers_s1_s2_s3_s4_and_sf4(self):
        for cards, expected in [
            ("2c 4c 7d 9d Qh", "S1"),
            ("6c 7d Qh 3s Ac", "S2"),
            ("7c 8d 9h Ks 2c", "S3"),
            ("6c 7d 8h 9s Kc", "S4"),
            ("5s 6s 7s 8s Kd", "SF4"),
            ("5s 6s 8s 9s Kd", "SF4"),
            ("5s 6s 7s 8s 9s", "SF5"),
        ]:
            with self.subTest(board=cards):
                self.assertIn(expected, self.classify(cards)["compact"]["codes"])

    def test_outs_distinguish_open_ended_and_gutshot(self):
        open_ended=self.classify("5s 6s 7s 8s Kd")
        gutshot=self.classify("5s 6s 8s 9s Kd")
        self.assertEqual(open_ended["compact"]["straight_completion_count"], 2)
        self.assertEqual(gutshot["compact"]["straight_completion_count"], 1)
        self.assertEqual(open_ended["compact"]["straight_flush_completion_count"], 2)
        self.assertEqual(gutshot["compact"]["straight_flush_completion_count"], 1)
        self.assertEqual(open_ended["compact"]["straight_flush_completion_cards"],
                         [{"rank":4,"suit":3},{"rank":9,"suit":3}])
        self.assertEqual(gutshot["compact"]["straight_flush_completion_cards"],
                         [{"rank":7,"suit":3}])

    def test_pair_aliases_and_five_card_made_hands(self):
        examples = {
            "Kc Kd 8h 4s 2c": "P1",
            "Kc Kd 8h 8s 2c": "P2",
            "Kc Kd Kh 8s 2c": "P3",
            "Kc Kd Kh 8s 8c": "P3-2",
            "Kc Kd Kh Ks 2c": "P4",
            "5c 6d 7h 8s 9c": "S5",
            "As Qs 9s 6s 3s": "F5",
        }
        for board, code in examples.items():
            with self.subTest(board=board):
                self.assertIn(code,self.classify(board)["compact"]["codes"])

    def test_never_changes_stable_75_ids(self):
        with (ROOT / "data" / "postflop_board150_catalog.json").open(encoding="utf8") as fh:
            catalog=json.load(fh)
        self.assertEqual(catalog["reachable_codes"],75)
        with (ROOT / "data" / "postflop_compact16_catalog.json").open(encoding="utf8") as fh:
            selected=json.load(fh)
        self.assertEqual(selected["reachable_codes"],49)
        self.assertEqual(sum(x["deals"] for x in selected["rows"]),2598960)
        for row in selected["rows"]:
            self.assertEqual(self.classify(row["example"])["compact"]["id"],row["id"])
        for row in catalog["rows"]:
            with self.subTest(id=row["id"]):
                obj=classify_board(parse_physical_board(row["example"]))
                self.assertIn(" · ",obj["id"])
                self.assertEqual(obj["legacy_id"],row["id"])
                self.assertTrue(set(obj["compact"]["codes"])<=set(LABELS))
                self.assertNotIn("P0",obj["compact"]["codes"])

    def test_turn_and_flop_have_own_prefix_and_selected_codes(self):
        for cards,prefix in [("6c-7d-9h","FLOP|"),("5s-6s-7s-8s","TURN|")]:
            found=self.classify(cards)
            self.assertTrue(found["id"].startswith(prefix))
            self.assertTrue(found["compact"]["codes"])


if __name__ == "__main__":
    unittest.main()
