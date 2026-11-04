"""Connect costly Shadow decisions with their exact recorded Hero cards.

All lookups use a server-owned session JSONL and immutable line numbers; no
user-provided cards, session paths, opponent hidden cards, or replay guesses.
Historical V2 reports can be joined with original events without re-simulating.
"""
import json
from collections import defaultdict
from itertools import islice
from pathlib import Path

from gto5_shadow_report import compare


def identity(row):
    return (str(row.get("tournament")), str(row.get("hand_id")),
            str(row.get("street")), tuple(row.get("board") or ()),
            str(row.get("actor")), str(row.get("reference_model")),
            str(row.get("chosen5")), str(row.get("opponents")),
            round(float(row.get("regret_bb") or 0), 4))


def enrich_legacy_report(report, source_path):
    """Fill historical worst rankings with Hero+index when match is unique.

    V3 already has stable line ids; legacy V2 only has the source records.
    Refuse to attach ambiguous duplicate decisions.
    """
    paths = [report] + list(report.get("comparisons") or ())
    rows = [row for group in paths for row in
            (group.get("rankings") or {}).get("worst_decisions", ())
            if row.get("shadow_id") is None]
    if not rows or not source_path.is_file():
        return report
    wanted = {identity(row) for row in rows}
    matches = defaultdict(list)
    with source_path.open("r", encoding="utf-8") as stream:
        for i, line in enumerate(stream):
            if not line.strip():
                continue
            record = json.loads(line)
            # Avoid costly compare() for unrelated records.
            quick = (str(record.get("tournament")), str(record.get("hand_id")),
                     str(record.get("street")),
                     tuple(record.get("board") or ()),
                     str(record.get("actor")), str(record.get("reference_model")),
                     str(record.get("chosen5")))
            if not any(key[:7] == quick for key in wanted):
                continue
            summary, reason = compare(record)
            if reason is None:
                key = identity(summary)
                if key in wanted:
                    matches[key].append((i, record))
    for row in rows:
        found = matches.get(identity(row), ())
        if len(found) == 1:
            i, rec = found[0]
            row["shadow_id"] = i
            row["hole"] = rec.get("hole") or []
            row["bot"] = rec.get("bot")
        elif len(found) > 1:
            row["detail_unavailable_reason"] = "Несколько одинаковых Shadow-решений — нельзя выбрать одно без догадки"
    return report


def get_raw_event(path, index):
    if not 0 <= index <= 10_000_000:
        raise ValueError("Индекс Shadow вне допустимого диапазона")
    with Path(path).open("r", encoding="utf-8") as stream:
        line = next(islice(stream, index, index + 1), None)
    if not line:
        raise IndexError("Решение отсутствует в исходном Shadow-журнале")
    return json.loads(line)


def get_shadow_hand(path, index, *, exact=False, complete_trace=None):
    """Complete Hero hand for V3+, sampled-only history for older sessions."""
    selected = get_raw_event(path, index)
    hand_key = (selected.get("tournament"), selected.get("hand_id"),
                selected.get("bot"), tuple(selected.get("hole") or ()))
    saved_steps = selected.get("hand_steps")
    source = "full_hand_trace" if isinstance(saved_steps, list) and saved_steps else "shadow_samples_only"
    entries = []
    with Path(path).open("r", encoding="utf-8") as stream:
        for i, line in enumerate(stream):
            if not line.strip():
                continue
            r = json.loads(line)
            if (r.get("tournament"), r.get("hand_id"),
                r.get("bot"), tuple(r.get("hole") or ())) != hand_key:
                continue
            self_ev = r.get("ev5") or {}
            ref_ev = r.get("ev41") or {}
            entries.append({
                "shadow_id": i,
                "street": r.get("street"),
                "board": r.get("board"),
                "opponents": r.get("opponents"),
                "chosen": r.get("chosen5"),
                "best_reference": max(ref_ev, key=ref_ev.get) if ref_ev else None,
                "ev_actor": self_ev,
                "ev_reference": ref_ev,
                "decision_step_index": r.get("decision_step_index"),
                "decision_inputs": r.get("decision_inputs") or {},
            })
    if saved_steps:
        steps = saved_steps
    else:
        # Only steps in original Shadow sample are recoverable for old series.
        steps = [{
            "street": r["street"], "board": r["board"],
            "hero_hole": selected.get("hole"), "opponents_count": r["opponents"],
            "decision": r["chosen"], "ev": r["ev_actor"],
            "equity_model": r["decision_inputs"],
            "shadow_id": r["shadow_id"],
        } for r in entries]
    out = {
        "shadow_id": index, "tournament": selected.get("tournament"),
        "hand_id": selected.get("hand_id"), "bot": selected.get("bot"),
        "actor": selected.get("actor"), "reference_model": selected.get("reference_model"),
        "hole": selected.get("hole") or [], "board": selected.get("board") or [],
        "street": selected.get("street"), "opponents": selected.get("opponents"),
        "chosen_actor": selected.get("chosen5"),
        "ev_actor": selected.get("ev5") or {},
        "ev_reference": selected.get("ev41") or {},
        "trace_source": source, "steps": steps, "paired_steps": entries,
        "selected_step_index": selected.get("decision_step_index"),
        "note": ("Все сохранённые решения Hero в раздаче, включая те, что не попали в Shadow."
                 if source == "full_hand_trace" else
                 "Историческая серия: восстановлены ТОЛЬКО сопоставленные Shadow-решения; "
                 "другие действия отсутствуют в исходном журнале."),
    }
    if exact:
        from bots.hand_seniority_51 import hero_seniority, hero_seniority_52
        from core.engine import eval_hand
        from gto_trace_exact_audit import exact_current_hand_audit
        hole = [tuple(x) for x in out["hole"]]
        board = [tuple(x) for x in out["board"]]
        category = eval_hand(hole, board) >> 24
        model = selected.get("model") or {}
        mass = model.get("unrounded_probability_mass") or ()
        is_rank = selected.get("actor") in ("gto51", "gto515", "gto52")
        fn = hero_seniority_52 if selected.get("actor") == "gto52" else hero_seniority
        fraction, seniority_info = (
            fn(hole, board, category_mass=mass[category] if len(mass)>category else None)
            if is_rank else (.5, {"win_fraction": .5, "method": "category centre 5.0"})
        )
        inputs = selected.get("decision_inputs") or {}
        pseudo_step = {
            "street": selected["street"], "board": selected["board"],
            "hero_hole": selected["hole"], "distribution": model,
            "equity_model": {
                "seniority": {"win_fraction": fraction, "method": seniority_info.get("method")},
                "hero_quantile": inputs.get("hero_quantile"),
            },
        }
        out["exact_audit"] = exact_current_hand_audit(pseudo_step)
        out["exact_audit"]["formula_source"] = (
            "recalculated from stored cards and distribution" if not
            inputs.get("seniority") else "stored Shadow decision model"
        )
    return out
