"""Regression: tournament seat rotation balances physical starting positions."""
import unittest
from run_tournament_stats import rotate_player_specs


class TestSeatingRotation(unittest.TestCase):
    def test_nine_player_full_cycle(self):
        players = [(f"P{i+1}", f"bot{i+1}", None) for i in range(9)]
        cycle = [rotate_player_specs(players, t) for t in range(9)]
        for pid, name, label in players:
            starts = [next(i for i, spec in enumerate(s) if spec[0] == pid) for s in cycle]
            self.assertEqual(sorted(starts), list(range(9)))
        self.assertEqual(rotate_player_specs(players, 9), players)

    def test_original_ids_are_not_reassigned(self):
        players = [("P1", "smart", None), ("P2", "gto", None), ("P3", "tag_punisher", None)]
        self.assertEqual(rotate_player_specs(players, 1),
                         [players[1], players[2], players[0]])
        self.assertEqual(rotate_player_specs(players, 2),
                         [players[2], players[0], players[1]])

    def test_single_and_empty(self):
        self.assertEqual(rotate_player_specs([], 7), [])
        self.assertEqual(rotate_player_specs([("A", "bot", None)], 10),
                         [("A", "bot", None)])


if __name__ == "__main__":
    unittest.main()
