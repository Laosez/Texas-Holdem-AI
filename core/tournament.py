"""Canonical tournament loop shared by eval, UI, and engine wrappers."""

from __future__ import annotations

import io
import random
from contextlib import nullcontext, redirect_stdout
from typing import Any, Callable, Literal

from bots import escalate_blinds
from core.engine import Seat, Table
from core.engine_factory import make_table
from core.table_order import advance_dealer_seat_index, normalize_dealer_seat_index
from core.tournament_rules import append_eliminations
from core.dead_button import initial_blinds, next_blinds
from run_tournament_stats import finalize_finish_order


DealerRotation = Literal["full_table", "active_circle", "dead_button"]
WinnerResolution = Literal["finish_order", "chip_count_on_max_hands"]
TournamentEvent = dict[str, Any]
TournamentCallback = Callable[[TournamentEvent], None]
CancelCheck = Callable[[], bool]
PauseWait = Callable[[], None]
AnteSchedule = Callable[[int, int, int], int]


def _coerce_seats(seats: list[Seat | dict[str, Any]], chips: int | None) -> list[Seat]:
    """Return mutable Seat instances, optionally resetting their stack size."""
    result = [s if isinstance(s, Seat) else Seat(**s) for s in seats]
    if chips is not None:
        for seat in result:
            seat.chips = chips
    return result


def _active_seats(seats: list[Seat]) -> list[Seat]:
    # Sitting-out seats are intentionally excluded; eval's chips-only filter is a benign subset.
    return [s for s in seats if s.chips > 0 and not s.is_sitting_out]


def _emit(callback: TournamentCallback | None, event: TournamentEvent) -> None:
    if callback is not None:
        callback(event)


def _winner_from_finish_order(
    finish_order: list[tuple[str, int, int, int]],
) -> str | None:
    for pid, pos, _, _ in finish_order:
        if pos == 1:
            return pid
    return None


def run_tournament(
    seats: list[Seat | dict[str, Any]],
    bot_for: dict[str, Any],
    *,
    small_blind: int,
    big_blind: int,
    blind_increase_every: int = 50,
    max_hands: int | None = 10_000,
    chips: int | None = None,
    dealer_index: int = 0,
    dealer_rotation: DealerRotation = "full_table",
    winner_resolution: WinnerResolution = "chip_count_on_max_hands",
    ante: int = 0,
    ante_schedule: AnteSchedule | None = None,
    rng: random.Random | None = None,
    table: Table | None = None,
    engine_impl: str | None = None,
    on_event: TournamentCallback | None = None,
    hand_delay: Callable[[], None] | None = None,
    should_cancel: CancelCheck | None = None,
    wait_if_paused: PauseWait | None = None,
    suppress_output: bool = False,
    log_decisions: bool = False,
) -> dict[str, Any]:
    """Run a last-bot-standing tournament and return eval-ready results.

    ``dealer_rotation="full_table"`` is the battle-tested ``run_eval`` loop:
    keep the original seat list, normalize the dealer over non-busted seats,
    stop at ``max_hands``, then resolve unfinished survivors by chip count.

    ``dealer_rotation="active_circle"`` preserves the legacy UI/manager loop:
    pass only active seats to the hand engine and advance the dealer in that
    shrinking active circle.
    """
    seats = _coerce_seats(seats, chips)
    if dealer_rotation not in ("full_table", "active_circle", "dead_button"):
        raise ValueError(f"unknown dealer_rotation: {dealer_rotation!r}")
    if winner_resolution not in ("finish_order", "chip_count_on_max_hands"):
        raise ValueError(f"unknown winner_resolution: {winner_resolution!r}")
    if ante < 0:
        raise ValueError("ante must be non-negative")

    # An explicitly-passed table wins; otherwise select the engine
    # implementation ("pe" by default since P6, or "legacy" / THAI_ENGINE_IMPL).
    table = table or make_table(
        rng=rng,
        engine_impl=("legacy" if dealer_rotation=="dead_button" and engine_impl is None
                     else engine_impl))
    if dealer_rotation=="dead_button":
        # The PE adapter cannot represent a physically empty SB/BTN.
        from core.engine import Table as LegacyTable
        if not isinstance(table,LegacyTable):
            raise ValueError("Dead-button mode requires the legacy table engine")
        dead_state=initial_blinds(seats,dealer_index)
    dealer = dealer_index
    hand_count = 0
    total_players = len(seats)
    finish_order: list[tuple[str, int, int, int]] = []
    chip_history: list[dict[str, int]] = [
        {"hand": 0, **{seat.player_id: seat.chips for seat in seats}}
    ]

    _emit(on_event, {
        "type": "start",
        "hand": 0,
        "seats": seats,
        "chip_history": chip_history,
    })

    output_cm = redirect_stdout(io.StringIO()) if suppress_output else nullcontext()
    with output_cm:
        while True:
            active = _active_seats(seats)
            if len(active) <= 1:
                break
            if max_hands is not None and hand_count >= max_hands:
                break
            if should_cancel is not None and should_cancel():
                _emit(on_event, {
                    "type": "cancelled",
                    "hand": hand_count,
                    "seats": seats,
                    "chip_history": chip_history,
                })
                return {
                    "winner": None,
                    "hand_count": hand_count,
                    "finish_order": finish_order,
                    "final_chips": {s.player_id: s.chips for s in seats},
                    "chip_swing": None,
                    "chip_history": chip_history,
                    "cancelled": True,
                }
            if wait_if_paused is not None:
                wait_if_paused()

            hand_count += 1
            sb, bb = escalate_blinds(
                hand_count, small_blind, big_blind, blind_increase_every
            )
            hand_ante = (
                int(ante_schedule(hand_count, sb, bb))
                if ante_schedule is not None
                else int(ante)
            )
            if hand_ante < 0:
                raise ValueError("ante schedule returned a negative ante")
            _emit(on_event, {
                "type": "hand_start",
                "hand": hand_count,
                "small_blind": sb,
                "big_blind": bb,
                "ante": hand_ante,
                "seats": seats,
            })

            if dealer_rotation in ("full_table","dead_button"):
                hand_seats = seats
                hand_bots = {s.player_id: bot_for[s.player_id] for s in active}
                if dealer_rotation=="dead_button":
                    if dead_state is None:break
                    hand_dealer=dead_state[0]
                else:
                    normalized_dealer = normalize_dealer_seat_index(seats, dealer)
                    if normalized_dealer is None:
                        break
                    hand_dealer = normalized_dealer
                    dealer = normalized_dealer
            else:
                hand_seats = active
                hand_bots = {s.player_id: bot_for[s.player_id] for s in hand_seats}
                hand_dealer = dealer % len(hand_seats)

            pre_hand_stacks={seat.player_id:seat.chips for seat in seats}
            table.play_hand(
                seats=hand_seats,
                small_blind=sb,
                big_blind=bb,
                dealer_index=hand_dealer,
                bot_for=hand_bots,
                on_event=None,
                log_decisions=log_decisions,
                ante=hand_ante,
                blind_increase_every=blind_increase_every,
                **({"blind_seats":dead_state[1:]}
                   if dealer_rotation=="dead_button" else {}),
            )

            if dealer_rotation=="dead_button":
                dead_state=next_blinds(seats,dead_state[2])
            elif dealer_rotation == "full_table":
                next_dealer = advance_dealer_seat_index(seats, dealer)
                if next_dealer is not None:
                    dealer = next_dealer
            else:
                # hand_dealer indexes the OLD active circle. Never reuse that
                # index in the shrunken circle: this skips positions on a bust.
                old_ring=[seat.player_id for seat in hand_seats]
                new_ring=[seat.player_id for seat in _active_seats(seats)]
                successor=next((
                    old_ring[(hand_dealer+step)%len(old_ring)]
                    for step in range(1,len(old_ring)+1)
                    if old_ring[(hand_dealer+step)%len(old_ring)] in new_ring
                ),None)
                dealer=new_ring.index(successor) if successor is not None else 0

            snapshot = {"hand": hand_count}
            for seat in seats:
                snapshot[seat.player_id] = seat.chips
            chip_history.append(snapshot)

            eliminated_events=append_eliminations(
                seats,finish_order,pre_hand_stacks,hand_count,total_players)

            _emit(on_event, {
                "type": "hand_end",
                "hand": hand_count,
                "small_blind": sb,
                "big_blind": bb,
                "ante": hand_ante,
                "seats": seats,
                "chip_history": chip_history,
                "eliminations": eliminated_events,
            })
            for pid, pos, _, _ in eliminated_events:
                _emit(on_event, {
                    "type": "elimination",
                    "hand": hand_count,
                    "player_id": pid,
                    "position": pos,
                    "seats": seats,
                    "chip_history": chip_history,
                })

            if hand_delay is not None:
                hand_delay()

    survivors=_active_seats(seats)
    naturally_complete=len(survivors)==1
    finalize_finish_order(seats, finish_order, total_players, hand_count)
    final_chips = {seat.player_id: seat.chips for seat in seats}
    # Provisional chip ranks in finish_order are NOT natural winners.
    winner=(survivors[0].player_id if naturally_complete else None)
    winner_source="natural" if naturally_complete else None
    if (winner is None and winner_resolution=="chip_count_on_max_hands"
            and len(survivors)>1):
        winner=max((s.player_id for s in survivors),key=lambda pid:final_chips[pid])
        winner_source="chip_count_cap"

    chip_swing = None
    if total_players == 2 and winner:
        losers = [seat.player_id for seat in seats if seat.player_id != winner]
        if losers:
            chip_swing = final_chips[winner] - final_chips[losers[0]]

    result = {
        "winner": winner,
        "hand_count": hand_count,
        "finish_order": finish_order,
        "final_chips": final_chips,
        "chip_swing": chip_swing,
        "chip_history": chip_history,
        "cancelled": False,
        "completed": naturally_complete,
        "winner_source": winner_source,
    }
    _emit(on_event, {
        "type": "finish",
        "hand": hand_count,
        "winner": winner,
        "result": result,
        "seats": seats,
        "chip_history": chip_history,
    })
    return result
