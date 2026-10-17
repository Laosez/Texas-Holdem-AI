"""Shared tournament finishing-place rules, including simultaneous busts.

The table order must never decide which of two players eliminated in the
same hand finishes higher. Larger stacks at the START of that hand win the
tie-break. Equal start stacks are tied, using competition ranking.
"""
from __future__ import annotations


def append_eliminations(seats, finish_order, start_stacks, hand_count, total_players):
    """Append all newly eliminated players after a single completed hand.

    Competition ranks: when two players with the same starting stack both
    bust in positions 8/9, they are both ranked 8th, not arbitrarily 8/9.
    A tie in the largest surviving stack is not handled by this function.
    """
    ranked = {entry[0] for entry in finish_order}
    busted = [seat for seat in seats if seat.chips <= 0 and seat.player_id not in ranked]
    if not busted:
        return []
    busted.sort(key=lambda seat: start_stacks[seat.player_id])
    next_place = total_players - len(finish_order)
    results = []
    idx = 0
    while idx < len(busted):
        size = start_stacks[busted[idx].player_id]
        end = idx + 1
        while end < len(busted) and start_stacks[busted[end].player_id] == size:
            end += 1
        place = next_place - (end - idx) + 1
        for seat in busted[idx:end]:
            entry = (seat.player_id, place, hand_count, 0)
            finish_order.append(entry)
            results.append(entry)
        next_place -= end - idx
        idx = end
    return results
