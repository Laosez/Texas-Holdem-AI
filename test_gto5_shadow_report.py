"""Unit tests for GTO 5.0 shadow-report groupings and EV regret."""
import unittest

from gto5_shadow_report import aggregate_shadow, board_tags, compare


def paired(board, street, opponents=1, chosen="check", bb=100):
    return {
        "board": board, "street": street, "opponents": opponents, "bb": bb,
        "ev5": {"check": 100, "bet:50": 160},
        "ev41": {"check": 120, "bet:50": 180},
        "chosen5": chosen,
        "hand_id": 17, "tournament": 9,
    }


class GTO5ShadowReportTests(unittest.TestCase):
    def test_board_texture_classification(self):
        self.assertEqual(board_tags(["2c", "7h", "Kd"])["P"], "P0")
        self.assertEqual(board_tags(["As", "Ac", "7d"])["P"], "P1")
        self.assertEqual(board_tags(["As", "Ac", "7d", "7h"])["P"], "P2")
        self.assertEqual(board_tags(["As", "Ac", "Ah"])["P"], "P3")
        self.assertEqual(board_tags(["As", "Ac", "Ah", "Ad"])["P"], "P4")
        self.assertEqual(board_tags(["As", "Ac", "Ah", "7d", "7h"])["P"], "PH")
        self.assertEqual(board_tags(["5c", "6c", "7h"])["S"], "S3")
        self.assertEqual(board_tags(["Ac", "2c", "3c", "4c"])["S"], "S4")
        self.assertEqual(board_tags(["Ac", "2c", "3c"])["F"], "F3")
        with self.assertRaises(ValueError):
            board_tags(["As", "As", "7h"])

    def test_ev_difference_and_regret_are_distinct(self):
        row, reason = compare(paired(["As", "Qc", "7h"], "flop", 2))
        self.assertIsNone(reason)
        self.assertAlmostEqual(row["mean_ev_delta_bb"], .2)
        self.assertAlmostEqual(row["regret_bb"], .6)
        self.assertEqual(row["mismatch"], 1)
        self.assertEqual(row["opponents"], "2")
        matched, _ = compare(paired(["As", "Qc", "7h"], "flop", 2, "bet:50"))
        self.assertEqual(matched["regret_bb"], 0)
        self.assertEqual(matched["mismatch"], 0)

    def test_incompatible_sizes_are_excluded_from_denominator(self):
        item = paired(["As", "Qc", "7h"], "flop")
        item["ev41"]["bet:100"] = item["ev41"].pop("bet:50")
        report = aggregate_shadow([paired(["As", "Qc", "7h"], "flop"), item])
        self.assertEqual(report["compared"], 1)
        self.assertEqual(report["skipped"], 1)
        self.assertEqual(report["skip_reasons"]["incompatible_actions"], 1)

    def test_street_opponents_structure_and_rankings(self):
        records = [paired(["As", "Qc", "7h"], "flop", 1)
                   for _ in range(32)]
        records += [paired(["As", "Ac", "7h", "2d"], "turn", 3, "bet:50")
                    for _ in range(40)]
        report = aggregate_shadow(records, minimum=30)
        self.assertEqual(report["compared"], 72)
        groups = report["groups"]
        self.assertEqual(len(groups["street"]), 2)
        self.assertEqual(len(groups["opponents"]), 2)
        self.assertTrue(any(row["label"].startswith("flop | 1 | P0")
                            for row in groups["street_opponents_board"]))
        self.assertTrue(any(row["label"].startswith("turn | 3 | P1")
                            for row in groups["street_opponents_board"]))
        self.assertEqual(report["rankings"]["frequent"][0]["mismatch_pct"], 100)
        self.assertAlmostEqual(report["overall"]["mean_regret_bb"], 32*.6/72, places=4)
        self.assertEqual(report["overall"]["n"], 72)

    def test_low_sample_groups_not_ranked(self):
        items = [paired(["2c", "7d", "9h"], "flop")] * 2
        report = aggregate_shadow(items, minimum=30)
        self.assertEqual(report["groups"]["board_structure"][0]["n"], 2)
        self.assertFalse(report["groups"]["board_structure"][0]["sufficient"])
        self.assertEqual(report["rankings"]["frequent"], [])


if __name__ == "__main__":
    unittest.main()
