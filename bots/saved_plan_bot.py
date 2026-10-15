"""Run immutable, user-edited preflop range versions from the strategy planner.

Token `plan_<id>_v<version>` is deliberately colon-free so the existing
`split:pre:post` specification remains unambiguous. Session snapshots
are read before opening the global store: deleting/editing the strategy
later cannot silently change an already-started tournament.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import random
import re

import planner_core as plans
from bots.gto_bot import _hand_key
from bots.gto_fixed_bot import FixedGTOPreflopBot
from core.bot_api import BotAdapter

PLAN_TOKEN = re.compile(r"^plan_([a-f0-9]{12})_v([1-9][0-9]{0,4})$")
BASE_POLICIES = {
    "builtin:a17_v5": "a17_preflop",
    "builtin:a17_legacy": "a17_preflop_legacy",
    "builtin:gto_heuristic": "gto",
    "builtin:pc_gto_80bb": "pc_gto_80bb",
    "builtin:any_two": "a17_preflop",
}


def token_for(ref: str) -> str:
    match = plans.REF.fullmatch(ref)
    if not match:
        raise ValueError("Неизвестная сохранённая версия стратегии")
    return f"plan_{match.group(1)}_v{int(match.group(2))}"


def ref_for(token: str) -> str:
    match = PLAN_TOKEN.fullmatch(token)
    if not match:
        raise ValueError("Некорректный идентификатор стратегии")
    return f"saved:{match.group(1)}@v{int(match.group(2))}"


def saved_document(token: str) -> dict:
    ref = ref_for(token)
    directory = os.environ.get("POKER_PLAN_SNAPSHOT_DIR")
    if directory:
        file = Path(directory) / (token + ".json")
        if not file.is_file():
            raise FileNotFoundError("В сессии отсутствует зафиксированная версия: " + token)
        document = json.loads(file.read_text(encoding="utf-8"))
        if document.get("ref") != ref:
            raise ValueError("В сессии нарушена идентичность сохранённой стратегии")
    else:
        document = plans.get_saved(ref)
    # Support original single-position V1 plans without mutating source.
    if "contexts" not in document:
        key = plans.context_key(document["players"], document["position"], document["scenario"])
        document = {**document, "contexts": {key: {
            "hands": document["hands"], "stack_bb": document["stack_bb"]}}}
    return document


def detect_scenario(view):
    """Do not apply an unopened (RFI) chart to a raised or limped pot."""
    if view.street != "preflop":
        return None
    entries = [
        item for item in (view.history or ())
        if isinstance(item, dict) and item.get("street") == "preflop"
        and item.get("type") in ("call", "raise", "bet", "all_in")
    ]
    if not entries:
        return "rfi" if str(view.position).upper() != "BB" else None
    if view.to_call <= 0:
        return None
    if entries[-1].get("pid") == view.me:
        return None
    if entries[-1].get("type") == "all_in":
        return "vs_shove"
    aggressive = sum(item["type"] in ("raise", "bet") for item in entries)
    if aggressive == 1 and len(entries) == 1:
        return "vs_open"
    if aggressive == 2 and entries[-1].get("type") in ("raise", "bet"):
        return "vs_threebet"
    return None


class SavedPlanPreflopBot(BotAdapter):
    """Execute hand/action percentages of exact saved positional contexts.

    Missing context or unassigned hand delegates to the source strategy.
    Percentages summing below 100 delegate the residual probability too.
    No inference of unspecified actions, BB chart or stack-dependent solver.
    """

    def __init__(self, token: str):
        self.token = token
        self.document = saved_document(token)
        from bots import create_bot
        original = self.document.get("base_profile", "builtin:a17_v5")
        self.base_bot = create_bot(BASE_POLICIES.get(original, "a17_preflop"))
        self.helpers = FixedGTOPreflopBot()

    def act(self, view):
        scenario = detect_scenario(view)
        if not scenario:
            return self.base_bot.act(view)
        n = len(view.stacks)
        position = str(view.position).upper()
        if position not in plans.positions(n):
            return self.base_bot.act(view)
        key = plans.context_key(n, position, scenario)
        slot = self.document["contexts"].get(key)
        if slot is None:
            return self.base_bot.act(view)
        hole = view.hole_cards
        if not hole or len(hole) < 2:
            return self.base_bot.act(view)
        hand = _hand_key(hole[0][0], hole[1][0], hole[0][1] == hole[1][1])
        freqs = slot.get("hands", {}).get(hand)
        if not freqs:
            return self.base_bot.act(view)
        roll = random.random() * 100
        for name, percentage in freqs.items():
            roll -= percentage
            if roll < 0:
                return self._take_action(name, view)
        return self.base_bot.act(view)

    def _take_action(self, action, view):
        legal = view.legal_actions
        if action == "fold":
            return self.helpers._do_fold_or_check(legal, view.to_call)
        if action in ("limp", "call"):
            return self.helpers._do_call_or_check(legal, view.to_call)
        if action == "push":
            for item in legal:
                if item["type"] == "raise":
                    return self.helpers._do_raise(legal, view.pot, sizing_frac=10**8)
            return self.helpers._do_call_or_check(legal, view.to_call)
        if action in ("open", "threebet", "fourbet"):
            return self.helpers._do_raise(legal, view.pot, sizing_frac=0.70)
        raise ValueError("Неизвестное действие сохранённой стратегии: " + action)

    def reset_memory(self):
        reset = getattr(self.base_bot, "reset_memory", None)
        if callable(reset):
            reset()
