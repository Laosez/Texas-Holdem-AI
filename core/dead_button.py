"""Physical-seat TDA dead-button movement for a single tournament table.

BB advances to the next live seat. SB is the immediately preceding physical
seat and may be empty; BTN is two physical seats back and may be empty.
Heads-up is special: the live SB is the button and BB alternates.
"""
from core.table_order import (
    is_active_seat, next_active_seat_index, normalize_dealer_seat_index,
)


def initial_blinds(seats, dealer_index):
    button=normalize_dealer_seat_index(seats,dealer_index)
    if button is None:
        raise ValueError("Table has no live dealer")
    sb=next_active_seat_index(seats,button)
    if sb is None or sb==button:
        raise ValueError("Dead-button mode requires 2+ players")
    bb=next_active_seat_index(seats,sb)
    if bb is None:
        raise ValueError("Cannot assign big blind")
    if sum(is_active_seat(s) for s in seats)==2:
        return (button,button,sb)  # HU: dealer is SB, next player BB
    return (button,sb,bb)


def next_blinds(seats,previous_bb):
    active=[i for i,s in enumerate(seats) if is_active_seat(s)]
    if len(active)<2:
        return None
    bb=next_active_seat_index(seats,previous_bb)
    if len(active)==2:
        sb=next_active_seat_index(seats,bb)
        return (sb,sb,bb)
    n=len(seats)
    sb_candidate=(bb-1)%n
    sb=sb_candidate if is_active_seat(seats[sb_candidate]) else None
    button=(bb-2)%n
    return (button,sb,bb)
