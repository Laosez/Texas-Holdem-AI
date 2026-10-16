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

    def __init__(self,style="corrected"):
        super().__init__("gto_postflop_v1")
        if style not in ("corrected","bluffcatch","probe"):raise ValueError(style)
        self.style=style

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
        n = _opponents(view)
        if call > 0:
            price=call / max(1,int(view.pot)+call)
            limit=(.30 if self.style=="bluffcatch" and n==1 else
                   .24 if self.style=="probe" and n==1 else .14)
            return _fallthrough(view,fold=price>limit)
        if view.street!="river":
            multi=1/(1+.55*max(0,n-1))
            frequency=.35 if self.style=="probe" and n==1 else .09
            if random.random()<frequency*multi:
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
            bot = (GtoSmallPairCorrected(version) if version!="baseline" else
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
    if any(v >= 2 for v in Counter(ev._card(c)[0] for c in board[:3]).values()):
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
            baseline=[]
            versions=("corrected","bluffcatch","probe")
            values={k:[] for k in versions}
            deltas={k:[] for k in versions}
            state_counter=Counter()
            by_state={k:defaultdict(list) for k in versions}
            action_counter={k:Counter() for k in ("baseline",*versions)}
            for _ in range(args.samples):
                picked,board=ev._draw_case(hand,ranges,specs,rng)
                state=sampled_flop_state(picked,board)
                state_counter[state]+=1
                seed=rng.randrange(1<<50)
                old,_=run_case(picked,board,"baseline",action_counter["baseline"],seed)
                baseline.append(old)
                for name in versions:
                    new,_=run_case(picked,board,name,action_counter[name],seed)
                    values[name].append(new)
                    deltas[name].append(new-old)
                    by_state[name][state].append(new-old)
            row={
              "scenario":scname,"hand":hand,"n":args.samples,
              "ev_old":round(statistics.mean(baseline),4),
              "variants":{
                 k:{"ev":round(statistics.mean(values[k]),4),
                    "delta_bb":round(statistics.mean(deltas[k]),4),
                    "ci95":round(ci95(deltas[k]),4),
                    "paired_bb":round(statistics.mean(by_state[k]["paired_board_two_pair"]),4)
                      if by_state[k]["paired_board_two_pair"] else None}
                 for k in versions
              },
              "state_counts":dict(state_counter),
            }
            summary[f"{scname} {hand}"]=row
            print("RESULT "+json.dumps(row,sort_keys=True,ensure_ascii=False),flush=True)
    for scname in SCENARIOS:
        rows=[v for v in summary.values() if v["scenario"]==scname]
        print("SUMMARY "+json.dumps({
            "scenario":scname,"samples":sum(x["n"] for x in rows),
            "mean_delta":{v:round(statistics.mean(r["variants"][v]["delta_bb"] for r in rows),4)
                          for v in ("corrected","bluffcatch","probe")}
        },ensure_ascii=False),flush=True)
    print("STUDY_COMPLETE "+str(len(summary))+" subgroups",flush=True)


if __name__=="__main__":
    main()
