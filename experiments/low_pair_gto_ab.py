#!/usr/bin/env python3
"""Controlled paired-deal A/B study: GTO V1 vs corrected small-pocket-pair reads.

NOT production policy. The controlled change is ONLY to interpret pocket
22-66 + paired board + exactly two pair as weak showdown strength rather than
"monster". Every other GTO frequency and sizing remains V1. This avoids
mistaking AA on board plus 55 in hole for a value monster.

Chip EV comes from the same full Table engine as /api/plan/postflop.
All cards, opponents, hole combos and runouts are paired, per case.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
import random
import statistics
from unittest.mock import patch

from bots.postflop_profiles import (
    PostflopProfileBot, read_hand, _to_call, _fallthrough, _amount,
    _opponents, _can_bluff, _in_position,
)
import planner_equity as eq
import planner_postflop_ev as ev

LOW = ("22", "33", "44", "55", "66")


class GtoSmallPairCorrected(PostflopProfileBot):
    """Only the erroneous paired-board pocket-two-pair branch differs from V1."""

    def __init__(self):
        super().__init__("gto_postflop_v1")

    def act(self, view):
        cards = list(view.hole_cards or ())
        board = list(view.board or ())
        if len(cards) != 2 or len(board) < 3 or cards[0][0] != cards[1][0] or cards[0][0] not in "23456":
            return super().act(view)
        read = read_hand(cards, board)
        counts = Counter(c[0] for c in board)
        if read.category != 2 or not any(v >= 2 for v in counts.values()):
            return super().act(view)
        # Pair on table plus weak pocket pair = usually very weak two pair;
        # do NOT treat as a full house, trips, or other strong value.
        call = _to_call(view)
        if call > 0:
            price = call / max(1, int(view.pot) + call)
            return _fallthrough(view, fold=price > 0.14)
        if view.street != "river":
            multi = 1 / (1 + .55 * max(0, _opponents(view)-1))
            if random.random() < .09 * multi:
                wet = read.wet
                size = .66 if view.street == "flop" and wet else .33 if view.street == "flop" else .72
                bet = _amount(view, size)
                if bet is not None:
                    return bet
        return _fallthrough(view)


class _Trace:
    def __init__(self, bot, tally):
        self.bot, self.tally = bot, tally

    def act(self, view):
        action = self.bot.act(view)
        if view.street in ("flop", "turn", "river"):
            hole = list(view.hole_cards or ())
            if len(hole) == 2 and hole[0][0] == hole[1][0] and hole[0][0] in "23456":
                board = list(view.board or ())
                read = read_hand(hole, board)
                bp = any(v >= 2 for v in Counter(c[0] for c in board).values())
                if read.category == 2 and bp:
                    label = "paired_board_two_pair"
                elif read.category >= 3 and hole[0][0] in {x[0] for x in board}:
                    label = "set_or_better"
                elif read.made == "weak_pair":
                    label = "underpair"
                elif read.made == "top_pair":
                    label = "overpair"
                else:
                    label = read.made
                self.tally[(view.street, label, action.type)] += 1
        return action


def opponent(profile, position, postflop):
    return {"profile": profile, "position": position, "scenario": "rfi",
            "players": 9, "selector": "active", "entry_mode": "always",
            "entry_pct": 100, "postflop": postflop}


SCENARIOS = {
    "HU_TAG_tight": [opponent("builtin:pc_gto_80bb", "9", "tag")],
    "HU_LAG_wide": [opponent("builtin:any_two", "9", "lag")],
    "Multiway_TAG_LAG": [
        opponent("builtin:pc_gto_80bb", "9", "tag"),
        opponent("builtin:any_two", "4", "lag"),
    ],
}


def run_case(picked, board, version, trace, seed):
    original_policy = ev._Policy

    def factory(kind, pos, hero=False):
        item = original_policy(kind, pos, hero=hero)
        if hero:
            bot = (GtoSmallPairCorrected() if version == "corrected" else
                   PostflopProfileBot("gto_postflop_v1"))
            item.postflop = _Trace(bot, trace)
        return item

    random.seed(seed)
    with patch.object(ev, "_Policy", side_effect=factory):
        return ev._play_case(picked, board, "gto", "3", 20, seed)


def ci95(deltas):
    n = len(deltas)
    if n < 2: return 0.
    return 1.96 * statistics.stdev(deltas) / math.sqrt(n)


def sampled_flop_state(picked, board):
    if any(v >= 2 for v in Counter(c[0] for c in board[:3]).values()):
        r = read_hand([ev._card(c) for c in picked[0][1]],
                      [ev._card(c) for c in board[:3]])
        if r.category == 2:
            return "paired_board_two_pair"
    r = read_hand([ev._card(c) for c in picked[0][1]],
                  [ev._card(c) for c in board[:3]])
    if r.category >= 3: return "set_or_better"
    if r.made == "weak_pair": return "underpair"
    if r.made == "top_pair": return "overpair"
    return r.made


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=700)
    args = parser.parse_args()
    if not 100 <= args.samples <= 3000: raise SystemExit("Need 100-3000 samples")

    summary = {}
    for scname, specs in SCENARIOS.items():
        ranges, _ = eq.build_ranges(specs, "selected")
        for hand in LOW:
            identity = f"smallpocket-AB-v1:{scname}:{hand}:{args.samples}"
            rng = random.Random(int(hashlib.sha256(identity.encode()).hexdigest()[:16],16))
            baseline, corrected, differences = [], [], []
            per_state = defaultdict(list)
            trials = {"baseline": Counter(), "corrected": Counter()}
            states=Counter()
            for _ in range(args.samples):
                picked, board = ev._draw_case(hand, ranges, specs, rng)
                kind = sampled_flop_state(picked, board)
                states[kind] += 1
                seed = rng.randrange(1 << 50)
                old, _ = run_case(picked, board, "baseline", trials["baseline"], seed)
                new, _ = run_case(picked, board, "corrected", trials["corrected"], seed)
                baseline.append(old)
                corrected.append(new)
                differences.append(new-old)
                per_state[kind].append(new-old)
            row = {
                "scenario": scname, "hand": hand, "n": len(differences),
                "ev_old": round(statistics.mean(baseline),4),
                "ev_corrected": round(statistics.mean(corrected),4),
                "delta_bb": round(statistics.mean(differences),4),
                "delta_95ci_halfwidth": round(ci95(differences),4),
                "state_counts": dict(states),
                "delta_by_flop_type": {
                    k: {"n":len(v), "delta_bb":round(statistics.mean(v),4),
                        "ci95":round(ci95(v),4)}
                    for k,v in sorted(per_state.items())
                },
                "paired_board_flop_actions": {
                    arm: {"/".join(k):v for k,v in sorted(counts.items())
                          if k[0]=="flop" and k[1]=="paired_board_two_pair"}
                    for arm,counts in trials.items()
                },
            }
            summary[f"{scname} {hand}"] = row
            print("RESULT "+json.dumps(row,sort_keys=True,ensure_ascii=False),flush=True)
    for scname in SCENARIOS:
        rows=[v for v in summary.values() if v["scenario"]==scname]
        print("SUMMARY "+json.dumps({
            "scenario": scname, "samples": sum(x["n"] for x in rows),
            "mean_of_5_class_delta_bb": round(statistics.mean(x["delta_bb"] for x in rows),4),
            "per_hand": {x["hand"]:x["delta_bb"] for x in rows}
        },ensure_ascii=False),flush=True)

    # Diagnostic check: intervention should actually affect paired-board
    # decisions in at least some cases. Do not assert improvement by design.
    found=sum(sum(x["paired_board_flop_actions"][arm].values())
              for x in summary.values() for arm in ("baseline","corrected"))
    if not found: raise AssertionError("No paired-board low-pocket-pair samples")
    print("STUDY_COMPLETE "+str(len(summary))+" subgroups",flush=True)


if __name__=="__main__":
    main()
