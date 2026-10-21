"""Scenario-table comparison of ACTUAL existing postflop policy implementations.

The simplified s/z/y input is a rank/suit-group template, not a physical deal.
We draw reproducible compatible physical-suit completions and sample each
unmodified stochastic bot. Results are empirical conditional action frequencies,
NOT solver GTO, equilibrium strategies, or exact policy probabilities.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import random
from types import SimpleNamespace

from bots import create_bot
from postflop_numeric_classifier import _tokens, classify_numeric

POLICIES = {
    "gto_postflop_v1": "GTO V1",
    "gto_postflop_30_5": "GTO 3.0/5 · adaptive",
    "gto_postflop_30_10": "GTO 3.0/10 · adaptive",
    "gto_postflop_20": "GTO 2.0 · board relative",
    "lag_postflop_v1": "LAG V1",
    "tag_postflop_v1": "TAG V1",
    "chaser_postflop_v1": "Chaser V1",
    "trapper_postflop_v1": "Trapper V1",
    "s100_postflop_v1": "S100 V1",
}
SUITS = "shdc"
NAMED = {"s": "s", "z": "h", "y": "d"}
RANKS = "23456789TJQKA"
MOVES = ("bet", "check", "raise", "call", "fold", "all_in")


def _physical_variants(hole_text, board_text, scenario_id, limit=4):
    hole = _tokens(hole_text)
    board = _tokens(board_text, board=True)
    raw = hole + board
    digest = hashlib.sha256((hole_text + "/" + board_text).encode()).digest()
    rng = random.Random(int.from_bytes(digest[:8], "big"))
    results, seen = [], set()
    for _ in range(600):
        taken, concrete = set(), []
        ok = True
        for rank, label in raw:
            suit = NAMED[label] if label else rng.choice(SUITS)
            if (rank, suit) in taken:
                if label:
                    ok = False
                    break
                candidates = [s for s in SUITS if (rank, s) not in taken]
                if not candidates:
                    ok = False
                    break
                suit = rng.choice(candidates)
            taken.add((rank, suit))
            concrete.append((rank, suit))
        if not ok:
            continue
        key = tuple(concrete)
        if key in seen:
            continue
        seen.add(key)
        # Reconstruct ALL essential actual suit repetitions and ensure they
        # classify as the same scenario as the abbreviated input.
        counts = Counter(suit for _, suit in concrete)
        recurring = list(dict.fromkeys(s for _, s in concrete if counts[s] >= 2))
        renames = {s: "szy"[i] for i, s in enumerate(recurring)}
        symbolic = [str(rank) + renames.get(suit, "") for rank, suit in concrete]
        actual = classify_numeric(" ".join(symbolic[:2]), "-".join(symbolic[2:]))
        if actual["scenario"]["id"] != scenario_id:
            continue
        converted = [(RANKS[rank - 2], suit) for rank, suit in concrete]
        results.append((converted[:2], converted[2:]))
        if len(results) >= limit:
            return results
    if not results:
        raise ValueError("Не удалось построить физическую раздачу для указанного сценария")
    return results


def _view(hole, board, context):
    n = context["opponents"]
    facing = context["to_call"] > 0
    stack = context["stack"]
    call = context["to_call"]
    if facing:
        legal = [{"type": "fold"}, {"type": "call"}, {"type": "raise", "min": max(2 * call, call + 2), "max": stack}]
    else:
        legal = [{"type": "check"}, {"type": "bet", "min": 2, "max": stack}]
    if facing and legal[-1]["min"] > legal[-1]["max"]:
        legal.pop()
    history = ([{"street": "preflop", "pid": "HERO", "type": "raise", "amount": 6}]
               if context["preflop_aggressor"] else [])
    return SimpleNamespace(
        me="HERO", street={3:"flop",4:"turn",5:"river"}[len(board)],
        position=("BTN" if context["position"] == "IP" else "BB"),
        hole_cards=hole, board=board,
        pot=context["pot"], to_call=call, min_raise=4, max_raise=stack,
        legal_actions=legal, stacks={"HERO": stack, **{f"V{i}": stack for i in range(n)}},
        opponents=[f"V{i}" for i in range(n)], acting_opponents=[f"V{i}" for i in range(n)],
        all_in_opponents=[], history=history, hand_id=1,
    )


def compare_request(data):
    if not isinstance(data, dict):
        raise ValueError("Ожидается JSON-объект")
    strategies = data.get("strategies")
    rows = data.get("rows")
    physical = data.get("mode") == "physical_catalog"
    if data.get("mode") not in (None, "physical_catalog"):
        raise ValueError("Неизвестный режим сравнения сценариев")
    raw_context = data.get("context", {})
    if (not isinstance(strategies, list) or not 1 <= len(strategies) <= 5
            or any(not isinstance(s, str) or s not in POLICIES for s in strategies)
            or len(set(strategies)) != len(strategies)):
        raise ValueError("Выберите от одной до пяти разных зарегистрированных постфлоп-стратегий")
    limit = 32 if physical else 125
    if not isinstance(rows, list) or not 1 <= len(rows) <= limit:
        raise ValueError(f"Укажите от 1 до {limit} сценариев")
    if not isinstance(raw_context, dict):
        raise ValueError("Некорректные настройки розыгрыша")
    context = {
        "opponents": raw_context.get("opponents", 1),
        "position": raw_context.get("position", "IP"),
        "preflop_aggressor": raw_context.get("preflop_aggressor", True),
        "pot": raw_context.get("pot", 24),
        "to_call": raw_context.get("to_call", 0),
        "stack": raw_context.get("stack", 80),
    }
    if (type(context["opponents"]) is not int or not 1 <= context["opponents"] <= 8
            or context["position"] not in ("IP", "OOP")
            or type(context["preflop_aggressor"]) is not bool):
        raise ValueError("Недопустимые позиция, инициатива или число соперников")
    for key, lo, hi in (("pot", 1, 10000), ("to_call", 0, 10000), ("stack", 1, 10000)):
        if (type(context[key]) not in (int, float) or not lo <= context[key] <= hi
                or int(context[key]) != context[key]):
            raise ValueError("Банк, цена Call и стек должны быть целыми положительными BB")
        context[key] = int(context[key])
    if context["to_call"] > context["stack"]:
        raise ValueError("Цена Call не может превышать стек")
    # The default context is a single baseline decision, not a full hand tree.
    if context["to_call"] > context["pot"]:
        raise ValueError("Цена Call не может превышать банк на текущей улице")
    bots = {strategy: create_bot(strategy) for strategy in strategies}
    samples = 96
    result = []
    for idx, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("Каждый сценарий должен быть объектом")
        if physical:
            from postflop_composite_classifier import (
                parse_physical_hero, classify_composite_flop
            )
            from flop_board_structure import parse_physical_flop
            hero_text, board_text = row.get("hero"), row.get("board")
            hole = tuple(parse_physical_hero(hero_text))
            board = tuple(parse_physical_flop(board_text))
            if len(set(hole + board)) != 5:
                raise ValueError("HERO и флоп содержат повторяющуюся карту")
            classified = classify_composite_flop(hero_text, board_text)
            if row.get("id") != classified["id"]:
                raise ValueError("Код сценария не соответствует физическим картам")
            scenario = {"id": classified["id"], "name": classified["name"]}
            views = [_view([(RANKS[r - 2], suit) for r, suit in hole],
                           [(RANKS[r - 2], suit) for r, suit in board], context)]
        else:
            scenario = classify_numeric(row.get("hole"), row.get("board"))
            views = [_view(hole, board, context) for hole, board in
                     _physical_variants(scenario["hole"], scenario["board"], scenario["scenario"]["id"])]
        scores = {}
        for strategy in strategies:
            counts = Counter()
            bot = bots[strategy]
            for step in range(samples):
                action = bot.act(views[step % len(views)])
                kind = getattr(action, "type", None)
                if kind not in MOVES:
                    raise RuntimeError(f"Стратегия {strategy} вернула неизвестное действие")
                if kind not in {spec["type"] for spec in views[0].legal_actions}:
                    raise RuntimeError(f"Стратегия {strategy} вернула недопустимое действие")
                counts[kind] += 1
            scores[strategy] = {kind: counts[kind] / samples for kind in MOVES if counts[kind]}
        result.append({"index": idx,
                       "scenario": scenario if physical else scenario["scenario"],
                       "actions": scores})
    return {
        "profiles": [{"id": s, "label": POLICIES[s]} for s in strategies],
        "samples_per_strategy": samples,
        "suit_variants": 1 if physical else 4,
        "method": "empirical_bot_act_physical" if physical else "empirical_bot_act",
        "context": context,
        "rows": result,
    }
