"""Canonical physical-board taxonomy: P / S / F / SF (river v2, ace remains available from physical cards).

Exactly 75 codes across the 2,598,960 possible five-card river boards,
independent of HERO / opponent cards. The same code is used by Sheet 03,
the plan EV attribution, and sampled turn/river histories. Missing streets
are explicitly tagged: PRE|NO_BOARD, FLOP|..., TURN|... and never entered
into the 150-river reference universe.
"""
from collections import Counter
from postflop_compact16 import selected_features
import re

RANKS="23456789TJQKA"
SUITS="cdhs"
P_NAMES=("Без пары", "Пара на столе", "Две пары на столе",
         "Тройка на столе", "Фулл-хаус на столе", "Каре на столе")
S_NAMES=("Без выраженной стрит-угрозы", "Стрит −2 · три подряд",
         "Стрит с двумя дырками", "Стрит −1 · четыре подряд",
         "Стрит с одной дыркой", "Стрит на столе")
F_NAMES={1:"Разные масти",2:"Флеш невозможен по мастям борда",
         3:"Флеш −2 · три одной масти",
         4:"Флеш −1 · четыре одной масти",5:"Флеш на столе"}
SF_NAMES=("Без выраженной стрит-флеш-угрозы",
          "Стрит-флеш −2 · три подряд", "Стрит-флеш с двумя дырками",
          "Стрит-флеш −1 · четыре подряд",
          "Стрит-флеш с одной дыркой", "Стрит-флеш на столе")

# A=1 can serve as rank one in the wheel; it remains rank 14 otherwise.
WINDOWS=[tuple(12 if x==1 else x-2 for x in range(lo,lo+5))
         for lo in range(1,11)]
RANK_PATTERN=re.compile(r"^(10|[2-9TJQKA]|1[1-4])([cdhs])$",re.I)


def parse_physical_board(value, *, streets=(3,4,5)):
    """Parse '14s-13h-9c-5d-2c' or 'As Kh 9c 5d 2c'."""
    if not isinstance(value,str):raise ValueError("Борд должен быть строкой")
    items=re.split(r"[\s,;\-]+",value.strip())
    if len(items) not in streets:
        raise ValueError("Требуется ровно "+"/".join(map(str,streets))+" физических карт")
    result=[]
    for item in items:
        m=RANK_PATTERN.fullmatch(item)
        if not m:raise ValueError("Некорректная карта: "+item)
        rank=m.group(1).upper()
        rank=str(int(rank)) if rank.isdigit() else rank
        numeric=int(rank) if rank.isdigit() else RANKS.index(rank)+2
        if not 2<=numeric<=14:raise ValueError("Ранг карты вне диапазона")
        result.append((numeric-2)*4+SUITS.index(m.group(2).lower()))
    if len(set(result))!=len(result):
        raise ValueError("Одна физическая карта повторяется")
    return result


def _sequence(mask):
    best=(0,0)
    for window in WINDOWS:
        flags=[(mask>>x)&1 for x in window]
        n=sum(flags)
        if n==5:return 5
        if n==4:
            strength=(4,2 if all(flags[:4]) or all(flags[1:]) else 1)
        elif n==3:
            strength=(3,2 if any(all(flags[i:i+3]) for i in range(3)) else 1)
        else:continue
        if strength>best:best=strength
    return { (0,0):0,(3,2):1,(3,1):2,
             (4,2):3,(4,1):4 }.get(best,0)


def classify_board(board_ids, street=None):
    """Exclusive physical board ID; accepts int cards rankIndex*4+suitIndex."""
    ids=list(board_ids)
    if street is None:street={0:"preflop",3:"flop",4:"turn",5:"river"}.get(len(ids))
    if street not in ("preflop","flop","turn","river"):
        raise ValueError("Неверная улица")
    expected={"preflop":0,"flop":3,"turn":4,"river":5}[street]
    if len(ids)!=expected:raise ValueError("Количество карт не совпадает с улицей")
    if len(set(ids))!=len(ids) or any(not isinstance(x,int) or not 0<=x<52 for x in ids):
        raise ValueError("Борд содержит невозможные физические карты")
    if street=="preflop":
        return {"id":"PRE|NO_BOARD","street":"preflop",
                "p":None,"s":None,"f":None,"sf":None,"a":None,
                "label":"До флопа · борда нет"}
    ranks=[x//4 for x in ids]
    suits=[x%4 for x in ids]
    occ=sorted(Counter(ranks).values(),reverse=True)
    p=(5 if occ[0]==4 else 4 if occ==[3,2] else
       3 if occ[0]==3 else 2 if occ[:2]==[2,2] else
       1 if occ[0]==2 else 0)
    suit_groups=[0,0,0,0]
    for rank,suit in zip(ranks,suits):
        suit_groups[suit]|=1<<rank
    mask=0
    for rank in set(ranks):mask|=1<<rank
    s=_sequence(mask)
    f=max(Counter(suits).values())
    sf=max((_sequence(m) for m in suit_groups),default=0)
    a=int(12 in ranks)
    code=f"P{p} · S{s} · F{f} · SF{sf}"
    if street!="river":code=street.upper()+"|"+code
    return {"id":code,"street":street,"p":f"P{p}","s":f"S{s}",
            "f":f"F{f}","sf":f"SF{sf}","a":f"A{a}",
            "label":f"{P_NAMES[p]} · {S_NAMES[s]} · {F_NAMES[f]} · {SF_NAMES[sf]}",
            "compact":selected_features(ids,p,s,f,sf)}


def classify_request(payload):
    raw=payload.get("board","") if isinstance(payload,dict) else ""
    cards=parse_physical_board(raw)
    info=classify_board(cards)
    info["cards"]="-".join(f"{x//4+2}{SUITS[x%4]}" for x in cards)
    return info
