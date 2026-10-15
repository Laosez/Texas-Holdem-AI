"""Standardized tournament preflop responses to isolate RFI composition.

Experimental control only, NOT a GTO solver or source PokerCoaching ranges.
All seats and preflop bots use the same hand/action table AFTER the first
voluntary entry. The original bot still owns its exact RFI hand selection.
Open/3-bet/4-bet/5-bet sizing is normalized in this optional protocol.

Enabled per exporter process by POKER_PREFLOP_PROTOCOL=standard_v1; legacy
sessions, direct-bot tests and CLI runs without the env flag are unchanged.
"""
from __future__ import annotations

import random

from core.bot_api import Action
from bots.gto_bot import _hand_key

PROTOCOL = "standard_v1"
HAND_GROUPS = {
    "premium": frozenset(("AA","KK","QQ","AKs","AKo")),
    "raise_mix": frozenset(("JJ","TT","AQs","AQo","AJs","KQs")),
    "flat_pairs": frozenset(("99","88","77","66","55","44","33","22")),
    "flat_suited": frozenset((
        "A2s","A3s","A4s","A5s","A6s","A7s","A8s","A9s","ATs",
        "KTs","KJs","QTs","QJs","JTs","T9s","98s","87s","76s","65s",
    )),
    "flat_offsuit": frozenset(("AJo","KQo")),
}
# Every unspecified hand is 100% fold. We deliberately avoid assigning an
# artificial RFI chart to positions: only response ranges are universal.
def response_frequencies(stage: str, hand: str) -> dict[str, int]:
    if stage in ("vs_open", "vs_limp"):
        if hand in HAND_GROUPS["premium"]:
            return {"raise":100}
        if hand in HAND_GROUPS["raise_mix"]:
            return {"raise":50,"call":50}
        if (hand in HAND_GROUPS["flat_pairs"] or
                hand in HAND_GROUPS["flat_suited"] or
                hand in HAND_GROUPS["flat_offsuit"]):
            return {"call":100}
        return {"fold":100}
    if stage=="vs_threebet":
        if hand in ("AA","KK"):
            return {"raise":100}
        if hand in ("QQ","AKs"):
            return {"raise":50,"call":50}
        if hand in ("AKo","JJ","TT","99","AQs","AJs","KQs"):
            return {"call":100}
        return {"fold":100}
    if stage=="vs_fourbet":
        if hand in ("AA","KK"):
            return {"raise":100}
        if hand in ("QQ","AKs","AKo"):
            return {"call":100}
        return {"fold":100}
    if stage in ("vs_fivebet", "vs_shove"):
        return {"call":100} if hand in ("AA","KK","QQ","AKs","AKo") else {"fold":100}
    raise ValueError("Unknown response stage: "+stage)


def preflop_stage(view) -> str | None:
    if view.street != "preflop":
        return None
    events=[
        e for e in (view.history or ())
        if isinstance(e,dict) and e.get("street")=="preflop"
        and e.get("type") in ("call","raise","bet","all_in")
    ]
    if not events:
        return None  # Original strategy RFI, including SB limp.
    if view.to_call<=0:
        return "check"
    if view.stacks.get(view.me,0)<=view.to_call:
        return "vs_shove"
    last_aggression=next((x for x in reversed(events)
                          if x["type"] in ("raise","bet","all_in")),None)
    if last_aggression and last_aggression.get("type")=="all_in":
        return "vs_shove"
    if not last_aggression:
        return "vs_limp"
    aggression_count=sum(x["type"] in ("raise","bet","all_in") for x in events)
    if aggression_count==1:
        return "vs_open"
    if aggression_count==2:
        return "vs_threebet"
    if aggression_count==3:
        return "vs_fourbet"
    return "vs_fivebet"


def _raise_to(view, multiple: float, *, shove=False, iso_limp=False) -> Action:
    legal=view.legal_actions or ()
    raise_spec=next((x for x in legal if x["type"]=="raise"),None)
    if raise_spec is None:
        return _passive(view)
    minimum,maximum=int(raise_spec["min"]),int(raise_spec["max"])
    if shove:
        return Action("raise",maximum)
    raises=[
        e for e in (view.history or ()) if isinstance(e,dict)
        and e.get("street")=="preflop" and e.get("type") in ("raise","bet","all_in")
    ]
    if raises:
        base=int(raises[-1].get("amount") or minimum)
        target=round(base*multiple)
    else:
        # Unopened min-total raise is 2BB. Plus 1BB per preceding limp.
        limpers=sum(e.get("type")=="call" and e.get("street")=="preflop"
                    for e in (view.history or ()) if isinstance(e,dict))
        target=round(minimum*multiple + (minimum/2)*limpers) if iso_limp else round(minimum*multiple)
    return Action("raise",min(maximum,max(minimum,target)))


def _passive(view) -> Action:
    available={e["type"] for e in (view.legal_actions or ())}
    if view.to_call>0 and "call" in available:
        return Action("call")
    if "check" in available:
        return Action("check")
    if "fold" in available:
        return Action("fold")
    return Action("call") if "call" in available else Action("check")


def _fold(view) -> Action:
    available={e["type"] for e in (view.legal_actions or ())}
    return Action("fold") if view.to_call>0 and "fold" in available else _passive(view)


def response_action(view) -> Action | None:
    stage=preflop_stage(view)
    if stage is None:
        return None
    if stage=="check":
        return _passive(view)
    cards=view.hole_cards
    hand=_hand_key(cards[0][0],cards[1][0],cards[0][1]==cards[1][1])
    frequencies=response_frequencies(stage,hand)
    roll=random.random()*100
    for name,freq in frequencies.items():
        roll-=freq
        if roll<0:
            if name=="fold":
                return _fold(view)
            if name=="call":
                return _passive(view)
            if stage=="vs_open":
                return _raise_to(view,3.0)
            if stage=="vs_limp":
                return _raise_to(view,1.25,iso_limp=True)
            if stage=="vs_threebet":
                return _raise_to(view,2.3)
            return _raise_to(view,1,shove=True)
    raise AssertionError("Hand frequencies do not sum to 100%")


def normalize_rfi_raise(view, action: Action) -> Action:
    """Keep source RFI hand mix, but fix bet sizing to a shared standard."""
    if view.street!="preflop" or action.type!="raise":
        return action
    if preflop_stage(view) is not None:
        return action
    spec=next((x for x in (view.legal_actions or ()) if x["type"]=="raise"),None)
    if spec is None:
        return action
    # A normal open has a minimum raise-to of 2 BB. Target 2.5 BB
    # or 3.0 BB from SB; never exceed stacks/legal minimum.
    size=1.5 if str(view.position).upper()=="SB" else 1.25
    return _raise_to(view,size)


# Validate the core tables over all 169 canonical classes on import.
def validate_protocol():
    from bots.pc_gto_80bb_ranges import HANDS
    for stage in ("vs_limp","vs_open","vs_threebet","vs_fourbet","vs_fivebet","vs_shove"):
        for hand in HANDS:
            choices=response_frequencies(stage,hand)
            assert choices and sum(choices.values())==100 and all(
                key in ("fold","call","raise") and 0<=value<=100
                for key,value in choices.items()),(stage,hand)
validate_protocol()
