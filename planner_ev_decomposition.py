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
    "flush_vs_full_house":"Флеш проиграл фулл-хаусу / каре / стрит-флешу",
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
    "equal_flush":"Разделили банк с равным флешем",
    "full_house_plus":"Флеш против фулл-хауса / каре / стрит-флеша",
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
            # Compare the actual best-five flush strength, not only net payout:
            # side pots and splits can make "won money" differ from showdown rank.
            flush=("equal_flush" if opponent_score==hero_score else
                   "lower_flush" if hero_score>opponent_score else "higher_flush")
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



OUTCOME_GROUPS=(
 ("pre_win","Победа до вскрытия"),
 ("pre_loss","Проигрыш до вскрытия"),
 ("showdown_win","Вскрытие · победа"),
 ("showdown_win_dominates","Вскрытие · победа с доминированием"),
 ("showdown_loss","Вскрытие · проигрыш"),
 ("showdown_loss_dominated","Вскрытие · проигрыш под доминированием"),
 ("showdown_split","Вскрытие · ничья / раздел банка"),
)
RANK_VALUES={rank:index for index,rank in enumerate("23456789TJQKA")}


def preflop_domination(hero,villain):
    """Conservative: same high card with better kicker, or higher pocket pair."""
    a=sorted((c[0] for c in hero),key=RANK_VALUES.__getitem__,reverse=True)
    b=sorted((c[0] for c in villain),key=RANK_VALUES.__getitem__,reverse=True)
    if a[0]==a[1] and b[0]==b[1] and a[0]!=b[0]:
        return ("hero" if RANK_VALUES[a[0]]>RANK_VALUES[b[0]] else "villain",
                "".join(a),"".join(b))
    if a[0]==b[0] and a[0]!=a[1] and b[0]!=b[1] and a[1]!=b[1]:
        return ("hero" if RANK_VALUES[a[1]]>RANK_VALUES[b[1]] else "villain",
                "".join(a),"".join(b))
    return None,"".join(a),"".join(b)


def showdown_group(hero_hole,villain_holes,board,hero_won):
    """Domination = same final five-card HAND CATEGORY, stronger rank/kicker.

    Example: pair vs pair, flush vs flush. AK vs AQ on the preflop is
    irrelevant to the primary showdown classification. The standalone
    legacy preflop matchup is retained only as optional diagnostic data.
    """
    if not villain_holes:
        return ("showdown_win" if hero_won else "showdown_loss"),None
    hero_score=eval_hand(list(hero_hole),list(board))
    best=max(villain_holes,key=lambda h:eval_hand(list(h),list(board)))
    best_score=eval_hand(list(best),list(board))
    if best_score==hero_score:
        return "showdown_split",None
    relation,hero_rank,rival_rank=preflop_domination(hero_hole,best)
    matchup=(relation,hero_rank,rival_rank) if relation else None
    same_category=(hero_score >> 24)==(best_score >> 24)
    if hero_won:
        # Avoid false domination in side-pot situations where a payout winner
        # does not outrank the strongest remaining rival.
        dominated_same_category=same_category and hero_score>best_score
        return ("showdown_win_dominates" if dominated_same_category
                else "showdown_win"),matchup
    dominated_same_category=same_category and hero_score<best_score
    return ("showdown_loss_dominated" if dominated_same_category
            else "showdown_loss"),matchup


def showdown_mechanism(hero_hole,villain_holes,board):
    """Observable best-five comparison at showdown, not preflop domination.

    In multiway spots we compare Hero with the strongest remaining rival.
    Side pots can make payout signs differ from ranking of the best hands.
    """
    h_score=eval_hand(list(hero_hole),list(board))
    h_cat=h_score>>24
    if not villain_holes:
        return "showdown_no_rival","Не определена комбинация соперника"
    v_hand=max(villain_holes,key=lambda h:eval_hand(list(h),list(board)))
    v_score=eval_hand(list(v_hand),list(board))
    v_cat=v_score>>24
    h_name=CATEGORIES.get(h_cat,"Комбинация")
    v_name=CATEGORIES.get(v_cat,"Комбинация")
    if h_score==v_score:
        return "showdown_equal","Равные итоговые комбинации · раздел банка"
    if h_cat!=v_cat:
        return ("showdown_categories_%s_%s"%(h_cat,v_cat),
                "%s против %s"%(h_name,v_name))
    # Same hand category: distinguish actual rank strength from kickers.
    if h_cat==1:
        hp=_pair_rank(list(hero_hole)+list(board))
        vp=_pair_rank(list(v_hand)+list(board))
        reason="Старшая пара" if hp!=vp else "Преимущество кикера"
    elif h_cat==0:
        reason="Старшая карта / кикер"
    elif h_cat==2:
        reason="Две пары / кикер"
    elif h_cat==3:
        reason="Старшая тройка / кикер"
    elif h_cat==4:
        reason="Старший стрит"
    elif h_cat==5:
        reason="Старший флеш"
    elif h_cat==6:
        reason="Старший фулл-хаус"
    elif h_cat==7:
        reason="Более высокое каре / кикер"
    else:
        reason="Более высокий стрит-флеш"
    return "showdown_same_%s_%s"%(h_cat,"rank" if h_cat!=1 or hp!=vp else "kicker"),(
        "%s · %s"%(h_name,reason))


def reason_for_event(event):
    """Reason when no showdown hand comparison is available."""
    if event=="uncontested":
        return "pre_uncontested","Все соперники не вошли в банк"
    if event=="win_without_showdown":
        return "pre_villain_folds","Соперники сбросили до вскрытия"
    if event.startswith("fold_"):
        street=event.removeprefix("fold_")
        return event,{"flop":"Наш фолд на флопе",
                      "turn":"Наш фолд на тёрне",
                      "river":"Наш фолд на ривере"}.get(street,"Наш фолд")
    return "unspecified","Причина не определена"


def catalog_flop_case(picked, board):
    """Map an *observed* physical 2+3 deal to Sheet 03's composite glossary.

    Do not assign a fictional flop to an uncontested preflop win.
    The 1,019 scenario IDs are defined by the same canonical classifier used
    by the interactive /s100 catalogue.
    """
    if len(picked) <= 1:
        return {"id": "PRE|NO_FLOP", "board_group": "PRE|NO_FLOP",
                "board_name": "00 · До флопа", "hero_class": "PRE|NO_FLOP",
                "hero_name": "Соперники не вошли · флоп не раздавался"}
    from postflop_composite_classifier import classify_composite_flop
    hero_cards = picked[0][1]
    hero = "-".join(str(int(_card(c)[0].replace("T", "10").replace("J", "11").replace("Q", "12").replace("K", "13").replace("A", "14"))) + _card(c)[1]
                    for c in hero_cards)
    flop = "-".join(str(int(_card(c)[0].replace("T", "10").replace("J", "11").replace("Q", "12").replace("K", "13").replace("A", "14"))) + _card(c)[1]
                    for c in board[:3])
    value = classify_composite_flop(hero, flop)
    return {"id": value["id"], "board_group": value["board"]["group_id"],
            "board_name": value["board"]["group_name"],
            "hero_class": value["hero_state"]["id"],
            "hero_name": value["hero_state"]["name"]}


class EVDecomposition:
    def __init__(self,hand):
        self.hand=hand
        self.n=0
        self.event=defaultdict(lambda:{"count":0,"net":0.0})
        self.loss=defaultdict(lambda:{"count":0,"gross_loss":0.0})
        self.flush=defaultdict(lambda:{"count":0,"net":0.0})
        self.ev_total=0.0
        self.groups=defaultdict(lambda:{"count":0,"net":0.0,"positive_net":0.0,"negative_net":0.0,"positive_count":0,"negative_count":0,"neutral_count":0})
        self.matchups=defaultdict(lambda:{"count":0,"wins":0,"net":0.0})
        self.reasons=defaultdict(lambda:{"count":0,"net":0.0,"label":"",**{"count":0,"net":0.0,"positive_net":0.0,"negative_net":0.0,"positive_count":0,"negative_count":0,"neutral_count":0}})
        self.river=defaultdict(lambda:{"count":0,"net":0.0,"positive_net":0.0,"negative_net":0.0,
                                        "positive_count":0,"negative_count":0,"neutral_count":0})
        self.catalog=defaultdict(lambda:{"count":0,"net":0.0,"positive_net":0.0,"negative_net":0.0,
                                         "positive_count":0,"negative_count":0,"neutral_count":0,
                                         "board_group":"","board_name":"","hero_class":"","hero_name":""})

    def add(self,net_bb, event, *, risk=None, flush=None, group=None, matchup=None, reason=None, catalog=None, attribution=None):
        self.n+=1
        self.ev_total+=net_bb
        e=self.event[event];e["count"]+=1;e["net"]+=net_bb
        if group is None:
            if event.startswith("showdown_"):
                group="showdown_win" if event.endswith("_win") else "showdown_loss"
            else:
                group="pre_loss" if event.startswith("fold_") else "pre_win"
        bucket=self.groups[group];bucket["count"]+=1;bucket["net"]+=net_bb
        reason_key,reason_label=reason if reason is not None else reason_for_event(event)
        r=self.reasons[(group,reason_key)]
        r["count"]+=1;r["net"]+=net_bb;r["label"]=reason_label
        for record in (bucket,r):
            if net_bb>0:
                record["positive_net"]+=net_bb;record["positive_count"]+=1
            elif net_bb<0:
                record["negative_net"]+=net_bb;record["negative_count"]+=1
            else:
                record["neutral_count"]+=1
        if attribution is not None:
            bd=attribution["board"]
            hero=attribution["hero"]
            # Compact sparse cube, not 1,019 pre-materialized scenario rows.
            key=(attribution["sign"],attribution["cause"],
                 bd["id"],bd["catalog_id"],bd["street"],bd["suit"],bd["rank_texture"],
                 bd["straight"],hero["origin"],hero["category"],
                 hero["hole_use"],attribution["detail"],
                 attribution.get("villain_category"),attribution.get("showdown_opponents",0),
                 attribution.get("outcome_code","X1"))
            cell=self.river[key]
            cell["count"]+=1
            cell["net"]+=net_bb
            if net_bb>0:
                cell["positive_net"]+=net_bb
                cell["positive_count"]+=1
            elif net_bb<0:
                cell["negative_net"]+=net_bb
                cell["negative_count"]+=1
            else:
                cell["neutral_count"]+=1
        if catalog is not None:
            item=self.catalog[catalog["id"]]
            item["board_group"]=catalog["board_group"]
            item["board_name"]=catalog["board_name"]
            item["hero_class"]=catalog["hero_class"]
            item["hero_name"]=catalog["hero_name"]
            item["count"]+=1
            item["net"]+=net_bb
            if net_bb>0:
                item["positive_net"]+=net_bb
                item["positive_count"]+=1
            elif net_bb<0:
                item["negative_net"]+=net_bb
                item["negative_count"]+=1
            else:
                item["neutral_count"]+=1
        if matchup:
            relation,hero_rank,rival_rank=matchup
            entry=self.matchups[(relation,hero_rank,rival_rank)]
            entry["count"]+=1
            entry["wins"]+=int(group in ("showdown_win","showdown_win_dominates"))
            entry["net"]+=net_bb
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
        def report_numbers(record):
            return {
                "positive_ev_bb":round(record["positive_net"]/n,5),
                "negative_ev_bb":round(record["negative_net"]/n,5),
                "positive_count":record["positive_count"],
                "negative_count":record["negative_count"],
                "neutral_count":record["neutral_count"]}
        grouped=[]
        for key,label in OUTCOME_GROUPS:
            group=self.groups[key]
            reasons=[{"key":code,"label":stat["label"],
                      "count":stat["count"],
                      "frequency_pct":round(100*stat["count"]/n,2),
                      "within_group_pct":round(100*stat["count"]/group["count"],2),
                      "avg_bb":round(stat["net"]/stat["count"],4),
                      "contribution_bb":round(stat["net"]/n,5),
                      **report_numbers(stat)}
                     for (category,code),stat in self.reasons.items()
                     if category==key and stat["count"]]
            reasons.sort(key=lambda row:(-row["count"],row["label"]))
            assert sum(v["count"] for v in reasons)==group["count"]
            assert sum(v["positive_count"]+v["negative_count"]+v["neutral_count"]
                       for v in reasons)==group["count"]
            grouped.append({
                "key":key,"label":label,"count":group["count"],
                "frequency_pct":round(100*group["count"]/n,2),
                "avg_bb":round(group["net"]/group["count"],4) if group["count"] else 0.,
                "contribution_bb":round(group["net"]/n,5),
                **report_numbers(group),
                "reasons":reasons})
        matchups=[{"relation":rel,"hero":hero,"villain":villain,
                   "count":stats["count"],"wins":stats["wins"],
                   "win_pct":round(100*stats["wins"]/stats["count"],1),
                   "contribution_bb":round(stats["net"]/n,5)}
                  for (rel,hero,villain),stats in self.matchups.items()]
        matchups.sort(key=lambda x:(-x["count"],x["hero"],x["villain"]))
        assert sum(g["count"] for g in grouped)==n
        catalog_rows=[]
        if self.catalog:
            assert sum(item["count"] for item in self.catalog.values())==n
            for code,item in sorted(self.catalog.items()):
                catalog_rows.append({
                    "id":code,"board_group":item["board_group"],
                    "board_name":item["board_name"],
                    "hero_class":item["hero_class"],"hero_name":item["hero_name"],
                    "count":item["count"],
                    "frequency_pct":round(100*item["count"]/n,3),
                    "avg_bb":round(item["net"]/item["count"],5),
                    "positive_count":item["positive_count"],
                    "negative_count":item["negative_count"],
                    "neutral_count":item["neutral_count"],
                    "positive_ev_bb":round(item["positive_net"]/n,6),
                    "negative_ev_bb":round(item["negative_net"]/n,6),
                    "contribution_bb":round(item["net"]/n,6)
                })
            assert abs(sum(v["net"] for v in self.catalog.values())-self.ev_total)<1e-7
        river_rows=[]
        if self.river:
            from planner_river_classifier import BOARDS,CAUSES,ORIGINS
            assert sum(item["count"] for item in self.river.values())==n
            assert abs(sum(item["net"] for item in self.river.values())-self.ev_total)<1e-7
            for key,item in sorted(self.river.items(),key=lambda p:str(p[0])):
                sign,cause,board_id,board_code,street,suit,rank_texture,straight,origin,category,hole_use,detail,villain_category,showdown_opponents,outcome_code=key
                river_rows.append({
                    "sign":sign,"cause":cause,"cause_name":CAUSES[cause],
                    "board_id":board_id,"board_name":BOARDS[board_id],
                    "board_code":board_code,
                    "street":street,"suit":suit,
                    "rank_texture":rank_texture,"straight":straight,
                    "origin":origin,"origin_name":ORIGINS[origin],
                    "hero_category":category,"hero_hole_use":hole_use,
                    "detail":detail,"villain_category":villain_category,
                    "showdown_opponents":showdown_opponents,"outcome_code":outcome_code,
                    "count":item["count"],
                    "positive_count":item["positive_count"],
                    "negative_count":item["negative_count"],
                    "neutral_count":item["neutral_count"],
                    "positive_ev_bb":round(item["positive_net"]/n,7),
                    "negative_ev_bb":round(item["negative_net"]/n,7),
                    "contribution_bb":round(item["net"]/n,7)
                })
        return {"hand":self.hand,"samples":n,
                "river_attribution":{
                    "version":"river_reason_board_v1",
                    "samples":n,
                    "reconciled":bool(river_rows),
                    "rows":river_rows,
                    "note":"Финансовый знак → причина → фактический последний борд; участие HERO, масть и связность — независимые свойства. Валовые EV нормированы на все N. Не является оценкой ошибки решения."},
                "catalog_attribution":{
                    "source":"postflop_composite_catalog_v1",
                    "total_scenarios":1019,
                    "samples":n,
                    "rows":catalog_rows,
                    "reconciled":bool(catalog_rows),
                    "note":"Взаимоисключающие сценарии фактического флопа. PRE|NO_FLOP — победы до флопа; EV+ и EV− нормированы на полную выборку, не на число попаданий в статью."},
                "outcome_groups":grouped,"domination_matchups":matchups,
                "ev_bb":round(self.ev_total/n,4),
                "events":events,"loss_exposures":risks,"flush":flush,
                "diagnostic_only":True,
                "note":("Стоимость потерь = сумма фактических отрицательных net BB / все симулированные раздачи. "
                        "Это НЕ стоимость ошибки решения: для неё нужно сравнение альтернативных действий. "
                        "Категории исходов взаимно исключают друг друга и суммируются в EV. "
                        "Доминирование на вскрытии: одинаковый тип итоговой комбинации, но старший ранг или кикер. "
                         "Сравнение со старшей рукой оставшегося соперника; в мультивее сайд-поты могут влиять на выплату. "
                         "Префлоп-доминирование отдельно и не влияет на группы. "
                        "Флоп/тёрн/ривер в текущем движке могут завершиться без вскрытия, "
                        "поэтому для фолдов нельзя утверждать, какую комбинацию держал бы соперник на ривере.")}


def classify_case(picked,board,history,hero_fold_street,net_bb):
    """Detailed event, risk, flush, mutually exclusive group, preflop matchup."""
    if hero_fold_street:
        street=hero_fold_street if hero_fold_street in ("flop","turn","river") else "other"
        return "fold_"+street,"fold_"+street+"_loss",None,"pre_loss",None,reason_for_event("fold_"+street)
    players=history.get("players",())
    if "HERO" not in players:
        return "win_without_showdown",None,None,(
            "pre_win" if net_bb>=0 else "pre_loss"),None,reason_for_event("win_without_showdown")
    hero_hole=next(cards for pid,cards,_ in picked if pid=="HERO")
    remaining=[cards for pid,cards,_ in picked if pid!="HERO" and pid in players]
    hero_cards=[tuple(_card(c)) for c in hero_hole]
    rival_cards=[[tuple(_card(c)) for c in rival] for rival in remaining]
    board_cards=[tuple(_card(c)) for c in board]
    hero_won="HERO" in history.get("winners",())
    event,risk,flush=classify_showdown(
        hero_cards,rival_cards,board_cards,hero_won=hero_won)
    group,matchup=showdown_group(hero_cards,rival_cards,board_cards,hero_won)
    reason=showdown_mechanism(hero_cards,rival_cards,board_cards)
    return event,risk,flush,group,matchup,reason


def _card(card_id):
    # Same canonical mapping as planner_postflop_ev._card without circular import.
    return ("23456789TJQKA"[card_id//4],"cdhs"[card_id%4])
