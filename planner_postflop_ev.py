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
import multiprocessing
import random
import threading
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass

import planner_core as core
import planner_equity as eq

PROFILE_NAMES = {
    "gto": "gto_postflop_v1",
    "gto2": "gto_postflop_v2",
    "gto3": "gto_postflop_v3",
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
# Built-in postflop bots use random.random(); preserve reproducibility per deal.
_ROLLOUT_RNG_LOCK = threading.RLock()


def legal_profile(value):
    if value not in PROFILE_NAMES:
        raise ValueError("Неизвестная постфлоп-стратегия")
    return value


def validate_request(raw):
    """Use existing strict per-opponent range validation without modifying it."""
    from planner_api import _validate_request
    trials = raw.get("trials", 200)
    if type(trials) is not int or not 50 <= trials <= 64000:
        raise ValueError("Число симуляций: 50–64000 на руку")
    # Full matrix and single-hand analysis both accept up to 64000 trials.
    # Full matrices run across bounded independent processes.
    # Historical all-in equity endpoint retains its existing 50–2000
    # contract; only the postflop rollout accepts deep single-hand samples.
    base = _validate_request({**raw, "model": "selected",
                              "trials": min(trials, 2000)})
    base["trials"] = trials
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
        self.fold_street = None

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
            self.fold_street = view.street
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
    """Choose hero and entry events once; then condition cards on that lineup.

    Redrawing the entry events after a blocker collision underweights crowded
    multiway pots. Conditional rejection is instead confined to the fixed
    lineup, so the externally specified entry probabilities are preserved.
    """
    hero = rng.choice(eq.HAND_COMBOS[hand])
    active = []
    for idx, (weighted, spec) in enumerate(zip(ranges, opponents), 1):
        p = _entry_probability(spec["entry_mode"], spec["entry_pct"], weighted, hero)
        if rng.random() < p:
            active.append((idx, weighted, spec))
    # Fail explicitly for impossible physical combinations, rather than
    # silently redefining the distribution by discarding entire lineups.
    cards = eq.sample_compatible_hands([o[1] for o in active], hero, rng)
    picked = [("HERO", hero, None)]
    picked.extend((f"V{idx}", pair, spec)
                  for (idx, _, spec), pair in zip(active, cards))
    used = set(hero)
    for pair in cards:
        used.update(pair)
    board = rng.sample([c for c in eq.ALL_CARDS if c not in used], 5)
    return picked, board



def _uncontested_net_bb(hero_position):
    """Net blind profit when every other player folds, with no antes."""
    if hero_position == "SB":
        return 1.0  # Hero posted 0.5 BB; receives villain's 1 BB.
    if hero_position == "BB":
        return 0.5  # Hero posted 1 BB; receives villain's 0.5 BB.
    return 1.5      # Neither blind belongs to Hero.


def _showdown_share(picked, board):
    own = eq.score_seven_fast((*picked[0][1], *board))
    others = [eq.score_seven_fast((*p[1], *board)) for p in picked[1:]]
    best = max((own, *others))
    return 1. / (1. + sum(score == best for score in others)) if own == best else 0.


def _play_case(picked, board, hero_profile, hero_position, stack_bb, seed, *, detail=False, metrics=False):
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
        if detail:
            history["players"] = tuple(players)
            history["winners"] = tuple(winners)
    table.on_hand_end = finish
    pot_state = {"bb": None}
    if metrics:
        table.on_hand_pot = lambda hand_id, chips, bb: pot_state.__setitem__(
            "bb", chips / float(bb))

    chips = int(stack_bb) * 2
    seats = [Seat(pid, chips) for pid in ring]
    with _ROLLOUT_RNG_LOCK:
        old_state = random.getstate()
        try:
            random.seed(seed ^ 0x504F5354)
            outcome = table.play_hand(seats, small_blind=1, big_blind=2,
                                      dealer_index=0, bot_for=policies)
        finally:
            random.setstate(old_state)
    if sum(outcome.values()) != 0:
        raise RuntimeError("Payout conservation failed")
    chip_ev = outcome["HERO"] / 2.
    showdown = history["showdown"] and not policies["HERO"].folded_after_flop
    if detail:
        from planner_ev_decomposition import classify_case
        classified = classify_case(
            picked, board, history, policies["HERO"].fold_street, chip_ev)
        return (chip_ev, showdown, classified, pot_state["bb"]) if metrics else (
            chip_ev, showdown, classified)
    return (chip_ev, showdown, pot_state["bb"]) if metrics else (chip_ev, showdown)


def calculate(raw, progress=None, *, _hands=None, _return_raw=False,
              _prepared=None):
    payload = validate_request(raw)
    src, provenance = (_prepared if _prepared is not None
                       else eq.build_ranges(payload["opponents"], "selected"))
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
    selected_hands = [payload["hand"]] if payload["hand"] else (list(_hands) if _hands is not None else core.HANDS)
    # Detailed outcomes only for the one selected hand, to keep 169-hand
    # matrix runs compact and avoid coupling existing benchmark callers.
    decomposition = None
    if payload["hand"] and not disabled:
        from planner_ev_decomposition import EVDecomposition
        decomposition = EVDecomposition(payload["hand"])
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
    entry_pots = [0.] * len(entry_counts)
    entry_ev_sum = [0.] * len(entry_counts)
    entry_ev_sq = [0.] * len(entry_counts)
    # Track the second moment as well as the mean; pot size alone cannot
    # determine Monte Carlo EV precision.
    hand_ev_squared = {}
    for index, hand in enumerate(selected_hands):
        seed = int.from_bytes(hashlib.sha256(salt + hand.encode()).digest()[:8], "big")
        rng = random.Random(seed)
        policy_seed_rng = random.Random(seed ^ 0x6C616773)
        samples = 0
        accepted = 0
        ev_total = 0.
        showdown_total = 0
        fold_win_total = 0
        ev_squared_total = 0.
        while samples < n:
            picked, board = _draw_case(hand, src, payload["opponents"], rng)
            entrants = len(picked) - 1
            entry_counts[entrants] += 1
            if len(picked) <= 1:
                # Net winnings exclude Hero's own blind (SB/BB).
                uncontested = _uncontested_net_bb(payload["hero_position"])
                if not disabled:
                    ev_total += uncontested
                    ev_squared_total += uncontested ** 2
                    entry_ev_sum[0] += uncontested
                    entry_ev_sq[0] += uncontested ** 2
                    fold_win_total += 1
                    if decomposition:
                        decomposition.add(uncontested,"uncontested")
                entry_pots[0] += 1.5  # SB 0.5 + BB 1.0
                samples += 1
                continue
            result["equity"].setdefault(hand, 0.)
            result["equity"][hand] += _showdown_share(picked, board)
            accepted += 1
            if not disabled:
                rollout = _play_case(
                    picked, board, payload["hero_postflop"],
                    payload["hero_position"], payload["hero_stack_bb"],
                    policy_seed_rng.randrange(1 << 50), detail=bool(decomposition),
                    metrics=True
                )
                chip_ev, at_showdown = rollout[:2]
                pot_bb = rollout[-1]
                if pot_bb is None:
                    raise RuntimeError("Final pot telemetry missing")
                entry_pots[entrants] += pot_bb
                entry_ev_sum[entrants] += chip_ev
                entry_ev_sq[entrants] += chip_ev ** 2
                ev_squared_total += chip_ev ** 2
                if decomposition:
                    event,risk,flush,group,matchup,reason = rollout[2]
                    decomposition.add(chip_ev,event,risk=risk,flush=flush,
                                      group=group,matchup=matchup,reason=reason)
                ev_total += chip_ev
                showdown_total += at_showdown
                fold_win_total += bool(not at_showdown and chip_ev > 0)
            samples += 1
        result["equity"][hand] = round(
            100. * result["equity"].get(hand, 0.) / accepted, 3
        ) if accepted else None
        result["ev_bb"][hand] = round(ev_total / n, 4) if not disabled else None
        if not disabled and n > 1:
            sigma2 = max(0., (ev_squared_total - ev_total**2/n)/(n-1))
            hand_ev_squared[hand] = round(1.96 * math.sqrt(sigma2/n), 4)
        result["showdown_pct"][hand] = round(100 * showdown_total / n, 2) if not disabled else None
        result["fold_win_pct"][hand] = round(100 * fold_win_total / n, 2) if not disabled else None
        if progress:
            progress(index + 1, len(selected_hands))
    if payload["hand"]:
        result["decomposition"] = decomposition.result() if decomposition else None
    total_entries = sum(entry_counts)
    result["entry_counts_pct"] = [round(100 * x / total_entries, 2)
                                   for x in entry_counts]
    result["entry_n_samples"] = entry_counts
    result["entry_pot_bb"] = [round(entry_pots[k]/v,3) if v and
                              (not disabled or k==0) else None
                              for k,v in enumerate(entry_counts)]
    result["entry_ev_sd_bb"] = [
        round(math.sqrt(max(0.,(entry_ev_sq[k] -
            entry_ev_sum[k]**2/v)/(v-1))),5)
        if v>1 and not disabled else None
        for k,v in enumerate(entry_counts)
    ]
    result["ev_ci95_bb"] = hand_ev_squared if not disabled else {}
    result["entry_stats_note"] = (
        "Средний банк = фактический финальный банк (все ставки), BB. "
        "σ EV оценивается по фактическим net BB; прогноз ±95% для N прогонов "
        "использует ожидаемое N × P(числа активных соперников) и "
        "является приближением для одной руки. "
        "Для полной матрицы σ объединяет разные классы рук."
    )
    if _return_raw:
        # Combine sufficient statistics before deriving aggregate SD.
        result["_raw_stats"] = {
            "entry_counts": entry_counts,
            "entry_pots": entry_pots,
            "entry_ev_sum": entry_ev_sum,
            "entry_ev_sq": entry_ev_sq,
        }
    return result


def _single_batch(cases, hero_profile, hero_position, stack_bb, disabled):
    """Evaluate ready-made deterministic deals in a child process.

    All deals and policy seeds are generated in the parent, in the exact
    serial order. Results are returned in input order for identical EV,
    CI and single-hand decomposition independently of worker scheduling.
    """
    out = []
    uncontested = _uncontested_net_bb(hero_position)
    for picked, board, seed in cases:
        if len(picked) == 1:
            out.append((None, uncontested if not disabled else None,
                        False, 1.5, ("uncontested", None, None, "pre_win", None,
                         ("pre_uncontested", "Все соперники не вошли в банк"))))
            continue
        share = _showdown_share(picked, board)
        if disabled:
            out.append((share, None, False, None, None))
            continue
        net, showdown, classification, pot = _play_case(
            picked, board, hero_profile, hero_position, stack_bb,
            seed, detail=True, metrics=True)
        if pot is None:
            raise RuntimeError("Final pot telemetry missing")
        out.append((share, net, showdown, pot, classification))
    return out


def _single_parallel(raw, progress, workers, batch_size=256):
    """Multi-core one-hand EV with unchanged cards, seeds and attribution."""
    payload = validate_request(raw)
    if not payload["hand"]:
        raise ValueError("Для пакетного расчёта требуется одна рука")
    src, provenance = eq.build_ranges(payload["opponents"], "selected")
    disabled = payload["hero_postflop"] == "none" or any(
        spec["postflop"] == "none" and spec["entry_mode"] != "never"
        for spec in payload["opponents"])
    deal_only = {
        "opponents": [{k: v for k, v in item.items() if k != "postflop"}
                      for item in payload["opponents"]],
        "trials": payload["trials"], "cycles": payload["cycles"],
    }
    salt = hashlib.sha256(json.dumps(
        deal_only, ensure_ascii=False, sort_keys=True).encode()).digest()
    seed = int.from_bytes(hashlib.sha256(
        salt + payload["hand"].encode()).digest()[:8], "big")
    rng = random.Random(seed)
    policy_rng = random.Random(seed ^ 0x6C616773)
    n = payload["trials"] * payload["cycles"]
    entry_counts = [0] * (len(src) + 1)
    entry_pots = [0.] * len(entry_counts)
    entry_ev_sum = [0.] * len(entry_counts)
    entry_ev_sq = [0.] * len(entry_counts)
    from planner_ev_decomposition import EVDecomposition
    decomposition = EVDecomposition(payload["hand"]) if not disabled else None
    ev_total = ev_squared = eq_total = 0.
    accepted = showdown_total = fold_win_total = completed = 0
    result = {
        "model": "postflop_line_rollout_v1",
        "equity": {}, "ev_bb": {}, "showdown_pct": {}, "fold_win_pct": {},
        "simulations_per_hand": n, "behavioral_ev_enabled": not disabled,
        "note": ("EV не рассчитывается: для каждого активного игрока выбери постфлоп-стратегию"
                 if disabled else
                 "Chip EV в BB при выбранных диапазонах, принудительном входе и стандартном hero open; без ICM и оптимизации префлопа"),
        "opponents": provenance,
    }
    # Bound in-flight input data: each future carries at most batch_size deals.
    max_inflight = max(2, 2 * workers)
    pending = []
    produced = 0
    with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=multiprocessing.get_context("spawn")) as pool:
        while produced < n or pending:
            while produced < n and len(pending) < max_inflight:
                batch = []
                for _ in range(min(batch_size, n - produced)):
                    picked, board = _draw_case(
                        payload["hand"], src, payload["opponents"], rng)
                    # Match the serial PRNG: a policy seed is consumed only
                    # when the hero faces a real opponent and EV is enabled.
                    policy_seed = (policy_rng.randrange(1 << 50)
                                   if len(picked) > 1 and not disabled else 0)
                    batch.append((picked, board, policy_seed))
                pending.append((batch, pool.submit(
                    _single_batch, batch, payload["hero_postflop"],
                    payload["hero_position"], payload["hero_stack_bb"],
                    disabled)))
                produced += len(batch)
            batch, task = pending.pop(0)
            outcomes = task.result()
            for (picked, _, _), (share, net, showdown, pot, classified) in zip(batch, outcomes):
                entrants = len(picked) - 1
                entry_counts[entrants] += 1
                if entrants:
                    eq_total += share
                    accepted += 1
                if entrants == 0:
                    entry_pots[0] += 1.5
                if not disabled:
                    ev_total += net
                    ev_squared += net ** 2
                    if entrants:
                        entry_pots[entrants] += pot
                    entry_ev_sum[entrants] += net
                    entry_ev_sq[entrants] += net ** 2
                    if entrants == 0:
                        fold_win_total += 1
                    else:
                        showdown_total += showdown
                        fold_win_total += bool(not showdown and net > 0)
                    event, risk, flush, group, matchup, reason = classified
                    decomposition.add(net, event, risk=risk, flush=flush,
                                      group=group, matchup=matchup, reason=reason)
                completed += 1
            if progress:
                progress(completed, n)
    hand = payload["hand"]
    result["equity"][hand] = round(100. * eq_total / accepted, 3) if accepted else None
    result["ev_bb"][hand] = round(ev_total / n, 4) if not disabled else None
    result["showdown_pct"][hand] = round(100 * showdown_total / n, 2) if not disabled else None
    result["fold_win_pct"][hand] = round(100 * fold_win_total / n, 2) if not disabled else None
    result["decomposition"] = decomposition.result() if decomposition else None
    result["ev_ci95_bb"] = (
        {hand: round(1.96 * math.sqrt(max(
            0., (ev_squared - ev_total**2 / n) / (n - 1)) / n), 4)}
        if not disabled and n > 1 else {})
    total = sum(entry_counts)
    result["entry_n_samples"] = entry_counts
    result["entry_counts_pct"] = [round(100 * x / total, 2)
                                  for x in entry_counts]
    result["entry_pot_bb"] = [
        round(entry_pots[k] / v, 3) if v and (not disabled or k == 0)
        else None for k, v in enumerate(entry_counts)]
    result["entry_ev_sd_bb"] = [
        round(math.sqrt(max(0., (entry_ev_sq[k] - entry_ev_sum[k]**2 / v)
                           / (v - 1))), 5) if v > 1 and not disabled
        else None for k, v in enumerate(entry_counts)]
    result["entry_stats_note"] = (
        "Средний банк = фактический финальный банк (все ставки), BB. "
        "σ EV оценивается по фактическим net BB; прогноз ±95% для N прогонов "
        "использует ожидаемое N × P(числа активных соперников) и "
        "является приближением для одной руки. "
        "Для полной матрицы σ объединяет разные классы рук.")
    return result


_MATRIX_RANGES = None


def _init_matrix_worker(raw):
    """Build immutable opponent distributions only once per worker."""
    global _MATRIX_RANGES
    _MATRIX_RANGES = eq.build_ranges(raw["opponents"], "selected")


def _compute_chunk(raw, hands):
    """Spawn-safe worker; each hand uses its original deterministic seed."""
    return calculate(raw, _hands=hands, _return_raw=True,
                     _prepared=_MATRIX_RANGES)


def calculate_parallel(raw, progress=None, workers=1, chunk_size=8):
    """True multi-core 169-hand rollout; single-hand results stay unchanged.

    Spawn rather than fork: this is called within a live HTTP server thread.
    """
    payload = validate_request(raw)
    if type(workers) is not int or not 1 <= workers <= 8:
        raise ValueError("Число процессов Monte Carlo: 1–8")
    if payload["hand"]:
        return (_single_parallel(payload, progress, workers)
                if workers > 1 and payload["trials"] * payload["cycles"] >= 2000
                else calculate(payload, progress=progress))
    if workers == 1:
        return calculate(payload, progress=progress)
    chunks = [list(core.HANDS[i:i + chunk_size])
              for i in range(0, len(core.HANDS), chunk_size)]
    final = None
    totals = None
    done = 0
    with ProcessPoolExecutor(max_workers=workers,
                             mp_context=multiprocessing.get_context("spawn"),
                             initializer=_init_matrix_worker,
                             initargs=(payload,)) as pool:
        jobs = {pool.submit(_compute_chunk, payload, chunk): len(chunk)
                for chunk in chunks}
        for job in as_completed(jobs):
            part = job.result()
            raw_stats = part.pop("_raw_stats")
            if final is None:
                final = part
                totals = raw_stats
            else:
                for name in ("equity", "ev_bb", "showdown_pct", "fold_win_pct",
                             "ev_ci95_bb"):
                    final[name].update(part[name])
                for name in totals:
                    totals[name] = [a + b for a, b in zip(totals[name],
                                                          raw_stats[name])]
            done += jobs[job]
            if progress:
                progress(done, len(core.HANDS))
    counts = totals["entry_counts"]
    grand_total = sum(counts)
    final["entry_n_samples"] = counts
    final["entry_counts_pct"] = [
        round(100 * count / grand_total, 2) for count in counts]
    final["entry_pot_bb"] = [
        round(totals["entry_pots"][i] / count, 3)
        if count and (final["behavioral_ev_enabled"] or i == 0) else None
        for i, count in enumerate(counts)]
    final["entry_ev_sd_bb"] = [
        round(math.sqrt(max(0., (totals["entry_ev_sq"][i]
                                - totals["entry_ev_sum"][i]**2/count) /
                               (count-1))), 5)
        if count > 1 and final["behavioral_ev_enabled"] else None
        for i, count in enumerate(counts)]
    return final
