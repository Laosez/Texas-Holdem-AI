"""Range-conditioned postflop Monte Carlo using the actual legacy betting engine.

Model boundary (important): participant ranges and entry probabilities are
applied before the hand; the preflop action is then scripted as one hero open
and calls from all admitted opponents.  Hero postflop policy and each villain
policy play REAL flop/turn/river actions through core.engine.Table, including
folds, raises, split pots and side pots. This is conditional raised-pot chip EV,
not tournament ICM or a solution to the full preflop betting tree.

"none" explicitly disables behavioral EV (equity-only), never silently uses
a fictional opponent policy. Showdown equity is evaluated on the SAME
sampled deals without regarding which players later fold.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
from dataclasses import dataclass

import planner_core as core
import planner_equity as eq

PROFILE_NAMES = {
    "gto": "gto_postflop_v1",
    "tag": "tag_postflop_v1",
    "lag": "lag_postflop_v1",
    "chaser": "chaser_postflop_v1",
    "trapper": "trapper_postflop_v1",
    "random": "random",
    "none": None,
}
RANKS = "23456789TJQKA"
SUITS = "cdhs"
PREFLOP_BB = 2
STARTING_STACK_BB = 20


def legal_profile(value):
    if value not in PROFILE_NAMES:
        raise ValueError("Неизвестная постфлоп-стратегия")
    return value


def validate_request(raw):
    """Use existing strict per-opponent range validation without modifying it."""
    from planner_api import _validate_request
    base = _validate_request({**raw, "model": "selected"})
    base["hero_postflop"] = legal_profile(raw.get("hero_postflop", "gto"))
    base["hero_position"] = str(raw.get("hero_position", "3"))
    core.validate_context(9, base["hero_position"], "rfi")
    base["hero_stack_bb"] = int(raw.get("hero_stack_bb", STARTING_STACK_BB))
    if type(raw.get("hero_stack_bb", STARTING_STACK_BB)) is not int or not 10 <= base["hero_stack_bb"] <= 200:
        raise ValueError("Стек для постфлоп EV: 10–200 BB")
    profiles = []
    for item in raw["opponents"]:
        profiles.append(legal_profile(item.get("postflop", "none")))
    for opponent, profile in zip(base["opponents"], profiles):
        opponent["postflop"] = profile
    hand = raw.get("hand")
    if hand is not None and hand not in core.HANDS:
        raise ValueError("Некорректная стартовая рука")
    base["hand"] = hand
    return base


def _card(value):
    return (RANKS[value // 4], SUITS[value % 4])


def _seat_sort(position):
    """Dealer-first circular ordering of 9-max position labels."""
    value = str(position)
    # 3 is BTN, then SB and BB, then UTG ... CO.
    labels = ["3", "SB", "BB", "9", "8", "7", "6", "5", "4"]
    return labels.index(value) if value in labels else 9


class _FixedDeal:
    """Provide exact sampled hole cards and full board to Table via shuffle()."""
    def __init__(self, players, holes, board, seed):
        self.players = players
        self.holes = holes
        self.board = board
        self.rng = random.Random(seed)

    def shuffle(self, deck):
        deal = [c for pid in self.players for c in self.holes[pid]] + list(self.board)
        if len(set(deal)) != len(deal):
            raise RuntimeError("Sampled hand contains a duplicate physical card")
        tail = [_card(c) for c in deal]
        taken = set(tail)
        other = [c for c in deck if c not in taken]
        self.rng.shuffle(other)
        deck[:] = other + tail[::-1]


class _Policy:
    def __init__(self, kind, position, hero=False):
        from bots import create_bot
        self.postflop = create_bot(PROFILE_NAMES[kind])
        self.position = position
        self.hero = hero
        self.opened = False
        self.folded_after_flop = False

    def act(self, view):
        from core.bot_api import Action
        if view.street == "preflop":
            if self.hero and not self.opened:
                for action in view.legal_actions:
                    if action["type"] == "raise":
                        self.opened = True
                        return Action("raise", max(action["min"], min(action["max"], 5)))
                    if action["type"] == "bet":
                        self.opened = True
                        return Action("bet", max(action["min"], min(action["max"], 5)))
            return Action("call" if view.to_call else "check")
        # Original 9-max position remains an input to the behavior policy;
        # the Table has fewer active seats due to conditional participation.
        view.position = "BTN" if str(self.position) == "3" else str(self.position)
        action = self.postflop.act(view)
        if self.hero and action.type == "fold":
            self.folded_after_flop = True
        return action


def _entry_probability(mode, pct, weighted_range, exact_hero):
    if mode == "never":
        return 0.
    if mode == "always":
        return 1.
    if mode == "manual":
        return float(pct) / 100.
    return weighted_range.probability_versus_hero(exact_hero)


def _draw_case(hand, ranges, opponents, rng):
    """Range-weighted conditional sample, rejecting overlapping physical cards."""
    for _ in range(200):
        hero = rng.choice(eq.HAND_COMBOS[hand])
        used = set(hero)
        picked = [("HERO", hero, None)]
        failed = False
        for idx, (weighted, spec) in enumerate(zip(ranges, opponents), 1):
            p = _entry_probability(spec["entry_mode"], spec["entry_pct"], weighted, hero)
            if rng.random() >= p:
                continue
            cards = weighted.sample(rng)
            if cards[0] in used or cards[1] in used:
                failed = True
                break
            used.update(cards)
            picked.append((f"V{idx}", cards, spec))
        if failed:
            continue
        board = rng.sample([c for c in eq.ALL_CARDS if c not in used], 5)
        return picked, board
    raise RuntimeError("Не удалось совместно выбрать карты диапазонов: слишком узкие/конфликтующие диапазоны")


def _showdown_share(picked, board):
    own = eq.score_seven((*picked[0][1], *board))
    others = [eq.score_seven((*p[1], *board)) for p in picked[1:]]
    best = max((own, *others))
    return 1. / (1. + sum(score == best for score in others)) if own == best else 0.


def _play_case(picked, board, hero_profile, hero_position, stack_bb, seed):
    """One complete legal preflop-to-river betting hand with sampled cards."""
    from core.engine import Seat, Table

    entries = [("HERO", hero_position, picked[0][1])]
    entries.extend((pid, entry["position"], cards) for pid, cards, entry in picked[1:])
    entries.sort(key=lambda x: (_seat_sort(x[1]), x[0]))
    ring = [x[0] for x in entries]
    holes = {pid: cards for pid, _, cards in entries}
    policies = {}
    entry_lookup = {pid: spec for pid, _, spec in picked[1:]}
    for pid, pos, _ in entries:
        kind = hero_profile if pid == "HERO" else entry_lookup[pid]["postflop"]
        policies[pid] = _Policy(kind, pos, hero=(pid == "HERO"))

    table = Table(rng=_FixedDeal(ring, holes, board, seed))
    history = {"showdown": False}
    def finish(hand_id, net, bb, players, winners):
        history["showdown"] = bool(players)
    table.on_hand_end = finish

    chips = int(stack_bb) * 2
    seats = [Seat(pid, chips) for pid in ring]
    outcome = table.play_hand(seats, small_blind=1, big_blind=2,
                              dealer_index=0, bot_for=policies)
    if sum(outcome.values()) != 0:
        raise RuntimeError("Payout conservation failed")
    return outcome["HERO"] / 2., history["showdown"] and not policies["HERO"].folded_after_flop


def calculate(raw, progress=None):
    payload = validate_request(raw)
    src, provenance = eq.build_ranges(payload["opponents"], "selected")
    disabled = payload["hero_postflop"] == "none" or any(
        spec["postflop"] == "none" and spec["entry_mode"] != "never"
        for spec in payload["opponents"]
    )
    result = {"model": "postflop_line_rollout_v1",
              "equity": {}, "ev_bb": {}, "showdown_pct": {}, "fold_win_pct": {},
              "simulations_per_hand": payload["trials"] * payload["cycles"],
              "behavioral_ev_enabled": not disabled,
              "note": ("EV не рассчитывается: для каждого активного игрока выбери постфлоп-стратегию"
                       if disabled else
                       "Chip EV в BB при выбранных диапазонах, принудительном входе и стандартном hero open; без ICM и оптимизации префлопа"),
              "opponents": provenance}
    selected_hands = [payload["hand"]] if payload["hand"] else core.HANDS
    # Common random *deals* for all postflop policies: switching GTO/TAG/LAG
    # does not re-roll hole cards, entrants or board. Action randomness is
    # independent of the deal stream.
    deal_only = {
        "opponents": [{k:v for k,v in item.items() if k!="postflop"}
                      for item in payload["opponents"]],
        "trials":payload["trials"],"cycles":payload["cycles"],
    }
    salt = hashlib.sha256(json.dumps(deal_only,ensure_ascii=False,
                      sort_keys=True).encode()).digest()
    n = payload["trials"] * payload["cycles"]
    entry_counts = [0] * (len(payload["opponents"])+1)
    for index, hand in enumerate(selected_hands):
        seed = int.from_bytes(hashlib.sha256(salt + hand.encode()).digest()[:8], "big")
        rng = random.Random(seed)
        policy_seed_rng = random.Random(seed ^ 0x6C616773)
        samples = 0
        accepted = 0
        ev_total = 0.
        showdown_total = 0
        fold_win_total = 0
        while samples < n:
            picked, board = _draw_case(hand, src, payload["opponents"], rng)
            entry_counts[len(picked)-1] += 1
            if len(picked) <= 1:
                # Everyone folded before the flop: win the posted blinds only.
                if not disabled:
                    ev_total += 1.5
                    fold_win_total += 1
                samples += 1
                continue
            result["equity"].setdefault(hand, 0.)
            result["equity"][hand] += _showdown_share(picked, board)
            accepted += 1
            if not disabled:
                chip_ev, at_showdown = _play_case(
                    picked, board, payload["hero_postflop"],
                    payload["hero_position"], payload["hero_stack_bb"],
                    policy_seed_rng.randrange(1 << 50)
                )
                ev_total += chip_ev
                showdown_total += at_showdown
                fold_win_total += bool(not at_showdown and chip_ev > 0)
            samples += 1
        result["equity"][hand] = round(
            100. * result["equity"].get(hand, 0.) / accepted, 3
        ) if accepted else None
        result["ev_bb"][hand] = round(ev_total / n, 4) if not disabled else None
        result["showdown_pct"][hand] = round(100 * showdown_total / n, 2) if not disabled else None
        result["fold_win_pct"][hand] = round(100 * fold_win_total / n, 2) if not disabled else None
        if progress:
            progress(index + 1, len(selected_hands))
    total_entries = sum(entry_counts)
    result["entry_counts_pct"] = [round(100 * x / total_entries, 2)
                                   for x in entry_counts]
    return result
