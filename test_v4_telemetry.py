"""Focused regression tests for the V4 tournament telemetry aggregation."""
import unittest

from export_preflop_ranges_v4 import tournament_report, TrackedBot, summarize_bot_timings
from unittest.mock import patch


class TournamentTelemetryTests(unittest.TestCase):
    def test_completed_tournament_has_one_winner_and_actual_blinds(self):
        outcome = {
            'winner': 'P2', 'completed': True, 'status': 'completed',
            'hand_count': 2,
            'finish_order': [('P1', 2, 2, 0), ('P2', 1, 2, 1000)],
            'blind_stages': [
                {'level': 1, 'sb': 1, 'bb': 2, 'start_hand': 1, 'end_hand': 1, 'hands': 1},
                {'level': 2, 'sb': 2, 'bb': 4, 'start_hand': 2, 'end_hand': 2, 'hands': 1},
            ],
        }
        result, files = tournament_report(
            [(1, 42, 0, outcome)], ['smart', 'gto'], 1,
            500, 1, 2, 1, 10000, 'rotate')
        self.assertEqual(result['wins_total'], 1)
        self.assertEqual(result['tournaments_completed'], 1)
        self.assertEqual(result['total_hands'], 2)
        self.assertEqual(result['leaderboard'][0]['bot'], 'gto')
        self.assertEqual(result['leaderboard'][0]['wins'], 1)
        self.assertEqual(sum(x['hands'] for x in result['blind_summary']), 2)
        self.assertEqual(len(files['tournament_players.csv']), 3)

    def test_hand_limit_creates_no_fake_winner(self):
        outcome = {
            'winner': None, 'completed': False, 'status': 'hand_limit',
            'hand_count': 1,
            'finish_order': [('P1', 0, 1, 500), ('P2', 0, 1, 500)],
            'blind_stages': [
                {'level': 1, 'sb': 1, 'bb': 2, 'start_hand': 1, 'end_hand': 1, 'hands': 1},
            ],
        }
        result, _ = tournament_report(
            [(1, 42, 0, outcome)], ['smart', 'gto'], 1,
            500, 1, 2, 50, 1, 'rotate')
        self.assertEqual(result['wins_total'], 0)
        self.assertEqual(result['tournaments_unfinished'], 1)
        self.assertTrue(all(row['avg_position_completed'] is None for row in result['leaderboard']))

    def test_rejects_duplicate_seat(self):
        outcome = {
            'winner': 'P1', 'completed': True, 'status': 'completed',
            'hand_count': 1,
            'finish_order': [('P1', 1, 1, 1000), ('P1', 2, 1, 0)],
            'blind_stages': [
                {'level': 1, 'sb': 1, 'bb': 2, 'start_hand': 1, 'end_hand': 1, 'hands': 1},
            ],
        }
        with self.assertRaisesRegex(RuntimeError, 'missing/duplicate'):
            tournament_report([(1, 42, 0, outcome)], ['smart', 'gto'], 1,
                              500, 1, 2, 50, 10000, 'rotate')


class BotTimingTests(unittest.TestCase):
    def test_counts_strategy_calls_both_streets_without_changing_actions(self):
        class Strategy:
            def act(self, view):
                return 'unchanged'
        class View:
            street = 'preflop'
            hole_cards = None
            hand_id = None

        bot = TrackedBot(Strategy(), 'gto')
        view = View()
        with (patch('export_preflop_ranges_v4.time.thread_time_ns', side_effect=[100, 5100, 5200, 12200]),
              patch('export_preflop_ranges_v4.time.perf_counter_ns', side_effect=[1000, 9000, 9100, 24100])):
            self.assertEqual(bot.act(view), 'unchanged')
            view.street = 'flop'
            self.assertEqual(bot.act(view), 'unchanged')
        self.assertEqual(bot.decision_timing['preflop']['decisions'], 1)
        self.assertEqual(bot.decision_timing['postflop']['decisions'], 1)
        self.assertEqual(bot.decision_timing['preflop']['cpu_ns'], 5000)
        self.assertEqual(bot.decision_timing['postflop']['wall_ns'], 15000)

    def test_aggregates_across_workers_and_streets(self):
        data = [
            {'bot':'smart','street':'preflop','decisions':4,'cpu_ns':4_000_000,
             'wall_ns':5_000_000,'max_cpu_ns':2_000_000,'max_wall_ns':3_000_000},
            {'bot':'smart','street':'preflop','decisions':6,'cpu_ns':6_000_000,
             'wall_ns':7_000_000,'max_cpu_ns':3_000_000,'max_wall_ns':4_000_000},
            {'bot':'smart','street':'postflop','decisions':2,'cpu_ns':4_000_000,
             'wall_ns':6_000_000,'max_cpu_ns':2_000_000,'max_wall_ns':3_000_000},
            {'bot':'gto','street':'preflop','decisions':2,'cpu_ns':20_000_000,
             'wall_ns':24_000_000,'max_cpu_ns':15_000_000,'max_wall_ns':18_000_000},
        ]
        report, tables = summarize_bot_timings(data, ['smart', 'gto', 'nit'])
        summary = {r['bot']:r for r in report['bots']}
        self.assertEqual(report['total_decisions'], 14)
        self.assertEqual(summary['smart']['decisions'], 12)
        self.assertEqual(summary['smart']['preflop_decisions'], 10)
        self.assertEqual(summary['smart']['postflop_decisions'], 2)
        self.assertEqual(summary['smart']['cpu_seconds'], .014)
        self.assertEqual(summary['smart']['max_cpu_ms'], 3)
        self.assertEqual(summary['smart']['decisions_per_cpu_second'], 857.14)
        self.assertAlmostEqual(summary['smart']['share_decision_cpu_pct'], 41.176, places=3)
        self.assertEqual(summary['nit']['decisions'], 0)
        self.assertIsNone(summary['nit']['mean_cpu_ms'])
        self.assertEqual(len(tables['bot_decision_timing.csv']), 4)
        self.assertEqual(len(tables['bot_decision_timing_by_street.csv']), 7)

    def test_exception_does_not_erase_timing(self):
        class Failing:
            def act(self, view):
                raise ValueError('engine-visible failure')
        class View:
            street = 'turn'
        bot = TrackedBot(Failing(), 'smart')
        with self.assertRaisesRegex(ValueError, 'engine-visible failure'):
            bot.act(View())
        self.assertEqual(bot.decision_timing['postflop']['decisions'], 1)


if __name__ == '__main__':
    unittest.main()

# Keep import-time behavior of the existing tests intact, but include the
# decision-timing regression suite in unittest discovery.
