"""SKACHKOV Poker System: versioned five-block preflop strategy planner.

All 169 classes use canonical A17 V5 boxes unless a user explicitly edits
their OWN copy. Missing action data does not mean fold. Saved revisions are
immutable so an existing tournament/analysis may pin its exact version.
"""
from __future__ import annotations
import ast
import json
import os
import re
import secrets
import shutil
import statistics
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DATA_ROOT = Path(os.environ.get("POKER_DATA_DIR", str(ROOT / "output" / "replit_runs"))).resolve()
STORE = DATA_ROOT / "strategy_plans"
RANKS = "AKQJT98765432"
HANDS = tuple(a+a if r == c else a+b+"s" if r < c else b+a+"o"
              for r, a in enumerate(RANKS) for c, b in enumerate(RANKS))
COMBOS = {h: 6 if len(h) == 2 else 4 if h.endswith("s") else 12 for h in HANDS}
ACTIONS = ("fold", "open", "limp", "call", "threebet", "fourbet", "push")
SCENARIOS = {
    "rfi": ("fold", "open", "limp", "push"),
    "vs_open": ("fold", "call", "threebet", "push"),
    "vs_threebet": ("fold", "call", "fourbet", "push"),
    "vs_shove": ("fold", "call"),
    "push_fold": ("fold", "push"),
}
BUILTINS = {
    "builtin:a17_v5": "A17 V5",
    "builtin:a17_legacy": "A17 Legacy",
    "builtin:gto_heuristic": "GTO Bot (эвристика)",
    "builtin:pc_gto_80bb": "PC GTO 80bb",
    "builtin:any_two": "Any Two",
}
REF = re.compile(r"^saved:([a-f0-9]{12})@v([1-9][0-9]{0,4})$")
ID = re.compile(r"^[a-f0-9]{12}$")


def now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def boxes_v5():
    from bots.a17_ranges import A17_HAND_TO_BOX
    return dict(A17_HAND_TO_BOX)


def validate_boxes(boxes):
    if not isinstance(boxes, dict) or set(boxes) != set(HANDS):
        raise ValueError("В группировке должны присутствовать ровно 169 классов рук")
    if any(type(value) is not int or not 0 <= value <= 17 for value in boxes.values()):
        raise ValueError("Номер коробки должен быть 0 (без коробки) или A01–A17")
    # Every one of 169 classes remains in the map. Value 0 is the unassigned
    # pool; temporarily empty boxes are allowed while editing a new geometry.
    return {hand: boxes[hand] for hand in HANDS}


def validate_box_order(order):
    """Stable visual ordering, not an implicit renumbering of membership IDs."""
    if order is None:
        return list(range(1, 18))  # legacy saved plans
    if not isinstance(order, list) or len(order) != 17 or any(type(n) is not int for n in order):
        raise ValueError("Порядок коробок должен содержать 17 номеров A01–A17")
    if set(order) != set(range(1, 18)):
        raise ValueError("Порядок коробок: номера A01–A17 не должны повторяться")
    return list(order)


def positions(players):
    if type(players) is not int or not 2 <= players <= 9:
        raise ValueError("Формат стола: от 2 до 9 игроков")
    return [str(n) for n in range(players, 2, -1)] + ["SB", "BB"]


def validate_context(players, position, scenario, stack_bb=20):
    if position not in positions(players):
        raise ValueError("Позиция недоступна для данного формата стола")
    if scenario not in SCENARIOS:
        raise ValueError("Неизвестная префлоп-ситуация")
    if not isinstance(stack_bb, (float, int)) or not 1 <= stack_bb <= 1000:
        raise ValueError("Стек должен быть от 1 до 1000 BB")
    return position, scenario


def normalize_actions(actions, scenario):
    if not isinstance(actions, dict):
        raise ValueError("Действия должны быть объектом")
    if any(k not in SCENARIOS[scenario] for k in actions):
        raise ValueError("Действие несовместимо с выбранной ситуацией")
    result = {}
    for action, frequency in actions.items():
        if isinstance(frequency, bool) or not isinstance(frequency, (int, float)):
            raise ValueError("Частоты должны быть числами")
        if not 0 <= frequency <= 100:
            raise ValueError("Частоты должны быть между 0 и 100")
        if frequency > 0:
            result[action] = round(float(frequency), 2)
    if sum(result.values()) > 100.001:
        raise ValueError("Сумма частот для руки превышает 100%")
    return result


def validate_plan(raw):
    if not isinstance(raw, dict):
        raise ValueError("Неверный формат стратегии")
    name = str(raw.get("name", "")).strip()
    if not 1 <= len(name) <= 80:
        raise ValueError("Название должно содержать от 1 до 80 символов")
    n = raw.get("players", 9)
    if type(n) is not int:
        raise ValueError("Некорректное число игроков")
    position = str(raw.get("position", "3"))
    scenario = str(raw.get("scenario", "rfi"))
    stack = raw.get("stack_bb", 20)
    validate_context(n, position, scenario, stack)
    boxes = validate_boxes(raw.get("boxes"))
    box_order = validate_box_order(raw.get("box_order"))
    hands = raw.get("hands", {})
    if not isinstance(hands, dict) or any(h not in COMBOS for h in hands):
        raise ValueError("Неизвестная стартовая рука")
    clean = {h: normalize_actions(v, scenario) for h, v in hands.items()}
    return {"format": "SKACHKOV_PLAN_V1", "name": name, "players": n,
            "position": position, "scenario": scenario, "stack_bb": stack,
            "boxes": boxes, "box_order": box_order, "hands": clean}


def _gto_ranges(position, n):
    """Read the checked-in heuristic bot tiers without importing its 100MB+ evaluator.

    This extracts original EARLY/MIDDLE/LATE/BLINDS tiers from its source and
    uses the same group-selection rule; explicitly *not* solver output.
    """
    from core.table_order import position_group
    filename = ROOT / "bots" / "gto_bot.py"
    tree = ast.parse(filename.read_text(encoding="utf-8"))
    vars_ = {}
    wanted = {f"_{prefix}_T{idx}" for prefix in ("EP", "MP", "LP", "BL")
              for idx in (1, 2, 3)}
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id in wanted:
                    vars_[target.id] = ast.literal_eval(node.value)
    if len(vars_) != 12:
        raise RuntimeError("Изменились базовые чарты GTOBot; переоценка необходима")
    if n == 2 and position == "SB":
        prefix = "LP"
    else:
        group = position_group(position, n)
        prefix = {"early": "EP", "middle": "MP", "late": "LP",
                  "sb": "BL", "bb": "BL"}[group]
    result = {h: {"fold": 85, "limp": 10, "open": 5} for h in HANDS}
    for idx, values in ((1, (0, 10, 90)), (2, (10, 50, 40)), (3, (55, 30, 15))):
        for h in vars_[f"_{prefix}_T{idx}"]:
            result[h] = dict(zip(("fold", "limp", "open"), values))
    return result



def _bb_fixed_gto_vs_open(players):
    """Actual A17 and PC GTO 80bb BB fallback versus one voluntary open.

    A17PreflopBot and PCGTO80bbBot both defer BB defense to
    FixedGTOPreflopBot. Its initial BL tiers come from _gto_ranges, then
    a real preflop opponent raise applies the exact fold tightening from
    FixedGTOPreflopBot._preflop. Raise means 3-bet here, NOT an RFI open.
    This is a heuristic, NOT an A17-specific defense or solver chart.
    """
    initial = _gto_ranges("BB", players)
    result = {}
    for hand, actions in initial.items():
        fold = actions["fold"] / 100
        call = actions["limp"] / 100
        raise_ = actions["open"] / 100
        fold = min(1.0, fold + 0.15 * (0.30 + fold))
        remainder = 1.0 - fold
        total = call + raise_
        if total:
            call, raise_ = remainder * call / total, remainder * raise_ / total
        else:
            call, raise_ = remainder, 0.0
        result[hand] = {"fold": round(100 * fold, 4),
                        "call": round(100 * call, 4),
                        "threebet": round(100 * raise_, 4)}
    return result

def preset(profile, position="3", scenario="rfi", players=9, stack_bb=20):
    validate_context(players, position, scenario, stack_bb)
    if profile.startswith("saved:"):
        doc = get_saved(profile)
        if (doc["position"], doc["scenario"], doc["players"]) != (position, scenario, players):
            raise ValueError("Сохранённая стратегия привязана к своему контексту")
        return doc
    if profile not in BUILTINS:
        raise ValueError("Пресет стратегии не найден")
    from bots.a17_ranges import A17_MAX_OPEN_BOX_BY_POSITION, A17_RFI_EXTRA_BOXES_BY_POSITION
    from bots.a17_ranges_legacy import A17_HAND_TO_BOX as legacy
    boxes = boxes_v5()
    if profile == "builtin:a17_legacy":
        boxes = dict(legacy)
    if profile == "builtin:any_two":
        pseudo_action = {"rfi":"open","vs_open":"call","vs_threebet":"call",
                         "vs_shove":"call","push_fold":"push"}[scenario]
        hands = {h: {pseudo_action: 100} for h in HANDS}
    elif profile == "builtin:gto_heuristic":
        hands = _gto_ranges(position, players) if scenario == "rfi" else {}
    elif profile == "builtin:pc_gto_80bb":
        from bots.pc_gto_80bb_ranges import rfi_actions
        hands = ({h: rfi_actions(h, position, players) for h in HANDS}
                 if scenario == "rfi" and position != "BB" else
                 _bb_fixed_gto_vs_open(players) if scenario == "vs_open" and position == "BB" else {})
    elif position == "BB" and scenario == "vs_open":
        hands = _bb_fixed_gto_vs_open(players)
    elif scenario == "rfi" and position in A17_MAX_OPEN_BOX_BY_POSITION:
        cutoff = A17_MAX_OPEN_BOX_BY_POSITION[position]
        extra = A17_RFI_EXTRA_BOXES_BY_POSITION.get(position, ())
        hands = {}
        for h in HANDS:
            b = boxes[h]
            if position == "SB" and b == 17:
                hands[h] = {"limp": 100}
            else:
                hands[h] = {"open": 100} if b <= cutoff or b in extra else {"fold": 100}
    elif scenario == "vs_threebet":
        hands = {h: ({"call": 50, "fourbet": 50} if boxes[h] in (1,2,3,4,5,6,7,9)
                      else {"fold": 100}) for h in HANDS}
    else:
        hands = {}  # unspecified scenario is NOT fold
    return {"format": "SKACHKOV_PLAN_V1", "id": profile, "version": 0,
            "name": BUILTINS[profile], "players": players, "position": position,
            "scenario": scenario, "stack_bb": stack_bb, "boxes": boxes,
            "box_order": list(range(1, 18)), "hands": hands,
            "range_origin": ("gto_fixed_bb_vs_open"
                             if position == "BB" and scenario == "vs_open"
                             and profile in ("builtin:a17_v5", "builtin:a17_legacy",
                                             "builtin:pc_gto_80bb") else None),
            "readonly": True, "source": "builtin"}


def _file(id_, version):
    if not ID.fullmatch(id_) or type(version) is not int or not 1 <= version <= 99999:
        raise ValueError("Некорректная версия стратегии")
    return STORE / id_ / f"v{version:05d}.json"


def get_saved(ref):
    match = REF.fullmatch(ref)
    if not match:
        raise ValueError("Некорректная ссылка на стратегию")
    path = _file(match.group(1), int(match.group(2)))
    if not path.is_file():
        raise KeyError(ref)
    data = json.loads(path.read_text(encoding="utf-8"))
    return {**data, "readonly": False}


def list_saved():
    if not STORE.is_dir():
        return []
    records = []
    for folder in sorted(STORE.iterdir()):
        if not folder.is_dir() or not ID.fullmatch(folder.name):
            continue
        versions = sorted(folder.glob("v[0-9][0-9][0-9][0-9][0-9].json"))
        if not versions:
            continue
        doc = json.loads(versions[-1].read_text(encoding="utf-8"))
        records.append({"id": doc["id"], "version": doc["version"], "ref": doc["ref"],
                        "name": doc["name"], "position": doc["position"],
                        "scenario": doc["scenario"], "players": doc["players"],
                        "updated": doc.get("updated")})
    return sorted(records, key=lambda r:r["updated"] or "", reverse=True)


def save_plan(raw, parent=None):
    clean = validate_plan(raw)
    if parent is not None:
        previous = get_saved(parent)
        id_ = previous["id"]
        if (previous["players"], previous["position"], previous["scenario"]) != (
                clean["players"], clean["position"], clean["scenario"]):
            raise ValueError("Для другого контекста сохрани стратегию как новую")
        version = previous["version"] + 1
        if _file(id_, version).exists():
            raise RuntimeError("Стратегия обновлена в другом окне: обнови список")
    else:
        id_, version = secrets.token_hex(6), 1
    if version > 99999:
        raise ValueError("Достигнут лимит версий")
    record = {**clean, "id": id_, "version": version,
              "ref": f"saved:{id_}@v{version}",
              "created": previous.get("created", now()) if parent else now(),
              "updated": now(),
              "source": "user"}
    target = _file(id_, version)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as stream:
        json.dump(record, stream, ensure_ascii=False, separators=(",", ":"))
    return {**record, "readonly": False}


def delete_plan(id_):
    if not ID.fullmatch(id_):
        raise ValueError("Некорректный ID")
    folder = STORE / id_
    if not folder.is_dir():
        raise KeyError(id_)
    trash = STORE / ".trash"
    trash.mkdir(parents=True, exist_ok=True)
    shutil.move(str(folder), str(trash / (id_ + "_" + secrets.token_hex(3))))
    return {"deleted": id_}


def range_weights(doc, selector="active"):
    """Weights 0..1 for each class; blank hands are NOT folded hands."""
    hands = doc.get("hands", {})
    if selector != "active" and selector not in ACTIONS:
        raise ValueError("Неизвестная выборка действий")
    result = {}
    for h, dist in hands.items():
        if selector == "active":
            freq = sum(v for action, v in dist.items() if action != "fold")
        else:
            freq = dist.get(selector, 0)
        if freq > 0:
            result[h] = freq / 100.0
    return result


def compare_docs(hero, villain):
    a, b = range_weights(hero), range_weights(villain)
    overlap = sum(COMBOS[h]*min(a.get(h, 0), b.get(h, 0)) for h in HANDS)
    union = sum(COMBOS[h]*max(a.get(h, 0), b.get(h, 0)) for h in HANDS)
    hero_mass = sum(COMBOS[h]*a.get(h, 0) for h in HANDS)
    villain_mass = sum(COMBOS[h]*b.get(h, 0) for h in HANDS)
    differing = sum(COMBOS[h] for h in HANDS
                    if h in hero["hands"] and h in villain["hands"]
                    and hero["hands"][h] != villain["hands"][h])
    return {"overlap_pct": round(100*overlap/union, 2) if union else None,
            "hero_pct": round(100*hero_mass/1326, 2),
            "villain_pct": round(100*villain_mass/1326, 2),
            "shared_combos_weighted": round(overlap, 2),
            "only_hero_combos_weighted": round(hero_mass-overlap, 2),
            "only_villain_combos_weighted": round(villain_mass-overlap, 2),
            "different_action_combos": differing}
