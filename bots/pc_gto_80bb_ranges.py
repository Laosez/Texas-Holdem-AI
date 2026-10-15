"""PC GTO 80bb (PokerCoaching source): quarter-step approximation of 80bb RFI.

Generated from the user's source PDF, pages 4-5 (80BB RAISE FIRST IN).
The tables encode all 169 starting-hand classes in 13x13 matrix order
(AKQJT98765432, suited above the diagonal, offsuit below). Each digit
is the corresponding action probability in 25 percentage-point units.
RFI charts at 80bb contain no shove; SB's "Call" = open-complete/limp.

This is a test baseline, NOT exact solver output, and is NOT a complete
80bb response chart for vs RFI, vs 3bet or vs 4bet.
"""
from __future__ import annotations

RANKS = "AKQJT98765432"
RFI_RAISE = {
    'UTG': '4444444444440,4444444400000,4444440000000,4004440000000,2000440000000,0000040000000,0000004000000,0000000410000,0000000043000,0000000004000,0000000000200,0000000000000,0000000000000',
    'UTG1': '4444444444444,4444444430000,4444440000000,4224440000000,4000444000000,0000043000000,0000004000000,0000000410000,0000000044000,0000000004000,0000000000400,0000000000000,0000000000000',
    'LJ': '4444444444444,4444444444000,4444443000000,4444442000000,4101444000000,1000044000000,0000004100000,0000000440000,0000000044000,0000000004100,0000000000400,0000000000040,0000000000000',
    'HJ': '4444444444444,4444444444400,4444444300000,4444444000000,4444444400000,4000044400000,4000004400000,0000000440000,0000000044000,0000000004400,0000000000400,0000000000040,0000000000002',
    'CO': '4444444444444,4444444444444,4444444444400,4444444442000,4444444440000,4400444440000,4000004440000,4000000444000,0000000044000,4000000004400,0000000000400,0000000000040,0000000000004',
    'BTN': '4444444444444,4444444444444,4444444444444,4444444444444,4444444444440,4444444444000,4444444444000,4430203444400,4400000044400,4400000004440,4000000000400,4000000000040,4000000000004',
    'SB': '0334412103000,0142300000000,0003100000000,0000310000002,0000120002010,0000011000110,0010011100200,1000110010010,0200000012000,0100000011101,0000000000003,0000000000000,0000000000000'
}
RFI_SB_LIMP = '4110032341444,4302144444444,4441344444444,4444134444442,4444324442434,4444433444334,4434433344244,3444334434434,4244444432444,4344444433343,4444444444441,4444440004444,4444400000004'

def _expand(value: str):
    rows = value.split(",")
    if len(rows) != 13 or any(len(row) != 13 for row in rows):
        raise ValueError("Invalid PC GTO 80bb chart geometry: expected 13x13")
    flattened = "".join(rows)
    if any(d not in "01234" for d in flattened):
        raise ValueError("PC GTO 80bb action probability must be 0-4 quarters")
    return tuple(int(d) for d in flattened)

def _matrix_hands():
    return tuple(
        RANKS[i] * 2 if i == j else
        RANKS[i] + RANKS[j] + "s" if i < j else
        RANKS[j] + RANKS[i] + "o"
        for i in range(13) for j in range(13)
    )

HANDS = _matrix_hands()
RAISE = {name: _expand(rows) for name, rows in RFI_RAISE.items()}
LIMP_SB = _expand(RFI_SB_LIMP)

# Number of remaining players, not the original 8-max guide's table number:
# extra early seats at 9-max reuse UTG; late positions remain fixed by distance
# to BTN; at short tables the earliest available seat uses its relative chart.
def chart_position(position: str, players: int) -> str | None:
    pos = str(position).upper()
    if pos == "SB":
        return "SB"
    if pos == "BB":
        return None
    if not pos.isdecimal() or not 3 <= int(pos) <= players <= 9:
        return None
    return {3: "BTN", 4: "CO", 5: "HJ", 6: "LJ", 7: "UTG1"}.get(int(pos), "UTG")

def rfi_actions(hand: str, position: str, players: int) -> dict[str, int] | None:
    chart = chart_position(position, players)
    if chart is None:
        return None
    index = HANDS.index(hand)
    raised = RAISE[chart][index]
    limped = LIMP_SB[index] if chart == "SB" else 0
    if raised + limped > 4:
        raise AssertionError("Invalid PC GTO 80bb action distribution")
    actions = {"fold": (4-raised-limped)*25, "open": raised*25}
    if chart == "SB":
        actions["limp"] = limped*25
    return actions

def combo_weight(hand: str) -> int:
    return 6 if len(hand) == 2 else (4 if hand.endswith("s") else 12)

def weighted_rfi(name: str) -> dict[str, float]:
    total = sum(combo_weight(h) for h in HANDS)
    actions = (rfi_actions(h, name, 9) for h in HANDS)
    # Non-numeric names accepted here solely to audit source charts directly.
    rows = RAISE[name]
    values = {"raise": sum(combo_weight(h)*rows[i]*25 for i,h in enumerate(HANDS))/total}
    if name == "SB":
        values["limp"] = sum(combo_weight(h)*LIMP_SB[i]*25 for i,h in enumerate(HANDS))/total
    values["fold"] = 100.0 - values["raise"] - values.get("limp", 0)
    return values

for _pos in RAISE:
    for _h in HANDS:
        _r = RAISE[_pos][HANDS.index(_h)]
        _l = LIMP_SB[HANDS.index(_h)] if _pos == "SB" else 0
        if _r + _l > 4:
            raise AssertionError(f"PC GTO 80bb invalid {_pos} {_h}")
