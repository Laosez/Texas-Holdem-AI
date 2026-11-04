"""Post-hoc GTO 5.0 shadow report; GTO 4.1 is a noisy reference.

This module does NOT execute the bots. Input records must be paired snapshots
from the same information set and include matching action sizes.
"""
from collections import Counter, defaultdict
from statistics import mean
import math

_RANKS = "23456789TJQKA"


def board_tags(board):
    cards = [tuple(c) for c in board]
    if len(cards) not in (3, 4, 5) or any(len(c) != 2 for c in cards):
        raise ValueError("Invalid board")
    if len(set(cards)) != len(cards):
        raise ValueError("Duplicated card")
    ranks = Counter(c[0] for c in cards)
    suits = Counter(c[1] for c in cards)
    if not set(ranks) <= set(_RANKS) or not set(suits) <= set("cdhs"):
        raise ValueError("Invalid rank or suit")
    counts = sorted(ranks.values(), reverse=True)
    if counts[0] == 4:
        p = "P4"
    elif counts[0] == 3:
        p = "PH" if 2 in counts else "P3"
    elif counts.count(2) == 2:
        p = "P2"
    else:
        p = "P1" if counts[0] == 2 else "P0"
    rs = {_RANKS.index(r) + 2 for r in ranks}
    windows = [set(range(n, n + 5)) for n in range(2, 11)]
    windows.append({14, 2, 3, 4, 5})
    m = max(len(rs & w) for w in windows)
    adjacent = any({n, n+1} <= rs for n in range(2, 14))
    s = "S5" if m >= 5 else "S4" if m == 4 else (
        "S3" if m == 3 else "S2" if adjacent else "S0")
    f_count = max(suits.values())
    f = "F0" if f_count == 1 else "F" + str(f_count)
    return {"P": p, "S": s, "F": f,
            "structure": " · ".join((p, s, f))}


def compare(record):
    """Return normalized EV deltas and regret, or an explicit skip reason.

    Keys in ev5 and ev41 must match EXACTLY. For bets, use e.g. bet:100
    to prevent comparing different amounts.
    """
    try:
        a = {str(k): float(v) for k, v in record["ev5"].items()}
        b = {str(k): float(v) for k, v in record["ev41"].items()}
        action = str(record["chosen5"])
        bb = float(record["bb"])
        opponents = int(record["opponents"])
        street = str(record["street"]).lower()
        if not a or len(a) < 2 or set(a) != set(b):
            return None, "incompatible_actions"
        if action not in a:
            return None, "unknown_choice"
        if not (bb > 0 and math.isfinite(bb)):
            return None, "invalid_bb"
        if not all(math.isfinite(v) for v in list(a.values()) + list(b.values())):
            return None, "nonfinite_ev"
        if street not in ("flop", "turn", "river") or not 1 <= opponents <= 8:
            return None, "invalid_context"
        tags = board_tags(record["board"])
    except (KeyError, TypeError, ValueError, AttributeError):
        return None, "invalid_record"
    ideal = max(b, key=b.get)
    errors = [abs(a[k]-b[k])/bb for k in a]
    return {**tags, "street": street,
            "actor": record.get("actor", "gto50"),
            "reference_model": record.get("reference_model", "gto41"),
            "opponents": str(opponents) if opponents < 4 else "4+",
            "mean_ev_delta_bb": mean(errors),
            "max_ev_delta_bb": max(errors),
            "regret_bb": max(0, b[ideal]-b[action])/bb,
            "mismatch": int(action != ideal),
            "chosen5": action, "chosen41": ideal,
            "board": ["".join(c) for c in record["board"]],
            "hand_id": record.get("hand_id"),
            "tournament": record.get("tournament")}, None


def _metrics(rows, minimum):
    n = len(rows)
    if n == 0:
        return {"n": 0, "sufficient": False}
    regrets = [r["regret_bb"] for r in rows]
    deltas = [r["max_ev_delta_bb"] for r in rows]
    return {
        "n": n,
        "sufficient": n >= minimum,
        "mae_ev_bb": round(mean(r["mean_ev_delta_bb"] for r in rows), 4),
        "max_delta_bb": round(max(deltas), 4),
        "delta_over_1bb_pct": round(100*sum(v > 1 for v in deltas)/n, 2),
        "delta_over_5bb_pct": round(100*sum(v > 5 for v in deltas)/n, 2),
        "mismatch_pct": round(100*mean(r["mismatch"] for r in rows), 2),
        "mean_regret_bb": round(mean(regrets), 4),
        "max_regret_bb": round(max(regrets), 4),
        "total_regret_bb": round(sum(regrets), 4),
        "regret_over_1bb_pct": round(100*sum(v > 1 for v in regrets)/n, 2),
        "regret_over_5bb_pct": round(100*sum(v > 5 for v in regrets)/n, 2),
    }


MODEL_LABELS = {
    "gto41": "GTO 4.1",
    "gto50": "GTO 5.0",
    "gto505": "GTO 5.0.5",
}


def _aggregate_valid(valid, minimum):
    """Same aggregation for the whole report and each actor/reference pair."""
    keys = {
        "street": ("street",),
        "opponents": ("opponents",),
        "P": ("P",), "S": ("S",), "F": ("F",),
        "board_structure": ("structure",),
        "street_opponents": ("street", "opponents"),
        "street_board": ("street", "structure"),
        "opponents_board": ("opponents", "structure"),
        "street_opponents_board": ("street", "opponents", "structure"),
    }
    groups = {}
    for name, fields in keys.items():
        buckets = defaultdict(list)
        for row in valid:
            buckets[" | ".join(row[f] for f in fields)].append(row)
        groups[name] = [
            {"label": label, **_metrics(rows, minimum)}
            for label, rows in sorted(buckets.items())
        ]
    eligible = [r for r in groups["board_structure"] if r["sufficient"]]
    rankings = {
        "frequent": sorted(eligible, key=lambda v: -v["mismatch_pct"])[:20],
        "frequent_ev_discrepancy": sorted(
            eligible, key=lambda v: -v["delta_over_5bb_pct"])[:20],
        "expensive": sorted(eligible, key=lambda v: -v["mean_regret_bb"])[:20],
        "total_loss": sorted(eligible, key=lambda v: -v["total_regret_bb"])[:20],
        "worst_decisions": sorted(valid, key=lambda v: -v["regret_bb"])[:20],
    }
    return {"compared": len(valid), "overall": _metrics(valid, minimum),
            "groups": groups, "rankings": rankings}


def aggregate_shadow(records, minimum=30):
    """Paired EV comparisons grouped by F/T/R, board, and exact model pair."""
    valid, skipped = [], Counter()
    for rec in records:
        value, reason = compare(rec)
        if reason:
            skipped[reason] += 1
        else:
            valid.append(value)
    result = {
        "format": "SKACHKOV_GTO5_SHADOW_REPORT_V2",
        "reference": "Reference model EV, not solver truth",
        "skipped": sum(skipped.values()),
        "skip_reasons": dict(skipped),
        **_aggregate_valid(valid, minimum),
    }
    by_pair = defaultdict(list)
    for row in valid:
        by_pair[(row["actor"], row["reference_model"])].append(row)
    result["comparisons"] = [{
        "key": actor + ":" + ref,
        "actor": actor, "reference_model": ref,
        "label": (MODEL_LABELS.get(actor, actor) + " → " +
                  MODEL_LABELS.get(ref, ref)),
        **_aggregate_valid(rows, minimum),
    } for (actor, ref), rows in sorted(by_pair.items())]
    if len(result["comparisons"]) == 1:
        result["reference"] = result["comparisons"][0]["label"]
    return result
