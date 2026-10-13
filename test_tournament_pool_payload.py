"""Regression: archetype bots must not be pickled into Pool task payloads."""
import io
import pickle
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

import run_tournament_stats as stats


class PoolTaskSerializationTests(unittest.TestCase):
    def test_nine_archetype_tournaments_send_only_serializable_specs(self):
        received = []
        pids = [f"P{n}" for n in range(1, 10)]
        finish_order = [(pid, i, 1, 0) for i, pid in enumerate(pids, 1)]

        class CapturingPool:
            def __init__(self, processes):
                self.processes = processes

            def __enter__(self):
                self_test.assertEqual(self.processes, 2)
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def imap_unordered(self, fn, tasks):
                self_test.assertIs(fn, stats.run_silent_tournament)
                for task in tasks:
                    # The pre-fix runner crashes on this exact boundary:
                    # ArchetypeConfig.knobs contains a MappingProxyType.
                    pickle.dumps(task)
                    received.append(task)
                    self_test.assertTrue(all(bot is None for _, _, bot in task[0]))
                    yield {
                        "winner": "P1",
                        "hand_count": 1,
                        "finish_order": finish_order,
                    }

        self_test = self
        bots = (
            "smart,gto,tag_punisher,wide_defender,baseline_sane,nit,"
            "loose_passive,maniac,pressure_filler"
        )
        with patch.object(stats, "Pool", CapturingPool):
            with redirect_stdout(io.StringIO()):
                stats.run_tournament_batch(
                    player_spec_str=bots,
                    num_tournaments=9,
                    chips=500,
                    base_sb=1,
                    base_bb=2,
                    blind_increase_every=50,
                    max_hands=10,
                    parallel=2,
                    output_csv=None,
                    seed=42,
                    seat_mode="rotate",
                )

        self.assertEqual(len(received), 9)
        self.assertEqual([task[-1] for task in received], list(range(42, 51)))
        self.assertEqual(
            [task[0][0][0] for task in received],
            [f"P{n}" for n in range(1, 10)],
        )
        self.assertEqual(
            sorted({task[0][i][0] for task in received for i in range(9)}),
            sorted(pids),
        )


if __name__ == "__main__":
    unittest.main()
