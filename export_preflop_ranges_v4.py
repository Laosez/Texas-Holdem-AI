"""Poker A17: observed preflop ranges with numeric positions, per table size and defense.

Standalone companion to run_tournament_stats.py. Uses its actual tournament engine
and wraps bot adapters without changing their decisions. Supports Python 3.10+.
Uses balanced cyclic seating by default to avoid confounded starting positions.

THAI_ENGINE_IMPL=legacy python export_preflop_ranges_v4.py \
  --players smart,gto,tag_punisher,wide_defender,baseline_sane,nit,loose_passive,maniac,pressure_filler \
  --tournaments 200 --parallel 2 --seed 42 --out ranges_200_v4_numeric
"""
from __future__ import annotations

import argparse
import gzip
import hashlib
import csv
import gc
import itertools
import json
from collections import defaultdict
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
import os
import shutil
import time

from core.table_order import position_labels

RANKS = 'AKQJT98765432'
POSITIONS = tuple(str(k) for k in range(10, 2, -1)) + ('SB', 'BB')
DEFAULT_BOTS = 'smart,gto,tag_punisher,wide_defender,baseline_sane,nit,loose_passive,maniac,pressure_filler'
# Numerator / opportunity for each event. The unit is a dealt hand (not actions).
METRICS = {
    'vpip': 'hands_observed',
    'pfr': 'hands_observed',
    'rfi': 'rfi_opportunities',
    'limp': 'limp_opportunities',
    'call_any': 'call_any_opportunities',
    'call_open': 'call_open_opportunities',
    'cold_call': 'cold_call_opportunities',
    'threebet': 'threebet_opportunities',
    'fourbet': 'fourbet_opportunities',
    'fivebet': 'fivebet_opportunities',
    'call_3bet': 'facing_3bet_opportunities',
    'fold_to_3bet': 'facing_3bet_opportunities',
    'bb_defend': 'bb_defend_opportunities',
    'sb_defend': 'sb_defend_opportunities',
    'fold_to_steal': 'fold_to_steal_opportunities',
    'fold_to_open': 'fold_to_open_opportunities',
    'steal': 'steal_opportunities',
    'squeeze': 'squeeze_opportunities',
}
COUNT_FIELDS = ['hands_observed'] + [f'{m}_n' for m in METRICS] + [
    x for x in dict.fromkeys(METRICS.values()) if x != 'hands_observed'
]


def hand_class(cards):
    if not cards or len(cards) != 2:
        return None
    try:
        (r1,s1),(r2,s2) = cards
        if r1 not in RANKS or r2 not in RANKS:
            return None
        a,b = sorted((r1,r2),key=RANKS.index)
        return a+b+('' if a==b else ('s' if s1==s2 else 'o'))
    except (ValueError, TypeError):
        return None


def class_grid():
    for i,a in enumerate(RANKS):
        for j,b in enumerate(RANKS):
            yield a+b if i==j else (a+b+'s' if i<j else b+a+'o')


def combos(h):
    return 6 if len(h)==2 else 4 if h.endswith('s') else 12


class TrackedBot:
    def __init__(self, inner, name):
        self.inner, self.name = inner, name
        self.hands = {}
        self.postflop_counts = defaultdict(int)
        self.postflop_position_counts = defaultdict(lambda: defaultdict(int))
        self.postflop_stage_counts = defaultdict(lambda: defaultdict(int))
        self.postflop_seen = set()
        self.postflop_cbet_hands = set()
        # Only the strategy call (inner.act), not engine, view creation or
        # the preflop event observer. Time is measured in each worker process.
        self.decision_timing = defaultdict(lambda: {
            'decisions': 0,
            'cpu_ns': 0,
            'wall_ns': 0,
            'max_cpu_ns': 0,
            'max_wall_ns': 0,
        })

    def observe_deal(self, hid, cards, position, table_size):
        """Account for every dealt hand, including BB hands without any action."""
        hand = hand_class(cards)
        if hand is None or hid is None or hid in self.hands:
            return
        row = dict(bot=self.name, pid=getattr(self,'player_id',None), hand=hand, position=str(position),
                   table_size=table_size,
                   **{field:0 for field in COUNT_FIELDS})
        row['hands_observed'] = 1
        self.hands[hid] = row

    def act(self, view):
        # Use thread CPU time as the primary cost metric. Unlike per-call wall
        # time it excludes time this worker is descheduled by the OS. Measure
        # all streets; report preflop separately from postflop.
        street = 'preflop' if getattr(view, 'street', None) == 'preflop' else 'postflop'
        wall_start = time.perf_counter_ns()
        cpu_start = time.thread_time_ns()
        try:
            action = self.inner.act(view)
        finally:
            cpu_ns = max(0, time.thread_time_ns() - cpu_start)
            wall_ns = max(0, time.perf_counter_ns() - wall_start)
            stats = self.decision_timing[street]
            stats['decisions'] += 1
            stats['cpu_ns'] += cpu_ns
            stats['wall_ns'] += wall_ns
            stats['max_cpu_ns'] = max(stats['max_cpu_ns'], cpu_ns)
            stats['max_wall_ns'] = max(stats['max_wall_ns'], wall_ns)
        if street != 'preflop':
            self.observe_postflop(view, action)
            return action
        h = hand_class(getattr(view,'hole_cards',None))
        hid = getattr(view,'hand_id',None)
        if h is None or hid is None:
            return action

        row = self.hands.get(hid)
        if row is None:
            # Fallback when the host engine has no on_deal hook.
            self.observe_deal(hid, getattr(view, 'hole_cards', None),
                              getattr(view, 'position', 'UNKNOWN'),
                              len(getattr(view, 'stacks', {}) or {}))
            row = self.hands[hid]
        legal = {str(k.get('type')) for k in (getattr(view,'legal_actions',None) or [])}
        kind = str(getattr(action,'type','fold'))
        if kind not in legal:
            kind = 'call' if 'call' in legal else ('check' if 'check' in legal else 'fold')
        call_cost = max(0,int(getattr(view,'to_call',0) or 0))
        hist = [e for e in (getattr(view,'history',None) or [])
                if isinstance(e,dict) and e.get('street')=='preflop']
        raises = [e for e in hist if e.get('type') in ('raise','bet','all_in')]
        prior_voluntary = any(e.get('pid')==view.me and e.get('type') in ('call','raise','bet','all_in') for e in hist)
        hero_raised = any(e.get('pid')==view.me for e in raises)
        can_raise = 'raise' in legal or 'bet' in legal
        is_raise = kind in ('raise','bet')
        is_call = kind=='call' and call_cost>0
        is_fold = kind=='fold'
        unopened = not any(e.get('type') in ('call','raise','bet','all_in') for e in hist)
        positions = getattr(view,'position',None)

        def mark(metric, eligible, hit):
            # Eligible may occur in multiple decisions; record at most once / hand.
            opp = METRICS[metric]
            if eligible and not row[opp]:
                row[opp] = 1
            if eligible and hit:
                row[f'{metric}_n'] = 1

        if is_call or is_raise:
            row['vpip_n'] = 1
        if is_raise:
            row['pfr_n'] = 1

        mark('rfi', unopened and can_raise, is_raise)
        mark('limp', not raises and call_cost>0 and 'call' in legal and not prior_voluntary, is_call)
        mark('call_any', call_cost>0 and 'call' in legal, is_call)
        facing_open = len(raises)==1 and raises[-1].get('pid')!=view.me and call_cost>0
        mark('call_open', facing_open and 'call' in legal, is_call)
        mark('cold_call', facing_open and not prior_voluntary and 'call' in legal, is_call)
        mark('threebet', facing_open and can_raise, is_raise)
        facing_3bet = len(raises)==2 and raises[-1].get('pid')!=view.me and call_cost>0 and hero_raised
        mark('call_3bet', facing_3bet and 'call' in legal, is_call)
        mark('fold_to_3bet', facing_3bet and 'fold' in legal, is_fold)
        mark('fourbet', len(raises)==2 and raises[-1].get('pid')!=view.me and call_cost>0 and can_raise, is_raise)
        mark('fivebet', len(raises)>=3 and raises[-1].get('pid')!=view.me and call_cost>0 and can_raise, is_raise)
        mark('bb_defend', positions=='BB' and facing_open and ('call' in legal or can_raise), is_call or is_raise)
        mark('sb_defend', positions=='SB' and facing_open and ('call' in legal or can_raise), is_call or is_raise)
        mark('fold_to_open', facing_open and 'fold' in legal, is_fold)
        mark('steal', unopened and positions in ('4','3','SB') and can_raise, is_raise)
        # Infer the opener's position from the clockwise physical seat order
        # and *our known position*. Rotation is valid as eliminated seats vanish.
        opener = raises[0].get('pid') if len(raises)==1 else None
        opener_pos = None
        if opener is not None:
            indices = getattr(view,'seat_indices',None) or {}
            ordered = [pid for pid,_ in sorted(indices.items(),key=lambda t:t[1])]
            n = len(ordered)
            tags = position_labels(n)
            if opener in ordered and view.me in ordered and positions in tags:
                btn = (ordered.index(view.me)-tags.index(positions))%n
                opener_pos = tags[(ordered.index(opener)-btn)%n]
        prior_to_open = hist[:hist.index(raises[0])] if raises and raises[0] in hist else []
        true_unopened_raise = not any(e.get('type') in ('call','raise','bet','all_in') for e in prior_to_open)
        mark('fold_to_steal',
             facing_open and positions in ('SB','BB') and opener_pos in ('4','3','SB')
             and true_unopened_raise and 'fold' in legal,
             is_fold)
        called_after_raise = any(e.get('type')=='call' for e in hist[hist.index(raises[-1])+1:]) if raises and raises[-1] in hist else False
        mark('squeeze', facing_open and called_after_raise and can_raise, is_raise)
        return action

    def _called_barrel(self, history, street, hand_id):
        """Hero's qualifying prior barrel was called without a subsequent raise."""
        if (hand_id, street) not in self.postflop_cbet_hands:
            return False
        actions = [item for item in history if item.get('street') == street]
        me = getattr(self, 'player_id', None)
        first = next((i for i, item in enumerate(actions)
                      if item.get('pid') == me and item.get('type') == 'bet'), None)
        if first is None:
            return False
        after = actions[first + 1:]
        return (any(item.get('pid') != me and item.get('type') == 'call' for item in after)
                and not any(item.get('type') in ('raise', 'all_in') for item in after))

    def observe_postflop(self, view, action):
        street = getattr(view, 'street', None)
        if street not in ('flop', 'turn', 'river'):
            return
        kind = str(getattr(action, 'type', ''))
        legal = {item.get('type') for item in (getattr(view, 'legal_actions', None) or [])}
        if kind not in legal:
            kind = 'call' if 'call' in legal else 'check' if 'check' in legal else 'fold'
        hist = [h for h in (getattr(view, 'history', None) or [])
                if isinstance(h, dict)]
        street_hist = [h for h in hist if h.get('street') == street]
        hid = getattr(view, 'hand_id', None)
        me = getattr(view, 'me', None)
        key = (hid, street)
        position = self.hands.get(hid, {}).get('position')
        ledgers = [self.postflop_counts]
        if position is not None:
            ledgers.append(self.postflop_position_counts[position])
            ledgers.append(self.postflop_stage_counts[(position, self.hands[hid]['table_size'])])

        # Only the very first eligible decision on each street can start a
        # continuation bet. The previous barrel must have been called.
        if key not in self.postflop_seen:
            self.postflop_seen.add(key)
            can_open = 'bet' in legal and not any(
                h.get('type') in ('bet', 'raise', 'all_in') for h in street_hist)
            is_barrel = False
            if can_open and street == 'flop':
                pre = [h for h in hist if h.get('street') == 'preflop'
                       and h.get('type') in ('bet', 'raise', 'all_in')]
                is_barrel = bool(pre and pre[-1].get('pid') == me)
            elif can_open and street == 'turn':
                is_barrel = self._called_barrel(hist, 'flop', hid)
            elif can_open and street == 'river':
                is_barrel = self._called_barrel(hist, 'turn', hid)
            if is_barrel:
                field = street + '_cbet'
                for counts in ledgers:
                    counts[field + '_opp'] += 1
                    counts[field + '_n'] += int(kind == 'bet')
                    if street == 'flop':  # Legacy field maintained for older clients.
                        counts['cbet_opp'] += 1
                        counts['cbet_n'] += int(kind == 'bet')
                if kind == 'bet':
                    self.postflop_cbet_hands.add((hid, street))

        had_checked = any(h.get('pid') == me and h.get('type') == 'check' for h in street_hist)
        for counts in ledgers:
            if kind in ('bet', 'raise'):
                counts[street + '_aggressive'] += 1
            elif kind == 'call':
                counts[street + '_calls'] += 1
            if int(getattr(view, 'to_call', 0) or 0) > 0 and 'fold' in legal:
                counts['fold_to_bet_opp'] += 1
                counts['fold_to_bet_n'] += int(kind == 'fold')
            if had_checked and int(getattr(view, 'to_call', 0) or 0) > 0 and 'raise' in legal:
                counts['check_raise_opp'] += 1
                counts['check_raise_n'] += int(kind == 'raise')

    def observe_hand_end(self, hand_id, net, bb, showdown, winners):
        row = self.hands.get(hand_id)
        if row is None:
            return
        pid = row['pid']
        ledgers = [self.postflop_counts,
                   self.postflop_position_counts[row['position']],
                   self.postflop_stage_counts[(row['position'],row['table_size'])]]
        for counts in ledgers:
            counts['net_hands'] += 1
            counts['net_bb_units'] += net.get(pid, 0) / bb if bb else 0
            if pid in showdown:
                counts['wsd_opp'] += 1
                counts['wsd_n'] += int(pid in winners)

    def reset_memory(self):
        fn = getattr(self.inner,'reset_memory',None)
        if callable(fn):
            fn()


def run_one(task):
    import bots
    import run_tournament_stats as runner
    tournament_id,names,chips,sb,bb,escalate,max_hands,seed,seat_offset = task
    instances=[]
    old=runner.create_bot
    old_table=runner.make_table
    specs=[(f'P{i+1}',bot,None) for i,bot in enumerate(names)]
    # Rotate complete entries, preserving stable player identity.
    specs = specs[seat_offset % len(specs):] + specs[:seat_offset % len(specs)]
    def factory(name):
        # P1=profile aliases preserve independent seat statistics for identical policies.
        # The strategy implementation itself still receives the original profile.
        profile = name.split("=", 1)[1] if "=" in name else name
        bot=TrackedBot(bots.create_bot(profile),name)
        # The alias P<n>=strategy identifies the seat while preserving the strategy label.
        bot.player_id = next((pid for pid,typ,_ in specs if typ == name), None)
        instances.append(bot)
        return bot
    def table_factory(*args, **kwargs):
        table=old_table(*args, **kwargs)
        tracked_by_pid={specs[i][0]:instances[i] for i in range(len(instances))}
        def on_deal(hand_id, hole, pos_by_pid, table_size):
            for pid, cards in hole.items():
                observer=tracked_by_pid.get(pid)
                if observer is not None:
                    observer.observe_deal(hand_id, cards, pos_by_pid[pid], table_size)
        table.on_deal=on_deal
        def on_hand_end(hid, net, current_bb, showdown, winners):
            for observer in instances:
                observer.observe_hand_end(hid, net, current_bb, showdown, winners)
        table.on_hand_end=on_hand_end
        return table
    runner.create_bot=factory
    runner.make_table=table_factory
    try:
        result=runner.run_silent_tournament((specs,chips,sb,bb,escalate,max_hands,seed))
        timings = [
            {'bot': bot.name, 'street': street, **dict(stats)}
            for bot in instances
            for street, stats in bot.decision_timing.items()
        ]
        return (tournament_id, seed, seat_offset, result,
                [r for bot in instances for r in bot.hands.values()], timings,
                ([{'bot': bot.name, **dict(bot.postflop_counts)} for bot in instances]
                 + [{'bot': bot.name, 'position': pos, 'table_size': size, **dict(counts)}
                    for bot in instances
                    for (pos, size), counts in bot.postflop_stage_counts.items()]))
    finally:
        runner.create_bot=old
        runner.make_table=old_table


def csv_write(path,rows):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('w',newline='',encoding='utf-8-sig') as f:
        writer=csv.writer(f)
        writer.writerows(rows)




def tournament_report(tournament_results, names, requested, chips, sb, bb,
                      blind_increase_every, max_hands, seat_mode):
    """Prepare real tournament/placement/blind records. Never synthesize wins."""
    ids = {f'P{i+1}': bot for i, bot in enumerate(names)}
    bot_rows = defaultdict(lambda: {
        'wins': 0, 'positions': [], 'hands_survived': [], 'appearances': 0,
    })
    tournaments_csv = [[
        'tournament', 'seed', 'seat_offset', 'status', 'completed',
        'winner_pid', 'winner_bot', 'hands', 'blind_levels',
        'start_sb', 'start_bb', 'last_sb', 'last_bb',
    ]]
    players_csv = [[
        'tournament', 'pid', 'bot', 'position', 'hand_finished',
        'chips_at_finish', 'completed', 'status',
    ]]
    blinds_csv = [[
        'tournament', 'level', 'sb', 'bb', 'start_hand', 'end_hand', 'hands',
    ]]
    blind_totals = defaultdict(lambda: {'hands': 0, 'tournaments': set()})
    completed = 0
    total_hands = 0
    hand_counts = []
    all_wins = 0

    for tournament_id, seed, offset, result in sorted(tournament_results, key=lambda x: x[0]):
        status = result['status']
        is_complete = bool(result['completed'])
        winner = result['winner']
        hands = result['hand_count']
        stages = result['blind_stages']
        finish_order = result['finish_order']
        total_hands += hands
        hand_counts.append(hands)

        # Verify that each seat appears exactly once. Tournament results must
        # be tied to stable PIDs rather than the rotated physical seats.
        positions = {pid: (pos, hand, amount) for pid, pos, hand, amount in finish_order}
        if len(positions) != len(names) or set(positions) != set(ids) or len(finish_order) != len(names):
            raise RuntimeError(f'Tournament {tournament_id}: missing/duplicate player results')
        if sum(stage['hands'] for stage in stages) != hands:
            raise RuntimeError(f'Tournament {tournament_id}: blind stage hand count disagrees with engine')
        if is_complete:
            completed += 1
            all_wins += 1
            if winner not in ids or positions[winner][0] != 1:
                raise RuntimeError(f'Tournament {tournament_id}: invalid winner or first place')
            # Equal pre-hand stacks busted together share a rank; gaps in
            # competition ranks are legal (e.g. 1,2,2,4).
            places=sorted(pos for pos,_,_ in positions.values())
            if (places[0] != 1 or places[-1]>len(names)
                    or places.count(1)!=1 or any(pos<1 for pos in places)):
                raise RuntimeError(f'Tournament {tournament_id}: invalid finishing positions')
        elif winner is not None:
            raise RuntimeError(f'Tournament {tournament_id}: unfinished tournament claims a winner')

        first = stages[0] if stages else None
        last = stages[-1] if stages else None
        tournaments_csv.append([
            tournament_id, seed, offset, status, int(is_complete),
            winner or '', ids.get(winner, ''), hands, len(stages),
            first['sb'] if first else '', first['bb'] if first else '',
            last['sb'] if last else '', last['bb'] if last else '',
        ])
        for pid, bot in ids.items():
            pos, hand, amount = positions[pid]
            players_csv.append([
                tournament_id, pid, bot, pos, hand, amount,
                int(is_complete), status,
            ])
            stats = bot_rows[bot]
            stats['appearances'] += 1
            # Avoid reporting chip-based, provisional ranks as genuine places.
            if is_complete:
                stats['positions'].append(pos)
            stats['hands_survived'].append(hand)
        if is_complete:
            bot_rows[ids[winner]]['wins'] += 1
        for stage in stages:
            blinds_csv.append([
                tournament_id, stage['level'], stage['sb'], stage['bb'],
                stage['start_hand'], stage['end_hand'], stage['hands'],
            ])
            entry = blind_totals[(stage['sb'], stage['bb'])]
            entry['hands'] += stage['hands']
            entry['tournaments'].add(tournament_id)

    if len(tournament_results) != requested or all_wins != completed:
        raise RuntimeError('Tournament telemetry missing or completed wins mismatch')
    if sum(v['hands'] for v in blind_totals.values()) != total_hands:
        raise RuntimeError('Total blind-level hands do not match simulated hands')

    leaderboard_csv = [[
        'bot', 'wins', 'win_pct_completed', 'win_pct_all',
        'avg_position_completed', 'completed_appearances',
        'total_appearances', 'avg_hands_survived',
    ]]
    leaderboard = []
    for name in dict.fromkeys(names):
        stats = bot_rows[name]
        positions = stats['positions']
        survived = stats['hands_survived']
        row = {
            'bot': name,
            'wins': stats['wins'],
            'win_pct_completed': (100*stats['wins']/completed) if completed else None,
            'win_pct_all': 100*stats['wins']/requested,
            'avg_position_completed': sum(positions)/len(positions) if positions else None,
            'completed_appearances': len(positions),
            'total_appearances': stats['appearances'],
            'avg_hands_survived': sum(survived)/len(survived) if survived else None,
        }
        leaderboard.append(row)
    leaderboard.sort(key=lambda d: (-d['wins'], d['avg_position_completed'] or float('inf'), d['bot']))
    for row in leaderboard:
        leaderboard_csv.append([row[k] if row[k] is not None else '' for k in (
            'bot','wins','win_pct_completed','win_pct_all','avg_position_completed',
            'completed_appearances','total_appearances','avg_hands_survived')])

    blind_summary_csv = [['sb', 'bb', 'hands', 'tournaments_observed', 'pct_of_all_hands']]
    blind_summary = []
    for (small, big), stats in sorted(blind_totals.items(), key=lambda p:(p[0][1],p[0][0])):
        row = {
            'sb': small, 'bb': big, 'hands': stats['hands'],
            'tournaments_observed': len(stats['tournaments']),
            'pct_of_all_hands': 100*stats['hands']/total_hands if total_hands else 0,
        }
        blind_summary.append(row)
        blind_summary_csv.append(list(row.values()))

    report = {
        'source': 'run_silent_tournament (actual engine results)',
        'tournaments_requested': requested,
        'tournaments_completed': completed,
        'tournaments_unfinished': requested-completed,
        'wins_total': all_wins,
        'total_hands': total_hands,
        'mean_hands_per_tournament': total_hands/requested,
        'min_hands_per_tournament': min(hand_counts),
        'max_hands_per_tournament': max(hand_counts),
        'initial_chips_per_player': chips,
        'initial_blinds': {'sb': sb, 'bb': bb},
        'blind_increase_every_hands': blind_increase_every,
        'max_hands_per_tournament': max_hands,
        'seat_mode': seat_mode,
        'button_policy':os.environ.get("POKER_BUTTON_POLICY","moving"),
        'leaderboard': leaderboard,
        'blind_summary': blind_summary,
        'notes': [
            'Wins are awarded only when exactly one seat remains with chips.',
            'Average finishing position excludes unfinished tournaments; provisional ranks are retained in the raw player results with completed=0.',
            'Win percentage is calculated per completed tournament; win_pct_all uses all requested tournaments.',
            'Blind-level hands reflect actual SB/BB supplied to every completed hand by the engine.',
        ],
    }
    return report, {
        'tournaments.csv': tournaments_csv,
        'tournament_players.csv': players_csv,
        'leaderboard.csv': leaderboard_csv,
        'blind_levels.csv': blinds_csv,
        'blind_summary.csv': blind_summary_csv,
    }


def summarize_bot_timings(timing_records, names):
    """Aggregate observed strategy-call timing; never infer from hand counts.

    Input records are emitted by each worker. CPU time is thread CPU ns and
    represents *only* inner.act(view). A decision is one bot.act invocation,
    not one dealt hand. Postflop covers flop, turn and river.
    """
    by_street = defaultdict(lambda: {
        'decisions': 0, 'cpu_ns': 0, 'wall_ns': 0,
        'max_cpu_ns': 0, 'max_wall_ns': 0,
    })
    for row in timing_records:
        key = (row['bot'], row['street'])
        if row['street'] not in ('preflop', 'postflop'):
            raise RuntimeError(f'Unexpected timing street: {row["street"]!r}')
        dest = by_street[key]
        for field in ('decisions', 'cpu_ns', 'wall_ns'):
            if row[field] < 0:
                raise RuntimeError(f'Negative strategy timing: {field}')
            dest[field] += row[field]
        for field in ('max_cpu_ns', 'max_wall_ns'):
            dest[field] = max(dest[field], row[field])

    def measured(bot, street, vals):
        count = vals['decisions']
        cpu_ns = vals['cpu_ns']
        wall_ns = vals['wall_ns']
        return {
            'bot': bot,
            'street': street,
            'decisions': count,
            'cpu_seconds': round(cpu_ns / 1e9, 9),
            'wall_seconds': round(wall_ns / 1e9, 9),
            'mean_cpu_ms': round(cpu_ns / count / 1e6, 6) if count else None,
            'mean_wall_ms': round(wall_ns / count / 1e6, 6) if count else None,
            'max_cpu_ms': round(vals['max_cpu_ns'] / 1e6, 6) if count else None,
            'max_wall_ms': round(vals['max_wall_ns'] / 1e6, 6) if count else None,
            'decisions_per_cpu_second': round(count * 1e9 / cpu_ns, 2) if cpu_ns else None,
        }

    street_rows = []
    summary_rows = []
    for name in dict.fromkeys(names):
        sum_vals = {field: 0 for field in ('decisions', 'cpu_ns', 'wall_ns')}
        sum_vals.update({'max_cpu_ns': 0, 'max_wall_ns': 0})
        for street in ('preflop', 'postflop'):
            vals = by_street[(name, street)]
            street_rows.append(measured(name, street, vals))
            for field in ('decisions', 'cpu_ns', 'wall_ns'):
                sum_vals[field] += vals[field]
            for field in ('max_cpu_ns', 'max_wall_ns'):
                sum_vals[field] = max(sum_vals[field], vals[field])
        row = measured(name, 'all', sum_vals)
        row['preflop_decisions'] = by_street[(name, 'preflop')]['decisions']
        row['postflop_decisions'] = by_street[(name, 'postflop')]['decisions']
        summary_rows.append(row)

    all_cpu_ns = sum(sum(x['cpu_ns'] for x in (by_street[(name, s)]
                     for s in ('preflop', 'postflop'))) for name in dict.fromkeys(names))
    for row in summary_rows:
        row['share_decision_cpu_pct'] = (
            round(row['cpu_seconds'] * 1e9 / all_cpu_ns * 100, 3)
            if all_cpu_ns else None
        )
    summary_rows.sort(key=lambda x: (-x['cpu_seconds'], x['bot']))

    csv_summary_fields = [
        'bot', 'decisions', 'preflop_decisions', 'postflop_decisions',
        'cpu_seconds', 'wall_seconds', 'mean_cpu_ms', 'mean_wall_ms',
        'max_cpu_ms', 'max_wall_ms', 'decisions_per_cpu_second',
        'share_decision_cpu_pct',
    ]
    csv_street_fields = [
        'bot', 'street', 'decisions', 'cpu_seconds', 'wall_seconds',
        'mean_cpu_ms', 'mean_wall_ms', 'max_cpu_ms', 'max_wall_ms',
        'decisions_per_cpu_second',
    ]
    def csv_table(fields, rows):
        return [fields] + [[r[field] if r[field] is not None else '' for field in fields]
                           for r in rows]
    total_decisions = sum(x['decisions'] for x in summary_rows)
    return {
        'source': 'TrackedBot.inner.act(view) measured in tournament worker thread',
        'units': 'CPU and wall seconds are sums of per-decision durations, not tournament wall time',
        'timing_method': 'time.thread_time_ns + time.perf_counter_ns',
        'total_decisions': total_decisions,
        'total_bot_decision_cpu_seconds': round(all_cpu_ns / 1e9, 9),
        'bots': summary_rows,
        'by_street': street_rows,
        'notes': [
            'An action is one call to the underlying bot strategy, not one dealt hand.',
            'CPU seconds is time spent executing strategy calls on their own threads, aggregated across parallel workers.',
            'Wall seconds is summed per-call latency; it can include OS scheduling delays and may exceed CPU seconds.',
            'Other costs (engine, card evaluation, view construction, preflop observation, file export) are excluded.',
            'Postflop combines flop, turn and river. Timing adds slight measurement overhead.',
            'decisions_per_cpu_second divides decision calls by their accumulated strategy CPU time, not overall simulation time.',
        ],
    }, {
        'bot_decision_timing.csv': csv_table(csv_summary_fields, summary_rows),
        'bot_decision_timing_by_street.csv': csv_table(csv_street_fields, street_rows),
    }


def write_json(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')

# Approved prior revision (same tournament engine, only export aggregation changed).
# This precise digest allows completed 450-tournament checkpoints to be resumed
# after the memory fix; any other historical source is rejected.
LEGACY_EXPORTER_SHA256 = "c95b365dd2af4051db541b27781b94e9ccbd113477ca6c3740fcbd6c9b5d40b2"


def checkpoint_config_key(args, names, source_sha256=None):
    """Bind checkpoints to exact experiment settings and an audited source."""
    payload = {
        "version": 1, "players": names, "tournaments": args.tournaments,
        "seed": args.seed, "chips": args.chips, "sb": args.sb, "bb": args.bb,
        "blind_increase_every": args.blind_increase_every, "max_hands": args.max_hands,
        "seat_mode": args.seat_mode,
        "source_sha256": source_sha256 or hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


def task_checkpoint(task, checkpoint_dir, config_key):
    """Read a completed tournament or safely run/checkpoint exactly this task."""
    tournament_id = task[0]
    path = checkpoint_dir / f"{tournament_id:06d}.json.gz"
    if path.exists():
        try:
            with gzip.open(path, "rt", encoding="utf-8") as stream:
                data = json.load(stream)
            if data.get("config_key") == config_key and data.get("task") == json.loads(json.dumps(task)):
                return data["result"]
        except (OSError, EOFError, ValueError, KeyError):
            path.unlink(missing_ok=True)
    # Reserve space for the HTTP runner's job.json and simulation logs.
    # On a small Railway volume, refuse a new checkpoint before exhausting it.
    reserve = 24 * 1024 * 1024
    free_before = shutil.disk_usage(checkpoint_dir).free
    if free_before < reserve:
        raise RuntimeError(
            f"Railway /data: свободно {free_before//1048576} МБ. "
            "Требуется резерв 24 МБ. Чекпойнты сохранены: "
            "освободи место через управление хранилищем или увеличь том."
        )
    result = run_one(task)
    payload = {"config_key": config_key, "task": task, "result": result}
    temporary = path.with_suffix(".partial")
    try:
        free = shutil.disk_usage(checkpoint_dir).free
        if free < reserve:
            raise RuntimeError(
                f"Railway /data: осталось {free//1048576} МБ перед записью "
                "чекпойнта; выполнение остановлено, чтобы не потерять журнал."
            )
        with gzip.open(temporary, "wt", encoding="utf-8", compresslevel=6) as stream:
            json.dump(payload, stream, ensure_ascii=False, separators=(",", ":"))
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return result


def main():
    p=argparse.ArgumentParser(description='Poker A17: full preflop action frequency export')
    p.add_argument('--players',default=DEFAULT_BOTS)
    p.add_argument('--tournaments',type=int,default=200)
    p.add_argument('--parallel',type=int,default=2)
    p.add_argument('--seed',type=int,default=42)
    p.add_argument('--chips',type=int,default=500)
    p.add_argument('--sb',type=int,default=1)
    p.add_argument('--bb',type=int,default=2)
    p.add_argument('--blind-increase-every',type=int,default=50)
    p.add_argument('--max-hands',type=int,default=10000)
    p.add_argument('--out',default='ranges_200_v4_numeric')
    p.add_argument('--checkpoint-dir',default='',help='Durable per-tournament JSON/GZIP checkpoints for safe resume')
    p.add_argument('--button-policy',choices=['dead_button','moving'],
                   default='dead_button',help='Tournament BTN/SB/BB policy')
    p.add_argument('--seat-mode',choices=['rotate','fixed'],default='rotate',
                   help='Rotate starting seats each tournament (default), or retain historical fixed seating')
    a=p.parse_args()
    os.environ["POKER_BUTTON_POLICY"]=a.button_policy
    if os.environ.get('THAI_ENGINE_IMPL', '').lower() != 'legacy':
        p.error('v4 requires THAI_ENGINE_IMPL=legacy: only legacy supports on_deal observation.')
    names=[n.strip() for n in a.players.split(',') if n.strip()]
    if not 2<=len(names)<=10 or a.tournaments<1 or a.parallel<1:
        p.error('Expected 2..10 players, >=1 tournaments and >=1 parallel workers')
    start_time = time.perf_counter()
    tasks=[(i+1,names,a.chips,a.sb,a.bb,a.blind_increase_every,a.max_hands,a.seed+i,
            i%len(names) if a.seat_mode=='rotate' else 0) for i in range(a.tournaments)]
    print(f'Initial seating: {a.seat_mode} · {len(names)} seats · {a.tournaments} tournaments',flush=True)
    checkpoint_dir = Path(a.checkpoint_dir) if a.checkpoint_dir else None
    config_key = checkpoint_config_key(a, names)
    if checkpoint_dir:
        checkpoint_dir.mkdir(parents=True, exist_ok=True)
        meta_file = checkpoint_dir / "config.json"
        if meta_file.exists():
            stored = json.loads(meta_file.read_text(encoding="utf-8"))
            if stored.get("config_key") != config_key:
                # Explicitly allow only the verified pre-aggregation-fix exporter.
                # Each per-tournament checkpoint still has to match this config
                # key AND the full task tuple before any result is reused.
                legacy_key = checkpoint_config_key(a, names, LEGACY_EXPORTER_SHA256)
                if stored.get("config_key") == legacy_key:
                    config_key = legacy_key
                    print("[resume] Compatible legacy checkpoint version verified; using memory-safe export",flush=True)
                else:
                    p.error("Checkpoint configuration or exporter source version changed; use a new session")
        else:
            meta_file.write_text(json.dumps({"config_key": config_key, "version": 1}, indent=2), encoding="utf-8")
        cached = len(list(checkpoint_dir.glob("*.json.gz")))
        if cached:
            print(f'[resume] Found {cached} per-tournament checkpoints; verifying before reuse', flush=True)
    all_counts=defaultdict(lambda:defaultdict(int))
    total_hands=0
    results=[]
    decision_records=[]
    postflop_aggregate=defaultdict(lambda:defaultdict(float))
    def ingest(result):
        nonlocal total_hands
        tournament_id, seed, seat_offset, outcome, rows, bot_timings, postflop=result
        decision_records.extend(bot_timings)
        for item in postflop:
            key=(item['bot'],item.get('position'),item.get('table_size'))
            total=postflop_aggregate[key]
            for field,value in item.items():
                if field not in ('bot','position','table_size'):
                    total[field]+=value
        results.append((tournament_id, seed, seat_offset, outcome))
        total_hands+=outcome['hand_count']
        for row in rows:
            key=(row['bot'],row['position'],row['hand'],row['table_size'])
            for field in COUNT_FIELDS:
                all_counts[key][field]+=row[field]

    if a.parallel==1:
        for i,task in enumerate(tasks,1):
            ingest(task_checkpoint(task, checkpoint_dir, config_key) if checkpoint_dir else run_one(task))
            if i%max(1,a.tournaments//10)==0 or i==a.tournaments:
                elapsed=max(time.perf_counter()-start_time, 1e-9)
                print(f'{i}/{a.tournaments} tournaments · {60*i/elapsed:.1f} tournaments/min · {total_hands/elapsed:.1f} hands/s',flush=True)
    else:
        with ProcessPoolExecutor(max_workers=a.parallel) as ex:
            futures=[ex.submit(task_checkpoint, t, checkpoint_dir, config_key)
                     if checkpoint_dir else ex.submit(run_one, t) for t in tasks]
            for i,f in enumerate(as_completed(futures),1):
                ingest(f.result())
                if i%max(1,a.tournaments//10)==0 or i==a.tournaments:
                    elapsed=max(time.perf_counter()-start_time, 1e-9)
                    print(f'{i}/{a.tournaments} tournaments · {60*i/elapsed:.1f} tournaments/min · {total_hands/elapsed:.1f} hands/s',flush=True)

    simulation_seconds = time.perf_counter()-start_time
    report, report_tables = tournament_report(
        results, names, a.tournaments, a.chips, a.sb, a.bb,
        a.blind_increase_every, a.max_hands, a.seat_mode)
    if total_hands != report['total_hands']:
        raise RuntimeError('Preflop hand count differs from tournament telemetry')
    bot_report, bot_tables = summarize_bot_timings(decision_records, names)
    # Keep only one output scope in RAM. The previous implementation built
    # 9 scopes at once, multiplying ~169 x positions x bots x dimensions
    # in a dictionary right after 100% of tournaments had finished.
    # With 450+ tournaments on 1 GiB Railway this could exhaust memory.
    output=Path(a.out)
    metric_columns=[]
    for m,base in METRICS.items():
        if f'{m}_n' not in metric_columns:
            metric_columns.append(f'{m}_n')
        if base!='hands_observed' and base not in metric_columns:
            metric_columns.append(base)
        metric_columns.append(f'{m}_pct')
    headers=['bot','position','hand','combos','hands_observed']+metric_columns
    scopes = ['all'] + [f'n{n}' for n in range(2, len(names) + 1)]
    all_totals = {}
    for scope in scopes:
        print(f'[export] Writing {scope} summary and hand tables',flush=True)
        agg=defaultdict(lambda:defaultdict(int))
        for (bot,pos,hand,n), counts in all_counts.items():
            if scope!='all' and scope!=f'n{n}':
                continue
            for h in (hand,'*'):
                for position in (pos,'ALL'):
                    row=agg[(bot,position,h)]
                    for f,v in counts.items():
                        row[f]+=v
        def formatted(bot,pos,hand):
            c=agg.get((bot,pos,hand),{})
            row=[bot,pos,hand,combos(hand) if hand!='*' else '',c.get('hands_observed',0)]
            vals=[]
            for col in metric_columns:
                if col.endswith('_pct'):
                    metric=col[:-4]
                    den=c.get(METRICS[metric],0)
                    vals.append(round(100*c.get(metric+'_n',0)/den,2) if den else '')
                else:
                    vals.append(c.get(col,0))
            return row+vals
        positions = POSITIONS if scope=='all' else tuple(position_labels(int(scope[1:])))
        # Stream rows to disk; never create a list of tens of thousands of rows.
        csv_write(output/f'by_hand_position_169_{scope}.csv',
                  itertools.chain([headers],(formatted(bot,pos,h)
                       for bot in names for pos in positions for h in class_grid())))
        csv_write(output/f'by_hand_169_{scope}.csv',
                  itertools.chain([headers],(formatted(bot,'ALL',h)
                       for bot in names for h in class_grid())))
        csv_write(output/f'summary_{scope}.csv',
                  itertools.chain([headers],(formatted(bot,'ALL','*') for bot in names)))
        if scope=='all':
            all_totals={name:dict(agg.get((name,'ALL','*'),{})) for name in names}
        csv_write(output/f'summary_position_{scope}.csv',
                  itertools.chain([headers],(formatted(bot,pos,'*')
                      for bot in names for pos in positions)))
        del agg
        gc.collect()
    print('[export] Hand tables completed, preparing postflop summaries',flush=True)
    post_agg = defaultdict(lambda: defaultdict(float))
    post_agg_pos = defaultdict(lambda: defaultdict(float))
    post_agg_stage = defaultdict(lambda: defaultdict(float))
    for (name, position, size), item in postflop_aggregate.items():
        dest = post_agg[name] if position is None else post_agg_stage[(name, position, size)]
        for key,value in item.items():
            dest[key] += value
            if position is not None:
                post_agg_pos[(name, position)][key] += value
    post_fields = ('flop_af','turn_af','river_af','flop_cbet','turn_cbet',
                   'river_cbet','cbet','fold_to_bet','check_raise','wsd','net_bb_100')
    raw_fields = tuple(field for street in ('flop','turn','river')
                       for field in (street+'_aggressive',street+'_calls',
                                     street+'_cbet_n',street+'_cbet_opp')) + (
        'cbet_n','cbet_opp','fold_to_bet_n','fold_to_bet_opp',
        'check_raise_n','check_raise_opp','wsd_n','wsd_opp',
        'net_bb_units','net_hands')

    def pf_metrics(c):
        result={}
        for street in ('flop','turn','river'):
            calls=c[street+'_calls']
            result[street+'_af'] = round(c[street+'_aggressive']/calls,4) if calls else None
        for metric in ('flop_cbet','turn_cbet','river_cbet','cbet',
                       'fold_to_bet','check_raise','wsd'):
            denom=c[metric+'_opp']
            result[metric] = round(100*c[metric+'_n']/denom,4) if denom else None
        result['net_bb_100'] = round(100*c['net_bb_units']/c['net_hands'],4) if c['net_hands'] else None
        return result

    def post_record(name, c, position=None, table_size=None):
        metrics=pf_metrics(c)
        prefix=[name] if position is None else [name,position]
        if table_size is not None:
            prefix.append(table_size)
        return prefix + [metrics[m] if metrics[m] is not None else '' for m in post_fields] + [
            c[f] for f in raw_fields]

    csv_write(output/'postflop_summary.csv',
              itertools.chain([['bot']+list(post_fields)+list(raw_fields)],
                              (post_record(name,post_agg[name]) for name in names)))
    csv_write(output/'postflop_position_summary.csv',
              itertools.chain([['bot','position']+list(post_fields)+list(raw_fields)],
                              (post_record(name,post_agg_pos[(name,pos)],pos)
                               for name in names for pos in POSITIONS)))
    csv_write(output/'postflop_position_stage_summary.csv',
              itertools.chain([['bot','position','table_size']+list(post_fields)+list(raw_fields)],
                              (post_record(name,post_agg_stage[(name,pos,n)],pos,n)
                               for name in names for n in range(2,len(names)+1)
                               for pos in position_labels(n))))
    for filename, table_rows in {**report_tables, **bot_tables}.items():
        csv_write(output/filename, table_rows)
    write_json(output/'tournament_report.json', report)
    write_json(output/'bot_decision_timing.json', bot_report)
    total_seconds = time.perf_counter()-start_time
    performance = {
        'tournaments': a.tournaments,
        'completed_tournaments': report['tournaments_completed'],
        'total_hands': total_hands,
        'parallel_workers': a.parallel,
        'simulation_wall_seconds': round(simulation_seconds, 6),
        'total_wall_seconds': round(total_seconds, 6),
        'tournaments_per_minute': round(60*a.tournaments/total_seconds, 3),
        'hands_per_second': round(total_hands/total_seconds, 3),
        'simulation_tournaments_per_minute': round(60*a.tournaments/simulation_seconds, 3) if simulation_seconds else None,
        'simulation_hands_per_second': round(total_hands/simulation_seconds, 3) if simulation_seconds else None,
        'avg_wall_seconds_per_tournament': round(total_seconds/a.tournaments, 6),
        'bot_decisions_total': bot_report['total_decisions'],
        'bot_decisions_cpu_seconds': bot_report['total_bot_decision_cpu_seconds'],
        'notes': ['Wall seconds include simulation and CSV export; parallel per-tournament elapsed time is not measured here.', 'Per-bot decision CPU time is instrumented independently within strategy calls; see bot_decision_timing.json.'],
    }
    write_json(output/'performance.json', performance)
    (output/'metadata.json').write_text(json.dumps({
        'version':4,'source':'export_preflop_ranges_v4.py','position_scheme':'numeric','seat_mode':a.seat_mode,
        'button_policy':a.button_policy,
        'seating':{'method':'cyclic_shift','cycle':len(names),'fixed_seat_mode_supported':True},
        'tournaments':a.tournaments,
        'total_hands':total_hands,'seed':a.seed,'players':names,'scopes':scopes,
        'metrics':METRICS,
        'telemetry_files':['tournaments.csv','tournament_players.csv','leaderboard.csv','blind_levels.csv','blind_summary.csv','tournament_report.json','performance.json','bot_decision_timing.csv','bot_decision_timing_by_street.csv','bot_decision_timing.json','postflop_summary.csv',
                           'summary_position_all.csv','postflop_position_summary.csv',
                           'postflop_position_stage_summary.csv',
                           'summary_position_n2.csv (and up to player count)'],
        'notes':['Every dealt hand counts in hands_observed, including BB pots won without a decision; other opportunity counters require an action.',
                 'A missing opportunity displays an empty percentage, never 0%.',
                 'Fold-to-steal uses numeric positions 4,3,SB (cutoff, button, small blind).',
                 'Tournament starting seating rotates by one physical seat per tournament when seat_mode=rotate.',
                 'n9 includes only hands starting with nine active seats; n2 is heads-up (SB is button); all includes every stage.',
                 'Denominator hands_observed includes every player receiving hole cards, even if no preflop action was required.',
                 'Postflop AF is (bets+raises)/calls; a zero-call sample has undefined AF and is blank.',
                 'Flop C-bet: last preflop aggressor at first available unraised flop decision. Turn and river barrels require the immediately previous qualifying barrel to be called without a raise.',
                 'Street C-bet opportunities require a legal bet; all-in players cannot receive new opportunities. Fold to bet and Check-raise use eligible decisions.',
                 'W$SD credits a player winning a showdown side pot, including ties.',
                 'Net bb/100 is whole-hand net chips normalized by BB at each deal, times 100 / dealt hands; not isolated postflop EV.']
    },ensure_ascii=False,indent=2),encoding='utf-8')
    print(f'\nTotal simulated hands: {total_hands}')
    print('BOT                    HANDS   VPIP%    PFR%    RFI%  3BET%  4BET%')
    for name in names:
        c=all_totals.get(name,{})
        def pc(m):
            base=c.get(METRICS[m],0)
            return f'{100*c.get(m+"_n",0)/base:6.1f}' if base else '     —'
        print(f'{name:<22}{c.get("hands_observed",0):>7}  {pc("vpip")}  {pc("pfr")}  {pc("rfi")}  {pc("threebet")}  {pc("fourbet")}')
    print('\nTOURNAMENT RESULTS (actual winner, completed only)')
    print(f'Completed: {report["tournaments_completed"]}/{a.tournaments} · '
          f'Unfinished: {report["tournaments_unfinished"]} · '
          f'Wins recorded: {report["wins_total"]}')
    print(f'{"BOT":<23}{"WINS":>6}{"WIN%":>9}{"AVG POS":>11}')
    for row in report['leaderboard']:
        pct=f'{row["win_pct_completed"]:.1f}%' if row['win_pct_completed'] is not None else '—'
        avg=f'{row["avg_position_completed"]:.2f}' if row['avg_position_completed'] is not None else '—'
        print(f'{row["bot"]:<23}{row["wins"]:>6}{pct:>9}{avg:>11}')
    print(f'\nBLINDS: {a.sb}/{a.bb} initial · escalates every {a.blind_increase_every} hands')
    print(f'{"SB/BB":<16}{"HANDS":>10}{"TOURNAMENTS":>15}')
    for stage in report['blind_summary']:
        print(f'{str(stage["sb"])+"/"+str(stage["bb"]):<16}{stage["hands"]:>10}{stage["tournaments_observed"]:>15}')
    print('\nBOT DECISION SPEED (strategy calls only; thread CPU time)')
    print(f'{"BOT":<23}{"CALLS":>9}{"CPU SEC":>11}{"AVG MS":>11}{"MAX MS":>11}{"CALLS/S":>12}{"CPU%":>8}')
    for row in bot_report['bots']:
        speed = f'{row["decisions_per_cpu_second"]:,.0f}' if row['decisions_per_cpu_second'] is not None else '—'
        avg = f'{row["mean_cpu_ms"]:.4f}' if row['mean_cpu_ms'] is not None else '—'
        max_cpu = f'{row["max_cpu_ms"]:.4f}' if row['max_cpu_ms'] is not None else '—'
        share = f'{row["share_decision_cpu_pct"]:.1f}%' if row['share_decision_cpu_pct'] is not None else '—'
        print(f'{row["bot"]:<23}{row["decisions"]:>9}{row["cpu_seconds"]:>11.6f}'
              f'{avg:>11}{max_cpu:>11}{speed:>12}{share:>8}')
    print('Calls/s = strategy calls per CPU second (not hands/s). Preflop vs postflop: bot_decision_timing_by_street.csv')
    print(f'\nPERFORMANCE: {performance["total_wall_seconds"]:.2f}s overall · '
          f'{performance["tournaments_per_minute"]:.1f} tournaments/min · '
          f'{performance["hands_per_second"]:.1f} hands/s')
    print('Files:',output.resolve())


if __name__=='__main__':
    main()
