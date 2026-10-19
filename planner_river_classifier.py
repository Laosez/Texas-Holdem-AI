"""V1: exclusive outcome reason -> actual last visible board, with orthogonal
rank texture, suit texture and HERO hand-origin diagnostics.

All inputs are immutable *physical* cards (rank 0..12 x 4, suit c/d/h/s).
Never classify a preflop fold on a fictional predetermined five-card runout.
This is observed payout attribution, NOT a counterfactual decision-error solver.
"""
from collections import Counter
from core.engine import eval_hand

_RANKS="23456789TJQKA"
_SUITS="cdhs"
_CAT=("Старшая карта","Одна пара","Две пары","Сет / трипс","Стрит",
      "Флеш","Фулл-хаус","Каре","Стрит-флеш")

CAUSES={
 "C01": "Никто не вошёл до флопа",
 "C02": "Фолд соперников · без вскрытия",
 "C03": "Фолд HERO",
 "C04": "Разница категорий комбинаций",
 "C05": "Старший ранг комбинации",
 "C06": "Преимущество кикера",
 "C07": "Равные комбинации · раздел банка",
 "C08": "Несовпадение выплаты и старшей руки · сайд-поты",
}
BOARDS={
 "B00":"До флопа",
 "B01":"Открытый · стрит-опасный",
 "B02":"Открытый · четыре одной масти (4s)",
 "B03":"Открытый · три одной масти (3s)",
 "B04":"Открытый · комбинированная угроза",
 "B05":"Готовый стрит / флеш на борде",
 "B06":"Одна пара · сухой",
 "B07":"Одна пара · опасный",
 "B08":"Две пары на борде",
 "B09":"Тройка на борде",
 "B10":"Фулл-хаус / каре на борде",
 "B11":"Открытый · без сильных угроз",
}
ORIGINS={
 "high_card":"Старшая карта",
 "own_pair":"Своя пара",
 "pocket_pair":"Карманная пара",
 "board_pair":"Пара борда",
 "two_pair_own":"Две собственные пары",
 "two_pair_mixed":"Своя пара + пара борда",
 "two_pair_board":"Общие две пары",
 "set":"Сет (карманная пара)",
 "trips":"Трипс (одна карта HERO)",
 "board_trips":"Тройка борда",
 "straight":"Стрит",
 "flush":"Флеш",
 "full_house":"Фулл-хаус",
 "quads":"Каре",
 "straight_flush":"Стрит-флеш",
 "unavailable":"Комбинация не раскрыта",
}


def cards(values):
    return [(_RANKS[int(x)//4],_SUITS[int(x)%4]) for x in values]


def _ranks(values):
    return [(_RANKS.index(c[0])+2) for c in values]


def _sequence(board):
    ranks=set(_ranks(board))
    if 14 in ranks:ranks.add(1)
    best=max(sum(v in ranks for v in range(lo,lo+5)) for lo in range(1,11))
    return ("made" if best>=5 else "four" if best==4
            else "connected" if best==3 else "disconnected")


def board_texture(board_ids, street):
    from postflop_board150 import classify_board
    if street=="preflop":
        return {"id":"B00","catalog_id":"PRE|NO_BOARD","label":BOARDS["B00"],"street":"preflop",
                "suit":"S0","rank_texture":"unpaired","straight":"disconnected",
                "board_cards":0}
    limit={"flop":3,"turn":4,"river":5}[street]
    visible=cards(board_ids[:limit])
    rank_counts=Counter(_ranks(visible))
    suit_counts=Counter(s for _,s in visible)
    s=max(suit_counts.values())
    suit="S"+str(s)
    freqs=sorted(rank_counts.values(),reverse=True)
    rank=("quads" if freqs[0]==4 else
          "full_house" if freqs[:2]==[3,2] else
          "trips" if freqs[0]==3 else
          "two_pair" if freqs[:2]==[2,2] else
          "one_pair" if freqs[0]==2 else "unpaired")
    straight=_sequence(visible)
    # On the flop a three-suit board is the threat of a 2-hole-card flush;
    # four suits on the board give every holder of that suit a flush.
    wet=s>=3 or straight in ("four","made")
    if rank in ("full_house","quads"):category="B10"
    elif rank=="trips":category="B09"
    elif rank=="two_pair":category="B08"
    elif rank=="one_pair":category="B07" if wet else "B06"
    elif straight=="made" or s==5:category="B05"
    elif s>=3 and straight in ("four","made"):category="B04"
    elif s==4:category="B02"
    elif s==3:category="B03"
    elif straight=="four":category="B01"
    else:category="B11"
    canonical=classify_board(board_ids[:limit],street)
    return {"id":category,"catalog_id":canonical["id"],"label":BOARDS[category],"street":street,
            "suit":suit,"rank_texture":rank,"straight":straight,
            "board_cards":len(visible)}


def _pair_ranks(hand):
    c=Counter(_ranks(hand))
    return sorted((rank for rank,n in c.items() if n>=2),reverse=True)


def _trip_rank(hand):
    c=Counter(_ranks(hand))
    return max((rank for rank,n in c.items() if n>=3),default=0)


def _quads_rank(hand):
    c=Counter(_ranks(hand))
    return max((rank for rank,n in c.items() if n>=4),default=0)


def _hand_origin(hole,board,category):
    hand=hole+board
    bc=Counter(_ranks(board))
    hc=Counter(_ranks(hole))
    if category==0:return "high_card"
    if category==1:
        pair=_pair_ranks(hand)[0]
        return ("board_pair" if bc[pair]>=2 else
                "pocket_pair" if hc[pair]==2 else "own_pair")
    if category==2:
        pair=_pair_ranks(hand)[:2]
        board_pairs=sum(bc[rank]>=2 for rank in pair)
        return ("two_pair_board" if board_pairs==2 else
                "two_pair_mixed" if board_pairs==1 else "two_pair_own")
    if category==3:
        trip=_trip_rank(hand)
        return ("board_trips" if bc[trip]>=3 else
                "trips" if bc[trip]==2 else "set")
    return {4:"straight",5:"flush",6:"full_house",
            7:"quads",8:"straight_flush"}[category]


def _hole_use(hole,board,score):
    # Minimum number of HERO cards needed to make a BEST five-card hand.
    # This detects shared board straights/flushes independently of category.
    if len(board)==5 and eval_hand([],board)==score:return 0
    if len(board)>=4:
        for card in hole:
            if eval_hand([card],board)==score:return 1
    return 2


def hand_details(hero_ids, board_ids, street):
    if street=="preflop" or hero_ids is None:
        return {"category":None,"category_name":"Неизвестно",
                "origin":"unavailable","origin_name":ORIGINS["unavailable"],
                "hole_use":None,"score":None}
    hole=cards(hero_ids)
    board=cards(board_ids[:{"flop":3,"turn":4,"river":5}[street]])
    score=eval_hand(hole,board)
    category=score>>24
    origin=_hand_origin(hole,board,category)
    return {"category":category,"category_name":_CAT[category],
            "origin":origin,"origin_name":ORIGINS[origin],
            "hole_use":_hole_use(hole,board,score),"score":score}


def _same_category_cause(hero,opponent,category):
    if category==0:return "C06"  # Different high-card/kicker vectors
    if category==1:
        return "C05" if _pair_ranks(hero)[0]!=_pair_ranks(opponent)[0] else "C06"
    if category==2:
        return "C05" if _pair_ranks(hero)[:2]!=_pair_ranks(opponent)[:2] else "C06"
    if category==3:
        return "C05" if _trip_rank(hero)!=_trip_rank(opponent) else "C06"
    if category==7:
        return "C05" if _quads_rank(hero)!=_quads_rank(opponent) else "C06"
    return "C05"  # Straight, flush, full house, straight flush strength


def classify_attribution(picked, board_ids, event, net_bb, street, players=(), winners=()):
    """Exactly one financial branch and cause; board is *last visible* street.

    The strongest still-in-hand opponent is used only to describe ranking.
    A conflict between payout and best-hand comparison is labelled C08.
    No opponent cards are consulted for a hand ending without showdown.
    """
    actual=street if street in ("preflop","flop","turn","river") else "preflop"
    board=board_texture(board_ids,actual)
    hero_cards=next((hand for pid,hand,_ in picked if pid=="HERO"),None)
    hero=hand_details(hero_cards,board_ids,actual)
    if event=="uncontested":code="C01";detail=CAUSES[code]
    elif event.startswith("fold_"):code="C03";detail=CAUSES[code]+" · "+actual
    elif event=="win_without_showdown":code="C02";detail=CAUSES[code]+" · "+actual
    else:
        active=[hand for pid,hand,_ in picked if pid!="HERO" and pid in players]
        if not active:
            code="C08";detail="Не указан открывший карты соперник"
        else:
            visible=cards(board_ids[:5])
            hhole=cards(hero_cards)
            hscore=eval_hand(hhole,visible)
            opp=max(active,key=lambda h:eval_hand(cards(h),visible))
            vhole=cards(opp)
            vscore=eval_hand(vhole,visible)
            hcat,vcat=hscore>>24,vscore>>24
            hero_top=hscore>vscore
            # Net can be negative for a payout winner if contribution exceeds
            # all pots won; do not call that a conventional outright win.
            conflict=(("HERO" in winners and hscore<vscore) or
                      ("HERO" not in winners and hscore>vscore))
            if conflict:
                code="C08";detail=CAUSES[code]
            elif hscore==vscore:
                code="C07";detail=CAUSES[code]
            elif hcat!=vcat:
                code="C04";detail=_CAT[hcat]+" против "+_CAT[vcat]
            else:
                code=_same_category_cause(hhole+visible,vhole+visible,hcat)
                detail=CAUSES[code]+" · "+_CAT[hcat]
    sign="profit" if net_bb>0 else "loss" if net_bb<0 else "neutral"
    return {"cause":code,"cause_name":CAUSES[code],"detail":detail,
            "sign":sign,"board":board,"hero":hero}
