"""Shared table-order helpers for engine drivers and CFR search."""

from __future__ import annotations

from typing import Any, Iterable, List, Optional



# One canonical position scheme for every table size (dealer-first order):
# 9-max preflop: 9,8,7,6,5,4,3,SB,BB. 3 is always the button (3+).
# Heads-up has only SB (also the button) and BB.
# No UTG/MP/HJ/CO/BTN aliases are used by the simulator.
def position_labels(n: int) -> List[str]:
    """Return numeric preflop positions, clockwise from the button (2..10)."""
    if not 2 <= n <= 10:
        raise ValueError(f"Unsupported table size: {n}; expected 2..10")
    if n == 2:
        return ["SB", "BB"]
    return ["3", "SB", "BB", *[str(rank) for rank in range(n, 3, -1)]]


def position_group(position: str, n_players: int) -> str:
    """Numeric position -> early/middle/late/sb/bb, relative to table size."""
    p = str(position).upper()
    if p == "SB":
        return "sb"
    if p == "BB":
        return "bb"
    if not p.isdecimal():
        raise ValueError(f"Unknown numeric position: {position!r}")
    k = int(p)
    if not (3 <= k <= n_players):
        raise ValueError(f"Position {p} is invalid at {n_players}-max")
    if k >= 8 or (k == n_players and n_players >= 6):
        return "early"
    if k >= 6:
        return "middle"
    return "late"


def position_tightness(position: str, n_players: int = 9) -> float:
    """Position tightness in [0, 1], preserving the bots' relative late bias.

    Early position gets 1.0 at 6+ tables. SB heads-up is the button, hence
    receives the button's 0.0 tightness; at 3+ tables it is a normal SB.
    """
    p = str(position).upper()
    if p == "SB":
        return 0.0 if n_players == 2 else 0.5
    if p == "BB":
        return 0.7
    if not p.isdecimal():
        return 0.5
    k = int(p)
    if not 3 <= k <= n_players:
        return 0.5
    if k == n_players and n_players >= 6:
        return 1.0
    if k == n_players - 1 and n_players >= 9:
        return 0.9
    return {3: 0.0, 4: 0.2, 5: 0.4, 6: 0.6, 7: 0.7,
            8: 0.9, 9: 0.9, 10: 1.0}.get(k, 0.5)


def street_action_order(street: str, ring_order: Iterable[int]) -> List[int]:
    """Return the fresh-street action order for a dealer-first ring."""
    ring = list(ring_order)
    if not ring:
        return []
    n = len(ring)
    if street == "preflop":
        start = 3 if n > 2 else 0
    else:
        start = 1 if n > 1 else 0
    start %= n
    return ring[start:] + ring[:start]


def is_active_seat(seat: Any) -> bool:
    """True when a seat should be included in the next hand."""
    return (
        getattr(seat, "chips", 0) > 0
        and not getattr(seat, "is_sitting_out", False)
    )


def active_seat_indices(seats: Iterable[Any]) -> List[int]:
    """Indices of seats with chips that are not sitting out."""
    return [i for i, seat in enumerate(seats) if is_active_seat(seat)]


def next_active_seat_index(
    seats: List[Any],
    after_index: int,
) -> Optional[int]:
    """Return the next active seat clockwise after ``after_index``."""
    if not seats:
        return None
    n = len(seats)
    for offset in range(1, n + 1):
        idx = (after_index + offset) % n
        if is_active_seat(seats[idx]):
            return idx
    return None


def normalize_dealer_seat_index(
    seats: List[Any],
    dealer_seat_index: int,
) -> Optional[int]:
    """Return an active full-table dealer index nearest the requested button."""
    if not seats:
        return None
    idx = dealer_seat_index % len(seats)
    if is_active_seat(seats[idx]):
        return idx
    return next_active_seat_index(seats, idx - 1)


def advance_dealer_seat_index(
    seats: List[Any],
    dealer_seat_index: int,
) -> Optional[int]:
    """Advance the button using full-table indices, skipping busted seats."""
    if not seats:
        return None
    idx = dealer_seat_index % len(seats)
    return next_active_seat_index(seats, idx)
