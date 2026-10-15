"""Monte Carlo all-in preflop equity for 1–5 independently defined ranges.

The joint sample is drawn from product distributions CONDITIONAL on no
overlapping cards, never by averaging heads-up equities. Tied pots split
equally between all winners. No use of the legacy half-tie estimator.
Pure Python evaluator avoids the engine's large five-card pickle table.
"""
from __future__ import annotations
from bisect import bisect_left
from collections import Counter
from itertools import combinations
import hashlib
import json
import math
import random

import planner_core as planner

RANKS = "23456789TJQKA"
ALL_CARDS = tuple(range(52))


def expand_hand(hand):
    a = RANKS.index(hand[0])
    b = RANKS.index(hand[1])
    if len(hand) == 2:
        return tuple((a*4+s, b*4+t) for s in range(4) for t in range(s+1,4))
    if hand.endswith("s"):
        return tuple((a*4+s,b*4+s) for s in range(4))
    return tuple((a*4+s,b*4+t) for s in range(4) for t in range(4) if s!=t)


HAND_COMBOS = {hand:expand_hand(hand) for hand in planner.HANDS}


def straight_high(ranks):
    mask = set(ranks)
    if 14 in mask:
        mask.add(1)
    for top in range(14, 4, -1):
        if all(i in mask for i in range(top-4,top+1)):
            return top
    return 0


def score_seven(cards):
    """Comparable 7-card Hold'em score (category 0..8, rank tiebreakers)."""
    ranks = [c//4+2 for c in cards]
    count = Counter(ranks)
    suits = [c%4 for c in cards]
    flush_suit = next((s for s in range(4) if suits.count(s)>=5),None)
    if flush_suit is not None:
        flush_ranks = [c//4+2 for c in cards if c%4==flush_suit]
        sf = straight_high(flush_ranks)
        if sf: return (8,sf)
    quads = [r for r,c in count.items() if c==4]
    if quads:
        q=max(quads)
        return (7,q,max(r for r in count if r!=q))
    trips = sorted((r for r,c in count.items() if c>=3),reverse=True)
    if trips:
        p = max((r for r,c in count.items() if r!=trips[0] and c>=2),default=0)
        if p: return (6,trips[0],p)
    if flush_suit is not None:
        return (5,*sorted(flush_ranks,reverse=True)[:5])
    straight = straight_high(count)
    if straight: return (4,straight)
    if trips:
        kickers=sorted((r for r in count if r!=trips[0]),reverse=True)[:2]
        return (3,trips[0],*kickers)
    pairs=sorted((r for r,c in count.items() if c>=2),reverse=True)
    if len(pairs)>=2:
        kicker=max(r for r in count if r not in pairs[:2])
        return (2,pairs[0],pairs[1],kicker)
    if pairs:
        k=sorted((r for r in count if r!=pairs[0]),reverse=True)[:3]
        return (1,pairs[0],*k)
    return (0,*sorted(count,reverse=True)[:5])


class WeightedRange:
    def __init__(self, class_weights):
        concrete = []
        cum = []
        mass = 0.0
        for hand in planner.HANDS:
            probability = float(class_weights.get(hand, 0))
            if not 0 <= probability <= 1:
                raise ValueError("Некорректная частота в диапазоне")
            if probability == 0:
                continue
            for two in HAND_COMBOS[hand]:
                concrete.append(two)
                mass += probability
                cum.append(mass)
        if not concrete:
            raise ValueError("У соперника пустой диапазон активных рук")
        self.combos = concrete
        self.cum = cum
        self.total = mass
        self.card_mass = [0.0] * 52
        self.combo_weights = {}
        for pair, weight in ((c, float(class_weights[h]))
                             for h in planner.HANDS for c in HAND_COMBOS[h]
                             if class_weights.get(h, 0) > 0):
            self.combo_weights[tuple(sorted(pair))] = weight
            self.card_mass[pair[0]] += weight
            self.card_mass[pair[1]] += weight

    def dealt_frequency(self):
        return self.total / 1326.0

    def probability_versus_hero(self, hero):
        """Range hit rate with hero's two exact blockers, out of C(50,2)."""
        c1, c2 = hero
        pair = (min(c1, c2), max(c1, c2))
        possible = (self.total - self.card_mass[c1] - self.card_mass[c2]
                    + self.combo_weights.get(pair, 0.0))
        return min(1.0, max(0.0, possible / 1225.0))
    def sample(self,rng):
        i=bisect_left(self.cum,rng.random()*self.total)
        return self.combos[min(i,len(self.combos)-1)]


def safe_inline_weights(weights):
    """Validated live hero range for reverse HU. No user-supplied file refs."""
    if not isinstance(weights, dict) or not 1 <= len(weights) <= 169:
        raise ValueError("Live-диапазон: ожидается 1–169 рук")
    if any(h not in planner.COMBOS for h in weights):
        raise ValueError("Live-диапазон содержит неизвестные руки")
    if any(type(w) not in (int, float) or not math.isfinite(w)
           or w < 0 or w > 1 for w in weights.values()):
        raise ValueError("Live-диапазон: частоты должны быть 0–1")
    result = {h: float(w) for h, w in weights.items() if w > 0}
    if not result:
        raise ValueError("Live-диапазон не содержит активных рук")
    return result


def build_ranges(opponents, model="selected"):
    if not isinstance(opponents,list) or not 1 <= len(opponents) <= 5:
        raise ValueError("Нужны от одного до пяти соперников")
    if model not in ("selected","any_two","gto_heuristic"):
        raise ValueError("Неизвестная модель equity")
    ranges=[]
    provenance=[]
    for index,opp in enumerate(opponents,1):
        if not isinstance(opp,dict):
            raise ValueError("Неверный профиль соперника")
        profile = opp.get("profile","builtin:any_two")
        if model=="any_two":
            profile="builtin:any_two"
        elif model=="gto_heuristic":
            profile="builtin:gto_heuristic"
        pos=str(opp.get("position","3"))
        scenario="rfi" if model!="selected" else str(opp.get("scenario","rfi"))
        n=int(opp.get("players",9))
        entry_mode = opp.get("entry_mode", "always")
        entry_pct = opp.get("entry_pct", 100.0)
        if entry_mode not in ("always", "range", "manual"):
            raise ValueError("Недопустимый режим вероятности входа")
        if type(entry_pct) not in (int, float) or not math.isfinite(entry_pct) or not 0 <= entry_pct <= 100:
            raise ValueError("Вероятность входа должна быть от 0 до 100%")
        if profile=="inline:hero":
            if model!="selected":
                raise ValueError("Live-диапазон разрешён только для selected")
            weights=safe_inline_weights(opp.get("weights"))
            ranges.append(WeightedRange(weights))
            provenance.append({"profile":profile,"position":pos,
                               "scenario":scenario,"selector":"active",
                               "weights":weights,
                               "entry_mode":entry_mode,"entry_pct":entry_pct})
            continue
        doc=planner.preset(profile,pos,scenario,n)
        selector = str(opp.get("selector","active")) if model=="selected" else "active"
        if profile in ("builtin:gto_heuristic","builtin:any_two"):
            selector="active"
        weights=planner.range_weights(doc,selector=selector)
        ranges.append(WeightedRange(weights))
        provenance.append({"profile":profile,"position":doc["position"],
                           "scenario":doc["scenario"],"selector":selector,
                           "entry_mode":entry_mode,"entry_pct":entry_pct})
    return ranges,provenance


def simulate_hand(hand, opponents, trials=200, seed=42):
    """Class equity conditioned on an actual legal, jointly sampled showdown.

    Samples hero's concrete suited/offsuit combinations and all opponents
    independently, rejecting card clashes to preserve the joint range law.
    """
    if hand not in HAND_COMBOS:
        raise ValueError("Неизвестная рука")
    if type(trials) is not int or not 50 <= trials <= 2000:
        raise ValueError("Число симуляций на руку: 50–2000")
    rng=random.Random(seed)
    hero_options=HAND_COMBOS[hand]
    payoff=0.0
    accepted=0
    attempts=0
    attempt_budget=max(1000,trials*300)
    while accepted<trials and attempts<attempt_budget:
        attempts+=1
        hero = rng.choice(hero_options)
        used=set(hero)
        dealt=[]
        for opponent in opponents:
            cards=opponent.sample(rng)
            if cards[0] in used or cards[1] in used:
                break
            used.update(cards)
            dealt.append(cards)
        if len(dealt)!=len(opponents):
            continue
        board=rng.sample([c for c in ALL_CARDS if c not in used],5)
        own_score=score_seven((*hero,*board))
        scores=[score_seven((*cards,*board)) for cards in dealt]
        best=max([own_score,*scores])
        if own_score==best:
            payoff+=1/(1+sum(s==best for s in scores))
        accepted+=1
    if accepted<trials:
        raise ValueError(f"Диапазоны несовместимы: удалось {accepted}/{trials} допустимых выставлений из {attempts} попыток. Расширь диапазоны.")
    return round(100*payoff/accepted,2)


def _player_entry_probability(opponent, spec, hero):
    mode = spec.get("entry_mode", "always")
    if mode == "range":
        return opponent.probability_versus_hero(hero)
    if mode == "manual":
        return float(spec["entry_pct"]) / 100.0
    return 1.0


def _subset_probabilities(probs):
    """Product Bernoulli distribution over exact masks (0 means all folded)."""
    values = [1.0]
    for p in probs:
        values = [v*(1.0-p) for v in values] + [v*p for v in values]
    # The iteration above builds masks with first index as lowest bit.
    return values


def entry_distributions(hand, opponents, specs):
    """Exact 0..N entry-count mix averaged over concrete hero holdings.

    'range' uses the 1225 available two-card combinations after hero blockers;
    manual entry is an external marginal assumption independent of the cards.
    """
    options = HAND_COMBOS[hand]
    n = len(opponents)
    counts = [0.0]*(n+1)
    choices = []
    for hole in options:
        probs = [_player_entry_probability(o, spec, hole)
                 for o, spec in zip(opponents, specs)]
        masks = _subset_probabilities(probs)
        for mask, p in enumerate(masks):
            counts[mask.bit_count()] += p/len(options)
        choices.append((hole, masks))
    return [min(1.0, max(0.0, p)) for p in counts], choices


def simulate_hand_variable(hand, opponents, specs, trials=200, seed=42):
    """Showdown equity conditioned on >=1 opponent entering the pot.

    Sample the hero's specific suit combination proportional to its chance
    of facing >=1 entrant, then the entered subset conditional on that hole.
    Never classify the all-fold (zero-opponent) case as 100% showdown equity.
    """
    counts, choices = entry_distributions(hand, opponents, specs)
    masses = [sum(mask_probs[1:]) for _, mask_probs in choices]
    total_mass = sum(masses)
    if total_mass <= 1e-14:
        return None, None, counts
    rng = random.Random(seed)
    earned = 0.0
    winning_pot_multiple = 0.0
    accepted = attempts = 0
    attempt_budget = max(2000, trials*500)
    while accepted < trials and attempts < attempt_budget:
        attempts += 1
        hole, masks = rng.choices(choices, weights=masses, k=1)[0]
        mask = rng.choices(range(1, len(masks)), weights=masks[1:], k=1)[0]
        active = [op for i, op in enumerate(opponents) if mask & (1 << i)]
        used = set(hole)
        cards = []
        for opponent in active:
            dealt = opponent.sample(rng)
            if dealt[0] in used or dealt[1] in used:
                break
            used.update(dealt)
            cards.append(dealt)
        if len(cards) != len(active):
            continue
        board = rng.sample([c for c in ALL_CARDS if c not in used], 5)
        hero_score = score_seven((*hole, *board))
        scores = [score_seven((*pair, *board)) for pair in cards]
        highest = max([hero_score, *scores])
        share = 0.0
        if hero_score == highest:
            share = 1.0/(1+sum(s == highest for s in scores))
        earned += share
        winning_pot_multiple += share*(len(active)+1)
        accepted += 1
    if accepted < trials:
        raise ValueError(f"Диапазоны и вероятности несовместимы: {accepted}/{trials} допустимых выставлений")
    return round(100*earned/accepted, 2), round(winning_pot_multiple/accepted, 5), counts


def simulate_range_equity(hero_weights, opponents, trials=3000, seed=42):
    """Direct joint range-vs-multiway equity, not an average of per-class equity.

    Samples a weighted hero *concrete combination* together with all
    opponent combinations; only collision-free joint deals enter the
    conditional distribution. Correctly accounts for card-removal
    differences across hero classes and multiway split pots.
    """
    if type(trials) is not int or not 200 <= trials <= 20000:
        raise ValueError("Симуляций для range equity: 200–20000")
    hero_range=WeightedRange(hero_weights)
    if not 1 <= len(opponents) <= 5:
        raise ValueError("Нужны 1–5 диапазонов соперников")
    rng=random.Random(seed)
    payoff=0.0
    accepted=0
    attempts=0
    budget=max(3000,trials*300)
    while accepted<trials and attempts<budget:
        attempts+=1
        hole=hero_range.sample(rng)
        used=set(hole)
        enemies=[]
        for opponent in opponents:
            cards=opponent.sample(rng)
            if cards[0] in used or cards[1] in used:
                break
            used.update(cards)
            enemies.append(cards)
        if len(enemies)!=len(opponents):
            continue
        board=rng.sample([c for c in ALL_CARDS if c not in used],5)
        scores=[score_seven((*hole,*board)),*(score_seven((*x,*board)) for x in enemies)]
        top=max(scores)
        if scores[0]==top:
            payoff+=1/sum(s==top for s in scores)
        accepted+=1
    if accepted<trials:
        raise ValueError(f"Несовместимые диапазоны при совместном выставлении: {accepted}/{trials} допустимых раздач")
    return {"equity_pct":round(100*payoff/accepted,2),
            "trials":accepted,"method":"joint_range_multiway_MC_V1",
            "note":"Monte Carlo: совместное распределение без конфликтующих карт; доля банка при равенстве делится между победителями."}


def config_hash(opponents,model,trials):
    raw=json.dumps({"model":model,"opponents":opponents,"trials":trials,
                    "engine":"SKACHKOV_MULTIWAY_MC_V1"},
                   sort_keys=True,ensure_ascii=False,separators=(",",":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def calculate_matrix(opponents,model="selected",trials=200,progress=None,cycles=1):
    """Independent reproducible MC cycles, aggregated across 169 classes."""
    if type(trials) is not int or not 50 <= trials <= 2000:
        raise ValueError("Симуляций на руку: 50–2000")
    if type(cycles) is not int or not 1 <= cycles <= 4:
        raise ValueError("Циклов Monte Carlo должно быть 1–4")
    sources,provenance=build_ranges(opponents,model)
    digest=config_hash(provenance,model,trials)
    values={};pot_multiples={};entry_by_hand={}
    entry_counts = [0.0]*(len(sources)+1)
    total=len(planner.HANDS)*cycles;done=0
    probabilistic = any(p.get("entry_mode", "always") != "always" for p in provenance)
    for hand in planner.HANDS:
        estimates=[];multiples=[]
        probabilities = None
        for cycle in range(cycles):
            # First cycle is backward compatible with the former single-pass MC.
            seed_key=f"{digest}:{hand}" if cycle==0 else f"{digest}:{hand}:cycle:{cycle}"
            seed=int(hashlib.sha256(seed_key.encode()).hexdigest()[:15],16)
            if probabilistic:
                eq, pot, probabilities = simulate_hand_variable(
                    hand, sources, provenance, trials=trials, seed=seed)
                if eq is not None:
                    estimates.append(eq);multiples.append(pot)
            else:
                eq = simulate_hand(hand,sources,trials=trials,seed=seed)
                estimates.append(eq)
                multiples.append((len(sources)+1)*eq/100.0)
            done+=1
            if progress and (done%5==0 or done==total):
                progress(done,total)
        values[hand]=round(sum(estimates)/len(estimates),2) if estimates else None
        pot_multiples[hand]=round(sum(multiples)/len(multiples),5) if multiples else None
        if probabilistic:
            entry_by_hand[hand]=[round(p*100,4) for p in probabilities]
            for k,p in enumerate(probabilities):
                entry_counts[k]+=planner.COMBOS[hand]*p/1326.0
    if not probabilistic:
        entry_counts=[0.0]*len(sources)+[1.0]
    return {"method":"SKACHKOV_MULTIWAY_MC_ENTRY_V2" if probabilistic else "SKACHKOV_MULTIWAY_MC_V1",
            "model":model,"opponents":provenance,
            "entry_counts_pct":[round(100*p,3) for p in entry_counts],
            "entry_by_hand_pct":entry_by_hand,
            "pot_multiple":pot_multiples,
            "equity_condition":"Conditional on at least one opponent entering; all-fold hands are not showdowns.",
            "simulations_per_hand":trials*cycles,"trials_per_cycle":trials,
            "cycles":cycles,"confidence_note":"Независимые циклы Monte Carlo; погрешность уменьшается при росте общего числа симуляций. Диапазоны с блокерами могут давать редкие совместимые исходы.",
            "equity":values,"config_hash":digest}


def aggregate_equity(doc,eq):
    weights=planner.range_weights(doc)
    mass=sum(planner.COMBOS[h]*v for h,v in weights.items())
    if not mass: return None
    return round(sum(planner.COMBOS[h]*v*eq[h] for h,v in weights.items())/mass,2)
