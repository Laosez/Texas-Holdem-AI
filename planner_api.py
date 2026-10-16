"""HTTP controller for Screen 2 (Plan), using standard-library only.

No untrusted file paths; all protected endpoints remain behind the existing
X-Runner-Key authentication in replit_simulator.Handler.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import secrets
import threading
from concurrent.futures import ThreadPoolExecutor

import planner_core as core
import planner_equity as equity

LOCK = threading.RLock()
EQUITY_TASKS = {}
# Bounded background task pool. Two simultaneous independent MC runs, the rest
# queue up without blocking HTTP threads. CPU Python work remains GIL-limited.
MAX_EQUITY_WORKERS = 2
MAX_EQUITY_PENDING = 8
EQUITY_EXECUTOR = ThreadPoolExecutor(max_workers=MAX_EQUITY_WORKERS,thread_name_prefix="poker-mc")
# One full-matrix multicore computation at once, to keep CPU/RAM bounded.
POSTFLOP_EXECUTOR = ThreadPoolExecutor(max_workers=1,thread_name_prefix="poker-postflop")
CACHE_PATH = core.DATA_ROOT / "plan_equity_cache"


def catalog():
    return {"builtins": [{"ref": ref, "name": label} for ref, label in core.BUILTINS.items()],
            "saved": core.list_saved(), "hands": list(core.HANDS),
            "boxes": core.boxes_v5(), "actions": list(core.ACTIONS),
            "scenarios": {s: list(actions) for s, actions in core.SCENARIOS.items()},
            "max_opponents": 8, "method": "Monte Carlo all-in, split-pot equity"}


def _path(p):
    if not isinstance(p, str) or len(p) > 160:
        raise ValueError("Неверная ссылка на пресет")
    return p


def resolve(profile, position, scenario, players=9, stack_bb=20):
    return core.preset(_path(profile), str(position), str(scenario), int(players), float(stack_bb))


def _source_hash():
    sha=hashlib.sha256()
    for filename in ("planner_core.py","planner_equity.py","planner_eval_fast.py",
                     "strategy_catalog/a17_v5.json","bots/gto_bot.py"):
        file=core.ROOT/filename
        sha.update(hashlib.sha256(file.read_bytes()).digest())
    return sha.hexdigest()


def _query_identity(payload):
    # Cached output is invalidated by any source/range revision or MC method change.
    parts={"model":payload["model"],"trials":payload["trials"],"cycles":payload.get("cycles",1),
           "opponents":[],"source":_source_hash()}
    for p in payload["opponents"]:
        profile=p["profile"]
        entry={"entry_mode":p.get("entry_mode","always"),
               "entry_pct":p.get("entry_pct",100.0)}
        scenario="rfi" if payload["model"]!="selected" else p["scenario"]
        if profile=="inline:hero":
            parts["opponents"].append({"profile":profile,"position":p["position"],
                                      "scenario":scenario,
                                      "weights":equity.safe_inline_weights(p["weights"]),**entry})
            continue
        doc=resolve(profile,p["position"],scenario,p["players"])
        parts["opponents"].append({"profile":doc.get("ref",profile),"position":doc["position"],
                                   "scenario":doc["scenario"],"weights":core.range_weights(
                                   doc,p.get("selector","active") if payload["model"]=="selected" else "active"),
                                   **entry})
    packed=json.dumps(parts,ensure_ascii=False,sort_keys=True,separators=(",",":"))
    return hashlib.sha256(packed.encode()).hexdigest()


def _validate_request(raw):
    if not isinstance(raw,dict):
        raise ValueError("Неверный формат фильтра")
    opponents=raw.get("opponents")
    if not isinstance(opponents,list) or not 1<=len(opponents)<=8:
        raise ValueError("Выбери 1–8 соперников")
    model=raw.get("model","selected")
    if model not in ("selected","any_two","gto_heuristic"):
        raise ValueError("Неизвестная модель equity")
    cycles=raw.get("cycles",1)
    if type(cycles) is not int or not 1<=cycles<=4:
        raise ValueError("Циклов расчёта должно быть от 1 до 4")
    trials=raw.get("trials",200)
    if type(trials) is not int or not 50<=trials<=2000:
        raise ValueError("Симуляций на руку должно быть 50–2000")
    cleaned=[]
    for entry in opponents:
        if not isinstance(entry,dict):
            raise ValueError("Неверная настройка соперника")
        source=entry.get("profile","builtin:any_two")
        if source not in core.BUILTINS and source!="inline:hero" and not core.REF.fullmatch(str(source)):
            raise ValueError("Неизвестная стратегия соперника")
        pos=str(entry.get("position","3"))
        scen=str(entry.get("scenario","rfi"))
        n=entry.get("players",9)
        if type(n) is not int:
            raise ValueError("Некорректный формат стола")
        core.validate_context(n,pos,scen)
        selector=str(entry.get("selector","active"))
        if selector!="active" and selector not in core.ACTIONS:
            raise ValueError("Неизвестный фильтр действий")
        entry_mode=entry.get("entry_mode","always")
        entry_pct=entry.get("entry_pct",100.0)
        if entry_mode not in ("always","range","manual","never"):
            raise ValueError("Режим вероятности входа неизвестен")
        if type(entry_pct) not in (int,float) or not 0<=entry_pct<=100:
            raise ValueError("Вероятность входа: 0–100%")
        import math
        if not math.isfinite(entry_pct):
            raise ValueError("Вероятность входа должна быть конечным числом")
        if source=="inline:hero":
            if model!="selected" or selector!="active":
                raise ValueError("Live-диапазон возможен только для selected/active")
            weights=equity.safe_inline_weights(entry.get("weights"))
            cleaned.append({"profile":source,"position":pos,"scenario":scen,
                            "players":n,"selector":selector,"weights":weights,
                            "entry_mode":entry_mode,"entry_pct":float(entry_pct)})
        else:
            cleaned.append({"profile":source,"position":pos,"scenario":scen,
                            "players":n,"selector":selector,
                            "entry_mode":entry_mode,"entry_pct":float(entry_pct)})
    return {"opponents":cleaned,"model":model,"trials":trials,"cycles":cycles}


def _cached_task(identity):
    target=CACHE_PATH/(identity+".json")
    if target.is_file():
        result=json.loads(target.read_text(encoding="utf-8"))
        if isinstance(result,dict) and isinstance(result.get("equity"),dict) and len(result["equity"]) in (1,17,169):
            return {"id":identity,"status":"completed","done":1,"total":1,"result":result,"cached":True}
    return None


def _schedule(identity,compute,total,executor=None):
    # In-memory task metadata is bounded; no unbounded thread spawning.
    CACHE_PATH.mkdir(parents=True,exist_ok=True)
    cached=_cached_task(identity)
    if cached:return cached
    with LOCK:
        current=EQUITY_TASKS.get(identity)
        if current:return public_task(current)
        pending=sum(t["status"] in ("queued","running") for t in EQUITY_TASKS.values())
        if pending>=MAX_EQUITY_PENDING:
            raise RuntimeError("Очередь Monte Carlo заполнена (8 циклов/расчётов). Дождись свободного слота.")
        if len(EQUITY_TASKS)>24:
            for key in list(EQUITY_TASKS):
                if EQUITY_TASKS[key]["status"] not in ("queued","running"):
                    EQUITY_TASKS.pop(key)
                if len(EQUITY_TASKS)<=16:break
        job={"id":identity,"status":"queued","done":0,"total":total,
             "result":None,"error":None,"cached":False}
        EQUITY_TASKS[identity]=job
        def execute():
            with LOCK:job["status"]="running"
            try:
                def progress(done,goal):
                    with LOCK:job.update(done=done,total=goal)
                result=compute(progress)
                target=CACHE_PATH/(identity+".json")
                # UUID temporary name protects the same cache from parallel writers.
                tmp=CACHE_PATH/(identity+"."+secrets.token_hex(6)+".partial")
                try:
                    tmp.write_text(json.dumps(result,ensure_ascii=False,separators=(",",":")),encoding="utf-8")
                    os.replace(tmp,target)
                finally:
                    tmp.unlink(missing_ok=True)
                with LOCK:job.update(status="completed",done=job["total"],result=result)
            except Exception as exc:
                with LOCK:job.update(status="failed",error=str(exc))
        try:(executor or EQUITY_EXECUTOR).submit(execute)
        except Exception:
            EQUITY_TASKS.pop(identity,None)
            raise
        return public_task(job)


def start_postflop_ev(raw,busy=False):
    """Run full multi-street line simulation; separate from historic all-in equity."""
    if busy:
        raise RuntimeError("Заверши турнирную серию перед запуском постфлоп EV")
    from planner_postflop_ev import validate_request,calculate_parallel
    payload=validate_request(raw)
    equity.build_ranges(payload["opponents"], "selected")
    # Pin to exact current range revisions + policy implementation hashes.
    digest=hashlib.sha256()
    for name in ("planner_postflop_ev.py","planner_eval_fast.py","core/fast_eval.py","bots/postflop_profiles.py",
                 "bots/postflop_archetypes_v1.py","bots/gto_postflop_v2.py",
                 "bots/gto_postflop_v3.py","planner_ev_decomposition.py",
                 "core/engine.py"):
        digest.update((core.ROOT/name).read_bytes())
    key={
        "type":"postflop_line_rollout_v1",
        "ranges":_query_identity(payload),
        "hero":payload["hero_postflop"],
        "position":payload["hero_position"],
        "stack":payload["hero_stack_bb"],
        "villains":[p["postflop"] for p in payload["opponents"]],
        "hand":payload["hand"],
        "rules_sha":digest.hexdigest(),
    }
    identity=hashlib.sha256(json.dumps(key,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    from replit_simulator import max_safe_workers
    workers=max_safe_workers() if not payload["hand"] else 1
    return _schedule(identity,lambda progress:calculate_parallel(
                         payload,progress=progress,workers=workers),
                     1 if payload["hand"] else len(core.HANDS),
                     executor=POSTFLOP_EXECUTOR)


def start_equity(raw,busy=False):
    if busy:raise RuntimeError("Дождись завершения турниров перед тяжёлым расчётом equity")
    payload=_validate_request(raw)
    equity.build_ranges(payload["opponents"],payload["model"])
    identity=_query_identity(payload)
    return _schedule(identity,lambda progress:equity.calculate_matrix(**payload,progress=progress),
                     len(core.HANDS)*payload["cycles"])


def start_box_equity(raw,busy=False):
    """True joint box-range vs all selected villain ranges (not threshold coverage)."""
    if busy:raise RuntimeError("Дождись завершения турниров перед расчётом equity коробок")
    if not isinstance(raw,dict):raise ValueError("Неверные настройки equity коробок")
    payload=_validate_request({"opponents":raw.get("opponents"),"model":"selected",
                               "trials":raw.get("trials",200),"cycles":raw.get("cycles",1)})
    boxes=core.validate_boxes(raw.get("boxes"))
    groups={str(b):{h:1.0 for h in core.HANDS if boxes[h]==b} for b in range(1,18)}
    sources,_=equity.build_ranges(payload["opponents"],"selected")
    # A complete map is provided, but the cache depends only on 17 memberships.
    identity=hashlib.sha256(json.dumps(
        {"type":"joint-box-equity-v1","groups":groups,"opponents":_query_identity(payload),
         "trials":payload["trials"],"cycles":payload["cycles"],"source":_source_hash()},
        ensure_ascii=False,sort_keys=True,separators=(",",":")).encode()).hexdigest()
    total=sum(bool(v) for v in groups.values())*payload["cycles"]
    def calculate(progress):
        result={};done=0
        for b,weights in groups.items():
            if not weights:
                result[b]=None
                continue
            outputs=[]
            for cycle in range(payload["cycles"]):
                seed=int(hashlib.sha256(f"{identity}:{b}:{cycle}".encode()).hexdigest()[:15],16)
                outputs.append(equity.simulate_range_equity(weights,sources,
                               trials=max(200,payload["trials"]),seed=seed)["equity_pct"])
                done+=1
                progress(done,total)
            result[b]=round(sum(outputs)/len(outputs),2)
        return {"method":"joint_range_multiway_MC_box_V1","equity":result,
                "trials_per_box":max(200,payload["trials"])*payload["cycles"],
                "cycles":payload["cycles"],
                "note":"Прямое Monte Carlo выставление всех рук каждой коробки vs совместные диапазоны выбранных соперников; 4/6/12 комбо, блокеры, split pots. Пустые коробки не оцениваются."}
    return _schedule(identity,calculate,total)


def public_task(job):
    with LOCK:
        return dict(job)


def get_task(id_):
    if not len(id_)==64 or not all(x in "0123456789abcdef" for x in id_):
        raise ValueError("Неверный ID расчёта")
    with LOCK:
        if id_ in EQUITY_TASKS:
            return public_task(EQUITY_TASKS[id_])
    target=CACHE_PATH/(id_+".json")
    if target.is_file():
        return {"id":id_,"status":"completed","done":169,"total":169,
                "result":json.loads(target.read_text(encoding="utf-8")),"cached":True}
    raise KeyError(id_)


def get_route(handler,path):
    from urllib.parse import parse_qs,urlparse
    q=parse_qs(urlparse(handler.path).query)
    if path=="/api/plan/catalog":
        handler.reply(200,catalog())
        return True
    if path=="/api/plan/source":
        p=lambda k,d:q.get(k,[d])[0]
        try:
            doc=resolve(p("profile","builtin:a17_v5"),p("position","3"),
                        p("scenario","rfi"),int(p("players",9)),float(p("stack_bb",20)))
            handler.reply(200,doc)
        except KeyError:
            handler.reply(404,{"error":"Стратегия не найдена"})
        except (ValueError,TypeError) as exc:
            handler.reply(400,{"error":str(exc)})
        return True
    if path.startswith("/api/plan/postflop/"):
        try:
            handler.reply(200,get_task(path.rsplit("/",1)[-1]))
        except KeyError:
            handler.reply(404,{"error":"Постфлоп расчёт не найден"})
        except ValueError as exc:
            handler.reply(400,{"error":str(exc)})
        return True
    if path.startswith("/api/plan/equity/"):
        try:
            handler.reply(200,get_task(path.rsplit("/",1)[-1]))
        except KeyError:
            handler.reply(404,{"error":"Расчёт не найден"})
        except ValueError as exc:
            handler.reply(400,{"error":str(exc)})
        return True
    return False


def post_route(handler,path,payload,busy=False):
    if path=="/api/plan/strategies":
        parent=payload.get("parent") if isinstance(payload,dict) else None
        try:
            result=core.save_plan(payload.get("plan"),parent)
            handler.reply(201,result)
        except (ValueError,TypeError) as exc:
            handler.reply(400,{"error":str(exc)})
        except (KeyError,RuntimeError) as exc:
            handler.reply(409,{"error":str(exc)})
        return True
    if path=="/api/plan/boxes-equity":
        try:
            result=start_box_equity(payload,busy=busy)
            handler.reply(200 if result["status"]=="completed" else 202,result)
        except (ValueError,TypeError,KeyError) as exc:
            handler.reply(400,{"error":str(exc)})
        except RuntimeError as exc:
            handler.reply(409,{"error":str(exc)})
        return True
    if path=="/api/plan/postflop":
        try:
            result=start_postflop_ev(payload,busy=busy)
            handler.reply(200 if result["status"]=="completed" else 202,result)
        except (ValueError,TypeError,KeyError) as exc:
            handler.reply(400,{"error":str(exc)})
        except RuntimeError as exc:
            handler.reply(409,{"error":str(exc)})
        return True
    if path=="/api/plan/equity":
        try:
            result=start_equity(payload,busy=busy)
            handler.reply(200 if result["status"]=="completed" else 202,result)
        except (ValueError,TypeError,KeyError) as exc:
            handler.reply(400,{"error":str(exc)})
        except RuntimeError as exc:
            handler.reply(409,{"error":str(exc)})
        return True
    if path=="/api/plan/range-equity":
        try:
            if busy:
                raise RuntimeError("Сначала заверши турнирную серию")
            settings=_validate_request({"opponents":payload["opponents"],"model":"selected","trials":200})
            trials=payload.get("trials",3000)
            if type(trials) is not int or not 200<=trials<=20000:
                raise ValueError("Симуляций для range equity: 200–20000")
            hero=core.validate_plan(payload["hero"])
            sources,_=equity.build_ranges(settings["opponents"],"selected")
            weights=core.range_weights(hero)
            if not weights:
                raise ValueError("Выбранная стратегия не содержит активного диапазона")
            key_data={"hero_weights":weights,"opponents":_query_identity(settings),
                      "trials":trials,"source":_source_hash()}
            key=hashlib.sha256(json.dumps(key_data,sort_keys=True).encode()).hexdigest()
            CACHE_PATH.mkdir(parents=True,exist_ok=True)
            target=CACHE_PATH/("range_"+key+".json")
            if target.is_file():
                result=json.loads(target.read_text(encoding="utf-8"))
                result["cached"]=True
            else:
                result=equity.simulate_range_equity(weights,sources,trials=trials,seed=int(key[:15],16))
                tmp=target.with_suffix(".partial")
                tmp.write_text(json.dumps(result,ensure_ascii=False),encoding="utf-8")
                os.replace(tmp,target)
                result["cached"]=False
            handler.reply(200,result)
        except (ValueError,TypeError,KeyError) as exc:
            handler.reply(400,{"error":str(exc)})
        except RuntimeError as exc:
            handler.reply(409,{"error":str(exc)})
        return True
    if path=="/api/plan/compare":
        try:
            hero=core.validate_plan(payload["hero"])
            villain=core.validate_plan(payload["villain"])
            handler.reply(200,core.compare_docs(hero,villain))
        except (ValueError,KeyError,TypeError) as exc:
            handler.reply(400,{"error":str(exc)})
        return True
    return False


def delete_route(handler,path):
    match=__import__("re").fullmatch(r"/api/plan/strategies/([a-f0-9]{12})",path)
    if not match:
        return False
    try:
        handler.reply(200,core.delete_plan(match.group(1)))
    except KeyError:
        handler.reply(404,{"error":"Стратегия не найдена"})
    except ValueError as exc:
        handler.reply(400,{"error":str(exc)})
    return True
