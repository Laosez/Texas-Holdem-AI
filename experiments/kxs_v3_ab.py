#!/usr/bin/env python3
"""Identically dealt Kxs postflop chip-EV comparison V2 vs V3.

The deal (hero hole, villain holes, board) is shared across policies.
Full Table betting engine executes both policies.  Preflop uses the fixed
Planner 2.5BB BTN open/call scenario, at 20BB effective stack.
Not a GTO equilibrium or a statistical claim about live tournament EV.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import random
import statistics

import planner_equity as equity
import planner_postflop_ev as engine


HANDS = [f"K{rank}s" for rank in "23456789TJQ"]
SCENARIOS = {
    "HU_GTO": [("builtin:pc_gto_80bb","9","gto2")],
    "HU_TAG": [("builtin:pc_gto_80bb","9","tag")],
    "HU_LAG": [("builtin:any_two","9","lag")],
}

def opponent(profile,position,line):
    return {"profile":profile,"position":position,"scenario":"rfi","players":9,
            "selector":"active","entry_mode":"always","entry_pct":100,
            "postflop":line}

def ci(deltas):
    return 1.96 * statistics.stdev(deltas) / math.sqrt(len(deltas)) if len(deltas)>1 else 0.0

def run(samples):
    for name, triples in SCENARIOS.items():
        specs=[opponent(*t) for t in triples]
        ranges,_=equity.build_ranges(specs,"selected")
        stats=[]
        for hand in HANDS:
            key=f"kxs-v3-ab:{name}:{hand}:{samples}"
            rng=random.Random(int(hashlib.sha256(key.encode()).hexdigest()[:16],16))
            base,variant,equities,deltas=[],[],[],[]
            for _ in range(samples):
                picked,board=engine._draw_case(hand,ranges,specs,rng)
                equities.append(engine._showdown_share(picked,board))
                seed=rng.randrange(1 << 49)
                random.seed(seed)
                v2,_=engine._play_case(picked,board,"gto2","3",20,seed)
                random.seed(seed)
                v3,_=engine._play_case(picked,board,"gto3","3",20,seed)
                base.append(v2);variant.append(v3);deltas.append(v3-v2)
            obj={"scenario":name,"hand":hand,"n":samples,
                 "showdown_equity_pct":round(100*statistics.mean(equities),2),
                 "v2_ev_bb":round(statistics.mean(base),4),
                 "v3_ev_bb":round(statistics.mean(variant),4),
                 "delta_bb":round(statistics.mean(deltas),4),
                 "delta_ci95_halfwidth":round(ci(deltas),4)}
            stats.append(obj)
            print("RESULT "+json.dumps(obj,ensure_ascii=False),flush=True)
        summary={"scenario":name,"n_per_hand":samples,
                 "equal_class_mean_delta_bb":round(statistics.mean(s["delta_bb"] for s in stats),4),
                 "changed_hands":sum(s["delta_bb"]!=0 for s in stats),
                 "winning_hands":sum(s["delta_bb"]>0 for s in stats),
                 "losing_hands":sum(s["delta_bb"]<0 for s in stats)}
        print("SUMMARY "+json.dumps(summary,ensure_ascii=False),flush=True)
    print("STUDY_COMPLETE: 11 Kxs classes x 3 opponents, V2 vs V3",flush=True)

if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("--samples",type=int,default=450)
    a=p.parse_args()
    if a.samples < 100 or a.samples>3000:raise SystemExit("100 <= samples <= 3000")
    run(a.samples)
