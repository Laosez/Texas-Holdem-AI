"""A17 hand-to-box mapping copied from the user's A17 edited JSON.

Source: SKACHKOV_A17_BOXES_EDITED.json
SHA256: 018a54acb73dc622a97c34a09cd440cf40817bfa48131f804b3e143d1dabbbc5
Only 'hand' and 'box' are relevant here; equity fields are NOT position ranges.
The 17 boxes and all 169 classes are preserved exactly.
"""

A17_BOX_HANDS = {
    1: "AA KK QQ JJ",
    2: "AKs AKo TT 99",
    3: "AQs AQo 88 77",
    4: "AJs ATs AJo 66 55",
    5: "A9s A8s A7s A6s A5s ATo",
    6: "KQs KJs KTs KQo QJs QTs JTs",
    7: "A4s A3s A2s 44 33 22",
    8: "K9s K8s K7s Q9s Q8s Q7s J9s J8s J7s T9s T8s T7s",
    9: "98s 97s 96s 87s 86s 85s 76s 75s 74s 65s 64s 54s",
    10: "KJo QJo KTo QTo JTo K9o Q9o J9o",
    11: "K6s K5s K4s K3s K2s Q6s Q5s Q4s Q3s J6s J5s T6s T5s",
    12: "A9o A8o A7o A6o A5o A4o A3o A2o",
    13: "Q2s J4s J3s J2s T4s T3s T2s 95s 94s 93s 92s 84s 83s 82s 73s 72s 63s 62s 53s 52s 43s 42s 32s",
    14: "T9o T8o 98o 97o 87o 86o 76o 75o 65o 64o 54o",
    15: "K8o K7o K6o K5o K4o K3o K2o",
    16: "J8o T7o 96o 85o 74o",
    17: "Q8o Q7o J7o Q6o J6o T6o Q5o J5o T5o 95o Q4o J4o T4o 94o 84o Q3o J3o T3o 93o 83o 73o 63o 53o 43o Q2o J2o T2o 92o 82o 72o 62o 52o 42o 32o",
}

# The numeric rank stays the same as table size shrinks.\n# In 6-max, rank "6" is UTG but still has its originally approved A01-A10.\nA17_MAX_OPEN_BOX_BY_POSITION = {\n    "9": 9,   # UTG
    "8": 9,   # UTG+1
    "7": 9,   # MP
    "6": 10,  # LJ
    "5": 12,  # HJ
    "4": 14,  # CO
    "3": 15,  # BTN
    "SB": 17, # All A17 hands are played; see separate raise boundary below.
}

# Applies at every tournament stage, including heads-up.
# A01-A16: raise whenever legal; A17: call/complete/check.
A17_SB_MAX_RAISE_BOX = 16\n\n# Compatibility for existing reports/tests referring to the 9-max template.\nA17_MAX_OPEN_BOX_9MAX = A17_MAX_OPEN_BOX_BY_POSITION


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


A17_HAND_TO_BOX = _hand_to_box()
