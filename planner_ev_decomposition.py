"""Single-hand postflop EV attribution from actual engine outcomes.

Outcomes partition all simulated deals, so their net BB contributions sum to
the reported chip EV. "Loss exposures" are observed negative payouts, not
counterfactual mistakes; classifying them must never imply optimal decisions.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from core.engine import eval_hand

CATEGORIES={0:"Старшая карта",1:"Одна пара",2:"Две пары",3:"Сет / трипс",
            4:"Стрит",5:"Флеш",6:"Фулл-хаус",7:"Каре",8:"Стрит-флеш"}
LABELS={
    "uncontested":"Победа без соперников на префлопе",
    "fold_flop":"Наш фолд на флопе","fold_turn":"Наш фолд на тёрне",
    "fold_river":"Наш фолд на ривере","fold_other":"Наш фолд",
    "win_without_showdown":"Победа без вскрытия (постфлоп)",
    "higher_flush":"Флеш проиграл старшему флешу",
    "flush_vs_full_house":"Флеш проиграл фулл-хаусу / каре",
    "higher_pair":"Проигрыш старшей паре",
    "better_kicker":"Проигрыш паре с лучшим кикером",
    "higher_straight":"Стрит проиграл старшему стриту",
    "higher_trips":"Тройка проиграла старшей тройке",
    "higher_two_pair":"Две пары проиграли старшим двум парам",
    "higher_made_hand":"Проигрыш более сильной категории",
    "other_showdown_loss":"Прочий проигрыш на вскрытии",
    "fold_flop_loss":"Потери после фолда на флопе",
    "fold_turn_loss":"Потери после фолда на тёрне",
    "fold_river_loss":"Потери после фолда на ривере",
    "fold_other_loss":"Потери после фолда"
}
FLUSH_LABELS={
    "lower_flush":"Флеш против младшего флеша",
    "higher_flush":"Флеш против старшего флеша",
    "full_house_plus":"Флеш против фулл-хауса / каре",
    "other_hand":"Флеш против других комбинаций",
}


def _pair_rank(cards):
    counts=Counter(card[0] for card in cards)
    ranks="23456789TJQKA"
    return max((ranks.index(rank) for rank,count in counts.items() if count>=2),default=-1)


def classify_showdown(hero_hole, villain_holes, board, *, hero_won):
    """Exactly one primary event/risk and optional one exclusive flush tag.

    Compare to strongest remaining showdown opponent, not folded cards.
    """
    hero_cards=list(hero_hole)
    visible=list(board)
    hero_score=eval_hand(hero_cards,visible)
    hero_cat=hero_score>>24
    rivals=[(eval_hand(list(hole),visible),list(hole)) for hole in villain_holes]
    rivals.sort(key=lambda item:item[0],reverse=True)
    opponent_score,opponent_cards=rivals[0] if rivals else (None,[])
    opponent_cat=(opponent_score>>24) if opponent_score is not None else -1
    result=("showdown_"+str(hero_cat)+("_win" if hero_won else "_loss"))
    risk=None
    flush=None
    if hero_cat==5:
        if opponent_cat==5:
            flush="lower_flush" if hero_won else "higher_flush"
        elif opponent_cat>=6 and not hero_won:
            flush="full_house_plus"
        else:
            flush="other_hand"
    if not hero_won and opponent_score is not None:
        if hero_cat==5 and opponent_cat==5 and opponent_score>hero_score:
            risk="higher_flush"
        elif hero_cat==5 and opponent_cat>=6:
            risk="flush_vs_full_house"
        elif hero_cat==opponent_cat==1:
            hero_pair=_pair_rank(hero_cards+visible)
            rival_pair=_pair_rank(opponent_cards+visible)
            risk="higher_pair" if rival_pair>hero_pair else "better_kicker"
        elif hero_cat==opponent_cat==4:
            risk="higher_straight"
        elif hero_cat==opponent_cat==3:
            risk="higher_trips"
        elif hero_cat==opponent_cat==2:
            risk="higher_two_pair"
        elif opponent_cat>hero_cat:
            risk="higher_made_hand"
        else:
            risk="other_showdown_loss"
    return result,risk,flush


class EVDecomposition:
    def __init__(self,hand):
        self.hand=hand
        self.n=0
        self.event=defaultdict(lambda:{"count":0,"net":0.0})
        self.loss=defaultdict(lambda:{"count":0,"gross_loss":0.0})
        self.flush=defaultdict(lambda:{"count":0,"net":0.0})
        self.ev_total=0.0

    def add(self,net_bb, event, *, risk=None, flush=None):
        self.n+=1
        self.ev_total+=net_bb
        e=self.event[event];e["count"]+=1;e["net"]+=net_bb
        if risk and net_bb<0:
            t=self.loss[risk];t["count"]+=1;t["gross_loss"]+=-net_bb
        if flush:
            f=self.flush[flush];f["count"]+=1;f["net"]+=net_bb

    def result(self):
        n=self.n
        if not n:return None
        events=[]
        for key,stats in self.event.items():
            label=LABELS.get(key)
            if label is None and key.startswith("showdown_"):
                parts=key.split("_")
                label=("Вскрытие · "+CATEGORIES.get(int(parts[1]),"Комбинация")
                       +(" · победа" if parts[2]=="win" else " · проигрыш"))
            events.append({"key":key,"label":label or key,
                           "count":stats["count"],"frequency_pct":round(100*stats["count"]/n,2),
                           "avg_bb":round(stats["net"]/stats["count"],4),
                           "contribution_bb":round(stats["net"]/n,5)})
        events.sort(key=lambda x:(x["key"].startswith("showdown_"),-x["count"],x["key"]))
        risks=[{"key":key,"label":LABELS.get(key,key),"count":v["count"],
                "frequency_pct":round(100*v["count"]/n,2),
                "avg_loss_bb":round(v["gross_loss"]/v["count"],4),
                "cost_bb":round(v["gross_loss"]/n,5)}
               for key,v in self.loss.items()]
        risks.sort(key=lambda x:(-x["cost_bb"],x["key"]))
        flush=[{"key":key,"label":FLUSH_LABELS[key],"count":v["count"],
                "frequency_pct":round(100*v["count"]/n,2),
                "avg_bb":round(v["net"]/v["count"],4),
                "contribution_bb":round(v["net"]/n,5)}
               for key,v in self.flush.items()]
        flush.sort(key=lambda x:-x["count"])
        return {"hand":self.hand,"samples":n,
                "ev_bb":round(self.ev_total/n,4),
                "events":events,"loss_exposures":risks,"flush":flush,
                "diagnostic_only":True,
                "note":("Стоимость потерь = сумма фактических отрицательных net BB / все симулированные раздачи. "
                        "Это НЕ стоимость ошибки решения: для неё нужно сравнение альтернативных действий. "
                        "Категории исходов взаимно исключают друг друга и суммируются в EV. "
                        "Метки доминирования и флеша — дополнительные срезы, их нельзя суммировать с исходами. "
                        "Флоп/тёрн/ривер в текущем движке могут завершиться без вскрытия, "
                        "поэтому для фолдов нельзя утверждать, какую комбинацию держал бы соперник на ривере.")}


def classify_case(picked,board,history,hero_fold_street,net_bb):
    """Classify a completed engine hand without imputing unrevealed holdings."""
    if hero_fold_street:
        street=hero_fold_street if hero_fold_street in ("flop","turn","river") else "other"
        return "fold_"+street,"fold_"+street+"_loss",None
    players=history.get("players",())
    if "HERO" not in players:
        return "win_without_showdown",None,None
    hero_hole=next(cards for pid,cards,_ in picked if pid=="HERO")
    remaining=[cards for pid,cards,_ in picked if pid!="HERO" and pid in players]
    return classify_showdown(
        [tuple(_card(c)) for c in hero_hole],
        [[tuple(_card(c)) for c in v] for v in remaining],
        [tuple(_card(c)) for c in board],hero_won="HERO" in history.get("winners",())
    )


def _card(card_id):
    # Same canonical mapping as planner_postflop_ev._card without circular import.
    return ("23456789TJQKA"[card_id//4],"cdhs"[card_id%4])
