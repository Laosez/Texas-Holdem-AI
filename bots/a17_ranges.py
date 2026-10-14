"""A17 hand-to-box mapping copied from the user's A17 edited JSON.

from __future__ import annotations
import json
from pathlib import Path

CATALOG_PATH = Path(__file__).resolve().parents[1] / "strategy_catalog" / "a17_v5.json"
CATALOG_ID = "A17_V5"
def _catalog():
    data = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    ranks="AKQJT98765432"
    expected={r+r for r in ranks}
    for i,a in enumerate(ranks):
        for b in ranks[i+1:]:
            expected.update((a+b+"s",a+b+"o"))
    hands=data.get("hands",[])
    mapping={v["hand"]:v["box"] for v in hands}
    if len(hands)!=169 or len(mapping)!=169 or set(mapping)!=expected or set(mapping.values())!=set(range(1,18)):
        raise RuntimeError("Invalid canonical A17 catalog")
    if sum(v["combos"] for v in hands)!=1326:
        raise RuntimeError("Invalid canonical A17 combos")
    if mapping["JTo"]!=14 or mapping["J9o"]!=14:
        raise RuntimeError("A17 V5 must assign JTo and J9o to A14")
    return mapping
A17_HAND_TO_BOX = _catalog()
A17_BOX_HANDS = {i:" ".join(h for h,b in A17_HAND_TO_BOX.items() if b==i) for i in range(1,18)}

# The numeric rank stays the same as table size shrinks.
# In 6-max, rank "6" is UTG but still has its originally approved A01-A10.
A17_MAX_OPEN_BOX_BY_POSITION = {
    "9": 9,   # UTG
    "8": 9,   # UTG+1
    "7": 9,   # MP
    "6": 10,  # LJ
    "5": 11,  # HJ
    "4": 11,  # CO
    "3": 12,  # BTN base range; A15 additionally, not A13/A14
    "SB": 17, # All A17 hands are played; see separate raise boundary below.
}

# Additional non-contiguous RFI boxes for specific numeric positions.
# BTN explicitly plays A01-A12 plus A15 only. Boxes A13 and A14 are excluded.
A17_RFI_EXTRA_BOXES_BY_POSITION = {
    "3": frozenset({15}),
}

# Applies at every tournament stage, including heads-up.
# A01-A16: raise whenever legal; A17: call/complete/check.
A17_SB_MAX_RAISE_BOX = 16

# Facing exactly a preflop 3-bet (second voluntary raise).
# A01-A07 and A09: split 50% call / 50% 4-bet.
# A08 and A10-A17: pure fold. Overrides SB and BB defaults.
A17_VS_3BET_CONTINUE_BOXES = frozenset((1, 2, 3, 4, 5, 6, 7, 9))
A17_VS_3BET_FOURBET_FREQ = 0.50

# Compatibility for existing reports/tests referring to the 9-max template.
A17_MAX_OPEN_BOX_9MAX = A17_MAX_OPEN_BOX_BY_POSITION


def _hand_to_box():
    ranks = "AKQJT98765432"
    expected = {r + r for r in ranks}
    for i, high in enumerate(ranks):
        for low in ranks[i + 1:]:
            expected.add(high + low + "s")
            expected.add(high + low + "o")
    result = {}
    for box in range(1, 18):
        for hand in A17_BOX_HANDS[box].split():
            if hand in result:
                raise ValueError(f"A17 duplicate hand: {hand}")
            result[hand] = box
    if set(result) != expected:
        raise ValueError(f"A17 incomplete mapping: missing={sorted(expected-set(result))}, extra={sorted(set(result)-expected)}")
    combos = sum(6 if len(h) == 2 else 4 if h.endswith("s") else 12 for h in result)
    if len(result) != 169 or combos != 1326:
        raise ValueError(f"A17 expected 169 hands and 1326 combos, got {len(result)}, {combos}")
    return result


# Strict verification of the canonical map against the derived boxed view.
if _hand_to_box() != A17_HAND_TO_BOX:
    raise RuntimeError('A17 catalog mismatch')
