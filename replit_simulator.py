"""Browser-operated Replit frontend for the existing v4 tournament simulator.

Stage 1 migration. The poker engine, bots, and exporter remain unchanged.
Python standard library only; uses legacy engine for experiment parity.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
import shutil
import statistics
import secrets
import signal
import subprocess
import sys
import threading
import time
import tempfile
import zipfile
from collections import deque
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse
import planner_api
import planner_core

ROOT = Path(__file__).resolve().parent
UI = ROOT / "replit_ui" / "index.html"
PLAN_UI = ROOT / "replit_ui" / "plan.html"
ANALYSIS_UI = ROOT / "replit_ui" / "analysis.html"
OUT = Path(os.environ.get("POKER_DATA_DIR", str(ROOT / "output" / "replit_runs"))).resolve()
PORT = int(os.environ.get("PORT", "3000"))
TOKEN = os.environ.get("POKER_RUNNER_KEY", "").strip()
MAX_BODY = 32_768
MAX_PLAN_BODY = 2 * 1024 * 1024  # Multi-position strategy JSON, authenticated route only
MAX_ZIP_BODY = 512 * 1024 * 1024
MAX_ZIP_UNPACKED = 512 * 1024 * 1024
MAX_ARCHIVE_FILES = 50_000
MAX_LOG_LINES = 200
RUNS: dict[str, dict] = {}
MUTEX = threading.RLock()

DEFAULT_PLAYERS = [
    "split:gto:smart",
    "split:gto:gto",
    "split:gto:tag_punisher",
    "split:gto:maniac_mixed",
    "split:gto:baseline_sane",
    "a17_tag",
    "split:gto:random",
    "split:gto:random_2",
    "split:gto:pressure_filler",
]
# Exact registry-approved profiles. No shell, path, script, or arbitrary Python input.
BASE_BOTS = {
    "smart", "gto", "gto_fixed", "pc_gto_80bb", "a17_preflop", "a17_preflop_legacy", "a17_tag", "a17_tag_legacy",
    "tag_punisher", "baseline_sane", "pressure_filler",
    "wide_defender", "nit", "loose_passive", "maniac",
    "maniac_mixed", "random", "random_2", "random_3",
}
SPLIT_PARTS = frozenset(json.loads(
    (ROOT / "strategy_catalog" / "available_bases.json").read_text(encoding="utf-8")
)["bases"])

# Screen 1 choices are street-specific. The full engine catalog remains
# available for legacy CLI exports and reproducible historical sessions.
PREFLOP_CHOICES = frozenset({"a17_preflop", "gto", "pc_gto_80bb", "random"})
POSTFLOP_PRIMARY = (
    "gto_postflop_v1", "gto_postflop_20", "s100_postflop_v1", "tag_postflop_v1", "lag_postflop_v1",
    "chaser_postflop_v1", "trapper_postflop_v1", "random",
)
# The new Screen 1 editor exposes exactly these five strategies.
POSTFLOP_CHOICES = frozenset(POSTFLOP_PRIMARY)
# Old historical sessions still load their original strategy tokens.
POSTFLOP_ARCHIVE = frozenset({
    "gto", "smart", "tag_punisher", "wide_defender",
    "baseline_sane", "nit", "loose_passive", "maniac",
    "maniac_mixed", "pressure_filler", "random",
})
RANDOM_ALIAS_RE = re.compile(r"random_(?:[2-9]|10)\Z")
if not PREFLOP_CHOICES | POSTFLOP_CHOICES <= SPLIT_PARTS:
    raise RuntimeError("The UI contains an unregistered bot strategy")


def available_postflop(name: str) -> bool:
    return (name in POSTFLOP_CHOICES or name in POSTFLOP_ARCHIVE
            or bool(RANDOM_ALIAS_RE.fullmatch(name)))

# Each of the nine player seats has a separately editable preflop/postflop policy.
# Blank means INCOMPLETE, never automatic inheritance.
DEFAULT_BOT_ROWS = [
    {"pre": "a17_preflop", "post": "gto_postflop_v1"},
    {"pre": "pc_gto_80bb", "post": "gto_postflop_20"},
    {"pre": "pc_gto_80bb", "post": "tag_postflop_v1"},
    {"pre": "pc_gto_80bb", "post": "lag_postflop_v1"},
    {"pre": "pc_gto_80bb", "post": "chaser_postflop_v1"},
    {"pre": "pc_gto_80bb", "post": "trapper_postflop_v1"},
    {"pre": "a17_preflop", "post": "tag_postflop_v1"},
    {"pre": "a17_preflop", "post": "lag_postflop_v1"},
    {"pre": "a17_preflop", "post": "trapper_postflop_v1"},
]
PROGRESS_RE = re.compile(
    r"(\d+)/(\d+) tournaments\s*·\s*([\d.]+) tournaments/min\s*·\s*([\d.]+) hands/s"
)
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_]{5,64}$")
ARCHIVE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
CHECKPOINT_RE = re.compile(r"^_checkpoints/(?:config\.json|[0-9]{6}\.json\.gz)$")

def strategy_fingerprint(exporter_digest_override=None):
    # Binds experiment to implementation, including future policy modules.
    # A known exporter-only memory optimization may reuse the previous
    # strategy fingerprint without accepting unknown gameplay changes.
    paths = sorted((ROOT / "bots").glob("*.py")) + sorted((ROOT / "core").glob("*.py"))
    paths += [ROOT / "export_preflop_ranges_v4.py",
              ROOT / "run_tournament_stats.py", ROOT / "strategy_catalog" / "a17_v5.json",
              ROOT / "strategy_catalog" / "available_bases.json"]
    digest = hashlib.sha256()
    for path in paths:
        if path.is_file():
            digest.update(str(path.relative_to(ROOT)).encode())
            if path.name == "export_preflop_ranges_v4.py" and exporter_digest_override is not None:
                digest.update(bytes.fromhex(exporter_digest_override))
            else:
                digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()

def _container_memory_limit_gb():
    """Read actual cgroup memory limit, not host RAM (v2 and v1 supported)."""
    for name in ("/sys/fs/cgroup/memory.max",
                 "/sys/fs/cgroup/memory/memory.limit_in_bytes"):
        try:
            raw=Path(name).read_text().strip()
            if raw=="max":
                continue
            limit=int(raw)
            if 0 < limit < 1 << 55:
                return limit / (1024 ** 3)
        except (OSError,ValueError):
            continue
    return None


def _container_cpu_limit():
    """CPU quota visible inside a cgroup (v2 or v1), in whole workers."""
    try:
        quota, period = Path("/sys/fs/cgroup/cpu.max").read_text().strip().split()
        if quota != "max" and int(period) > 0:
            return max(1, int(quota) // int(period))
    except (OSError, ValueError):
        pass
    try:
        quota = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_quota_us").read_text().strip())
        period = int(Path("/sys/fs/cgroup/cpu/cpu.cfs_period_us").read_text().strip())
        if quota > 0 and period > 0:
            return max(1, quota // period)
    except (OSError, ValueError):
        pass
    return None


def max_safe_workers():
    """Expose up to 8 tournament workers within live cgroup CPU/RAM limits."""
    cpu = max(1, min(8, _container_cpu_limit() or os.cpu_count() or 1))
    if os.environ.get("RAILWAY_PROJECT_ID"):
        memory = _container_memory_limit_gb()
        # Memory is measured in GiB; Railway's '8 GB' limit is ~7.45 GiB.
        # 2–4 worker thresholds remain unchanged for earlier small plans.
        # The 5–8 worker levels reserve headroom for the API and collector.
        thresholds = (0, 2.25, 3.35, 4.5, 5.05, 5.8, 6.55, 7.25)
        ram_workers = (max((i + 1 for i, threshold in enumerate(thresholds)
                            if memory >= threshold), default=1)
                       if memory is not None else 1)
        cpu = min(cpu, ram_workers)
    # Explicit override is a safety ceiling, never permission to exceed RAM.
    override = os.environ.get("POKER_MAX_WORKERS", "").strip()
    if override:
        try:
            cpu = min(cpu, max(1, int(override)))
        except ValueError:
            pass
    return max(1, cpu)


def saved_preflop_options():
    """The same immutable versions shown by the strategy editor."""
    from bots.saved_plan_bot import token_for
    return [{"token": token_for(item["ref"]), "ref": item["ref"],
             "name": item["name"], "version": item["version"],
             "contexts_count": item["contexts_count"]}
            for item in planner_core.list_saved()]


def existing_saved_token(token):
    """Reject user-supplied profile paths: tokens are canonical, known refs."""
    from bots.saved_plan_bot import PLAN_TOKEN, ref_for
    if not isinstance(token, str) or not PLAN_TOKEN.fullmatch(token):
        return False
    try:
        planner_core.get_saved(ref_for(token))
        return True
    except (KeyError, ValueError, OSError):
        return False


def strategy_catalog():
    options = sorted(SPLIT_PARTS)
    saved = saved_preflop_options()
    # Legacy "gto" is intentionally retired for NEW preflop selections;
    # its Monte Carlo postflop is useful as a historical control arm.
    # Old manifests continue to load both street tokens unchanged.
    preflop = sorted(PREFLOP_CHOICES - {"gto"}) + [item["token"] for item in saved]
    postflop = list(POSTFLOP_PRIMARY)
    return {"strategies": sorted(set(options) | set(preflop)),
            "preflop_strategies": preflop,
            "saved_preflop": saved,
            "postflop_strategies": postflop,
            "postflop_profiles": {
                "gto": {
                    "label": "GTO Old · Monte Carlo · контроль",
                    "model": "legacy_heuristic",
                    "features": ["100 Monte Carlo equity trials per decision", "C-bet", "draw", "semi-bluff", "check-raise", "river bluff"],
                },
                "gto_postflop_v1": {
                    "label": "GTO 1 · контроль (GTO-inspired, не solver)",
                    "model": "heuristic",
                    "features": ["value", "C-bet", "draw", "semi-bluff", "check-raise", "river blockers", "multiway", "SPR"]
                },
                "s100_postflop_v1": {
                    "label": "SKACHKOV S100 · общий справочник человека и бота (эксперимент)",
                    "model": "scenario_policy",
                    "features": ["100 unique states", "same JSON catalog human+bot",
                                 "hand/board classifier", "pot odds", "IP/OOP context", "multiway"]
                },
                "gto_postflop_20": {
                    "label": "GTO 2.0 · сила руки относительно борда (эвристика, не solver)",
                    "model": "heuristic",
                    "features": ["R0–R4 board-relative hand strength", "shared board-pair discount",
                                 "genuine two-pair exception", "wet board caution",
                                 "same V1 betting engine for controlled EV comparisons"]
                },
                "lag_postflop_v1": {
                    "label": "LAG Postflop V1 (агрессивный эксперимент)",
                    "model": "heuristic",
                    "features": ["value", "high C-bet", "semi-bluff", "air bluff", "check-raise", "river blockers", "multiway", "SPR"]
                },
                "tag_postflop_v1": {
                    "label": "TAG Postflop V1 · disciplined",
                    "model": "heuristic",
                    "features": ["selective value", "pot odds", "low bluff", "draws"]
                },
                "chaser_postflop_v1": {
                    "label": "Draw Chaser Postflop V1",
                    "model": "heuristic",
                    "features": ["draw pursuit", "excessive calls", "raw outs"]
                },
                "trapper_postflop_v1": {
                    "label": "Trapper Postflop V1",
                    "model": "heuristic",
                    "features": ["slowplay", "passive value", "board texture"]
                },
                "random": {
                    "label": "Random · случайные допустимые действия и размеры ставок",
                    "model": "random_baseline",
                    "features": ["uniform legal action", "random raise size", "no hand evaluation"]
                }
            },
            "preflop_protocols": {
                "legacy": "Исходные действия стратегии, старые эксперименты",
                "standard_v1": "Единые диапазоны ответов и размеры повышений; собственный RFI у каждой стратегии"
            },
            "preflop_coverage": {
                "pc_gto_80bb": {
                    "rfi": "PokerCoaching 80bb RFI 169-hand chart, 25% rounding (9-max chart indexed by position)",
                    "vs_open": "fallback:gto_fixed:positional heuristic, not PC source 3-bet chart",
                    "bb_vs_open": "fallback:gto_fixed:first-raise BB defense, no PC source chart",
                    "vs_threebet": "fallback:gto_fixed:positional heuristic, not PC source 4-bet chart",
                    "vs_fourbet": "fallback:gto_fixed:no separate PC chart"
                },
                "a17_preflop": {
                    "rfi": "A17 V5 position/box rules",
                    "vs_open": "fallback:gto_fixed except shared first BB defense",
                    "bb_vs_open": "fallback:gto_fixed:first-raise BB defense",
                    "vs_threebet": "A17 A01-A07+A09: 50% 4-bet, 50% call; others fold",
                    "vs_fourbet": "fallback:gto_fixed:no dedicated 5-bet chart"
                },
                "gto_fixed": "heuristic fallback only; no PC source response charts"
            },
            "a17_version": "A17_V5",
            "code_fingerprint": strategy_fingerprint(), "workers_max": max_safe_workers(),
            "required_streets": ["pre", "post"]}




def valid_bot(bot: str) -> bool:
    if bot in BASE_BOTS or existing_saved_token(bot):
        return True
    parts = bot.split(":")
    return (len(parts) == 3 and parts[0] == "split"
            and (parts[1] in SPLIT_PARTS or existing_saved_token(parts[1]))
            and parts[2] in SPLIT_PARTS)


def bounded_int(value, label: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{label}: требуется целое число")
    try:
        n = int(value)
    except (ValueError, TypeError):
        raise ValueError(f"{label}: требуется целое число") from None
    if str(value).strip() != str(n):
        raise ValueError(f"{label}: требуется целое число")
    if not minimum <= n <= maximum:
        raise ValueError(f"{label}: допустимый диапазон {minimum}–{maximum}")
    return n


def validate_config(data: dict) -> dict:
    if not isinstance(data, dict):
        raise ValueError("Ожидался объект настроек")
    raw_rows = data.get("bots")
    if raw_rows is not None:
        if not isinstance(raw_rows, list) or not 2 <= len(raw_rows) <= 9:
            raise ValueError("Нужны от 2 до 9 строк ботов")
        rows = []
        bots = []
        random_count = 0
        for i, row in enumerate(raw_rows, start=1):
            if not isinstance(row, dict):
                raise ValueError(f"P{i}: выбери обе стратегии")
            pre, post = row.get("pre", ""), row.get("post", "")
            if not isinstance(pre, str) or not isinstance(post, str):
                raise ValueError(f"P{i}: некорректная стратегия")
            if not pre or not post:
                raise ValueError(f"P{i}: Preflop и Postflop обязательны; пустое поле запрещает запуск")
            if pre not in PREFLOP_CHOICES and not existing_saved_token(pre):
                raise ValueError(f"P{i}: {pre} не является доступной префлоп-стратегией")
            if not available_postflop(post):
                raise ValueError(f"P{i}: {post} не является доступной постфлоп-стратегией")
            # One "Random" item in UI; unique identifiers keep per-seat
            # reports separate while previous CLI profiles remain intact.
            if post == "random" or RANDOM_ALIAS_RE.fullmatch(post):
                random_count += 1
                post = "random" if random_count == 1 else f"random_{random_count}"
            rows.append({"pre": pre, "post": post})
            bots.append(f"P{i}=split:{pre}:{post}")
    else:
        rows = None
        raw = data.get("players", DEFAULT_PLAYERS)
        if isinstance(raw, str):
            bots = [s.strip() for s in raw.split(",") if s.strip()]
        elif isinstance(raw, list) and all(isinstance(x, str) for x in raw):
            bots = [s.strip() for s in raw]
        else:
            raise ValueError("Нужен список ботов")
        if not 2 <= len(bots) <= 9 or len(set(bots)) != len(bots):
            raise ValueError("Нужны 2–9 ботов с уникальными именами")
        if not all(valid_bot(b) for b in bots):
            raise ValueError("Неизвестный бот: " + ", ".join(b for b in bots if not valid_bot(b)))
    sb = bounded_int(data.get("sb", 1), "SB", 1, 1000)
    bb = bounded_int(data.get("bb", 2), "BB", 2, 2000)
    if bb < sb:
        raise ValueError("BB должен быть не меньше SB")
    seat_mode = data.get("seat_mode", "rotate")
    if seat_mode not in ("rotate", "fixed"):
        raise ValueError("seat_mode: rotate или fixed")
    preflop_protocol = data.get("preflop_protocol", "legacy")
    if preflop_protocol not in ("legacy", "standard_v1"):
        raise ValueError("preflop_protocol: legacy или standard_v1")
    button_policy=data.get("button_policy","dead_button")
    if button_policy not in ("dead_button","moving"):
        raise ValueError("Режим баттона: dead_button или moving")
    config = {
        "players": bots, "bots": rows,
        "button_policy":button_policy,
        "tournaments": bounded_int(data.get("tournaments", 90), "Турниры", 1, 3000),
        "parallel": bounded_int(data.get("parallel", 1), "Потоки", 1, 8),
        "seed": bounded_int(data.get("seed", 2042), "Seed", 0, 2_147_483_647),
        "chips": bounded_int(data.get("chips", 500), "Стек", 10, 1_000_000),
        "sb": sb, "bb": bb,
        "blind_increase_every": bounded_int(
            data.get("blind_increase_every", 50), "Рост блайндов", 0, 10000
        ),
        "max_hands": bounded_int(data.get("max_hands", 10000), "Лимит рук", 100, 100_000),
        "seat_mode": seat_mode,
        "preflop_protocol": preflop_protocol,
    }
    if config["parallel"] > max_safe_workers():
        raise ValueError(f"Доступно не более {max_safe_workers()} процессов по CPU/RAM. Проверь ресурсы Railway и POKER_MAX_WORKERS.")
    return config


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def snapshot(job: dict) -> dict:
    error = job.get("error")
    # Historical failed runs did not persist a human-readable error.
    # Recover the diagnosis from the original process exit code, if known.
    if not error and job.get("status") == "failed":
        code = job.get("returncode")
        if code in (-9, 137):
            error = "Экспортёр остановлен SIGKILL, вероятна нехватка RAM. Контрольные точки можно восстановить."
        elif code not in (0, None):
            error = f"Экспортёр завершился с кодом {code}; проверь журнал раздач."
        elif code == 0 and job.get("report") is None:
            error = "Симуляция закончилась, но итоговый отчёт не сформирован."
    return {
        "id": job["id"], "status": job["status"], "created": job["created"],
        "updated": job["updated"], "config": job["config"],
        "log": list(job["log"]), "returncode": job["returncode"],
        "report": job.get("report"),
        "error": error,
        "progress": job.get("progress"),
        "stats": job.get("stats"),
        "performance": job.get("performance"),
        "strategy_fingerprint": job.get("strategy_fingerprint"),
    }


def persist(job: dict) -> None:
    p = OUT / job["id"] / "job.json"
    data = snapshot(job)
    data.pop("log", None)
    temporary = p.with_suffix(".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, p)


def _read_rows(file: Path) -> list[dict]:
    if not file.is_file():
        return []
    with file.open(encoding="utf-8-sig", newline="") as stream:
        return list(csv.DictReader(stream))


def stats_for_folder(folder: Path) -> dict:
    """Reconstruct audited totals and optional seat/table-size scopes from real CSV."""
    import math
    observed = {}
    positions = {"10", "9", "8", "7", "6", "5", "4", "3", "SB", "BB"}
    pre_metrics = {"vpip": "hands_observed", "pfr": "hands_observed",
                   "rfi": "rfi_opportunities", "threebet": "threebet_opportunities",
                   "fourbet": "fourbet_opportunities"}
    post_metrics = ("flop_af", "turn_af", "river_af", "flop_cbet", "turn_cbet",
                    "river_cbet", "cbet", "fold_to_bet", "check_raise", "wsd",
                    "net_bb_100")
    post_raw = tuple(f"{st}_{col}" for st in ("flop", "turn", "river")
                     for col in ("aggressive", "calls", "cbet_n", "cbet_opp")) + (
        "cbet_n", "cbet_opp", "fold_to_bet_n", "fold_to_bet_opp",
        "check_raise_n", "check_raise_opp", "wsd_n", "wsd_opp",
        "net_bb_units", "net_hands")

    def finite(value):
        try:
            number = float(value) if value not in ("", None) else None
            return number if number is not None and math.isfinite(number) else None
        except (TypeError, ValueError):
            return None

    def pre(row):
        count = finite(row.get("hands_observed"))
        if count is None or count <= 0:
            return None
        record = {"hands_observed": int(count)}
        raw = {}
        for metric, denom in pre_metrics.items():
            record[metric] = finite(row.get(metric + "_pct"))
            n, opportunity = finite(row.get(metric + "_n")), finite(row.get(denom))
            if n is not None and opportunity is not None:
                raw[metric + "_n"] = n
                raw[denom] = opportunity
        if raw:
            record["pre_raw"] = raw
        return record

    def attach_post(record, row):
        if record is None:
            return
        for metric in post_metrics:
            if metric in row:
                record[metric] = finite(row.get(metric))
        raw = {col: value for col in post_raw
               if (value := finite(row.get(col))) is not None}
        if raw:
            record["post_raw"] = raw

    # Original all-seat records stay available to imported/legacy archives.
    for row in _read_rows(folder / "summary_all.csv"):
        name = row.get("bot")
        record = pre(row)
        if name and record:
            observed[name] = record
    for row in _read_rows(folder / "postflop_summary.csv"):
        name = row.get("bot")
        if name:
            attach_post(observed.setdefault(name, {}), row)

    for row in _read_rows(folder / "summary_position_all.csv"):
        name, pos = row.get("bot"), row.get("position")
        record = pre(row)
        if name and pos in positions and record:
            observed.setdefault(name, {}).setdefault("positions", {})[pos] = record
    for row in _read_rows(folder / "postflop_position_summary.csv"):
        name, pos = row.get("bot"), row.get("position")
        record = observed.get(name, {}).get("positions", {}).get(pos)
        attach_post(record, row)

    # Compact table-size breakdown: only available where the original exporter
    # collected it. n2..n9 exists historically at total level; new position
    # CSVs are strictly optional.
    for size in range(2, 10):
        for row in _read_rows(folder / f"summary_n{size}.csv"):
            name = row.get("bot")
            record = pre(row)
            if name and record:
                observed.setdefault(name, {}).setdefault("stages", {})[
                    str(size)] = {"total": record, "positions": {}}
        for row in _read_rows(folder / f"summary_position_n{size}.csv"):
            name, pos = row.get("bot"), row.get("position")
            record = pre(row)
            stage = observed.get(name, {}).get("stages", {}).get(str(size))
            if stage and pos in positions and record:
                stage["positions"][pos] = record

    stage_raw = {}
    for row in _read_rows(folder / "postflop_position_stage_summary.csv"):
        name, pos = row.get("bot"), row.get("position")
        try:
            size = int(row.get("table_size") or 0)
        except (TypeError, ValueError):
            continue
        stage = observed.get(name, {}).get("stages", {}).get(str(size))
        if not stage or pos not in positions:
            continue
        record = stage["positions"].get(pos)
        if record is None:
            continue
        attach_post(record, row)
        pool = stage_raw.setdefault((name, size), {})
        for key, value in record.get("post_raw", {}).items():
            pool[key] = pool.get(key, 0) + value

    # Regenerate stage total postflop ratios from numerators/denominators.
    # Never average percentage values from different positions.
    for (name, size), raw in stage_raw.items():
        total = observed[name]["stages"][str(size)]["total"]
        total["post_raw"] = raw
        for street in ("flop", "turn", "river"):
            bets, calls = raw.get(street + "_aggressive", 0), raw.get(street + "_calls", 0)
            total[street + "_af"] = round(bets / calls, 4) if calls else None
        for metric in ("flop_cbet", "turn_cbet", "river_cbet", "cbet",
                       "fold_to_bet", "check_raise", "wsd"):
            n, opp = raw.get(metric + "_n", 0), raw.get(metric + "_opp", 0)
            total[metric] = round(100 * n / opp, 4) if opp else None
        net_hands = raw.get("net_hands", 0)
        total["net_bb_100"] = round(100 * raw.get("net_bb_units", 0) / net_hands, 4) if net_hands else None

    placement = {}
    for row in _read_rows(folder / "tournament_players.csv"):
        if row.get("completed") != "1":
            continue
        name = row.get("bot", "")
        entry = placement.setdefault(name, {"places": [], "top3": 0})
        try:
            place = int(row.get("position") or 0)
        except (TypeError, ValueError):
            continue
        if place < 1:
            continue
        entry["places"].append(place)
        entry["top3"] += int(place <= 3)
    for name, data in placement.items():
        result = observed.setdefault(name, {})
        places = data["places"]
        result["top3_pct"] = round(data["top3"] / len(places) * 100, 2) if places else None
        result["median_position"] = statistics.median(places) if places else None
    return observed


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def write_integrity_manifest(folder: Path) -> None:
    files = {}
    for file in sorted(folder.rglob("*")):
        if file.is_file() and not file.is_symlink() and file.name not in ("job.json", "integrity.json"):
            files[str(file.relative_to(folder))] = sha256_file(file)
    target = folder / "integrity.json"
    tmp = target.with_suffix(".tmp")
    tmp.write_text(json.dumps({"format": "SKACHKOV_INTEGRITY_V1", "files": files},
                              ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, target)


def complete_run_outputs(folder: Path) -> bool:
    """Never discard resumable checkpoints without a complete tournament export."""
    try:
        report = json.loads((folder / "tournament_report.json").read_text(encoding="utf-8"))
        requested = int(report["tournaments_requested"])
        completed = int(report["tournaments_completed"])
        unfinished = int(report["tournaments_unfinished"])
        required = ("performance.json", "metadata.json", "summary_all.csv",
                    "by_hand_169_all.csv", "by_hand_position_169_all.csv",
                    "tournaments.csv", "tournament_players.csv", "leaderboard.csv")
        return (requested > 0 and completed == requested and unfinished == 0
                and all((folder / name).is_file() for name in required))
    except (OSError, ValueError, KeyError, TypeError):
        return False


def completed_checkpoint_stats(folder: Path) -> dict:
    """Preview raw resume files; unrelated files and incomplete runs are untouched."""
    directory = folder / "_checkpoints"
    if not directory.is_dir() or directory.is_symlink() or not complete_run_outputs(folder):
        return {"files": 0, "bytes": 0}
    files = [p for p in directory.iterdir()
             if p.is_file() and not p.is_symlink()
             and re.fullmatch(r"[0-9]{6}\.json\.gz", p.name)]
    return {"files": len(files), "bytes": sum(p.stat().st_size for p in files)}


def compact_completed_checkpoints(folder: Path) -> dict:
    """Delete only redundant successful-run resume files (never partial sessions).

    Official CSV/JSON reports, timing and integrity metadata remain. The
    integrity checksum is regenerated by the caller after the compaction.
    """
    initial = completed_checkpoint_stats(folder)
    if initial["files"] == 0:
        return initial
    directory = folder / "_checkpoints"
    freed = 0
    removed = 0
    for path in directory.iterdir():
        if (path.is_file() and not path.is_symlink() and
                re.fullmatch(r"[0-9]{6}\.json\.gz", path.name)):
            freed += path.stat().st_size
            path.unlink()
            removed += 1
    return {"files": removed, "bytes": freed}


def storage_directory_breakdown() -> dict:
    """Read-only inventory of /data. Never removes or opens result contents."""
    categories = {}
    session_details = []
    for entry in OUT.iterdir():
        if entry.is_symlink():
            continue
        is_session = (entry.is_dir() and RUN_ID_RE.fullmatch(entry.name)
                      and (entry / "job.json").is_file())
        size = files = checkpoints = 0
        if entry.is_dir():
            for root, dirs, names in os.walk(entry, followlinks=False):
                dirs[:] = [name for name in dirs
                           if not (Path(root) / name).is_symlink()]
                for name in names:
                    path = Path(root) / name
                    if path.is_symlink():
                        continue
                    try:
                        length = path.stat().st_size
                    except OSError:
                        continue
                    size += length
                    files += 1
                    if is_session and "_checkpoints" in path.relative_to(entry).parts:
                        checkpoints += length
        elif entry.is_file():
            try:
                size = entry.stat().st_size
                files = 1
            except OSError:
                continue
        if is_session:
            category = "tournament_sessions"
            status = RUNS.get(entry.name, {}).get("status", "unknown")
            session_details.append({"id": entry.name, "status": status,
                                    "bytes": size, "checkpoint_bytes": checkpoints})
        else:
            category = entry.name if entry.is_dir() else "_root_files"
        bucket = categories.setdefault(category, {"bytes": 0, "files": 0, "directories": 0})
        bucket["bytes"] += size
        bucket["files"] += files
        bucket["directories"] += int(entry.is_dir())
    session_details.sort(key=lambda row: row["bytes"], reverse=True)
    by_status = {}
    for row in session_details:
        group = by_status.setdefault(row["status"],
                                     {"sessions": 0, "bytes": 0, "checkpoint_bytes": 0})
        group["sessions"] += 1
        group["bytes"] += row["bytes"]
        group["checkpoint_bytes"] += row["checkpoint_bytes"]
    return {
        "categories": dict(sorted(categories.items(),
                                  key=lambda kv: kv[1]["bytes"], reverse=True)),
        "session_statuses": by_status,
        "largest_sessions": session_details[:10],
        "file_bytes_total": sum(x["bytes"] for x in categories.values()),
        "note": "Logical file sizes; filesystem metadata and deleted-open files are not included",
    }


def storage_compaction_preview() -> dict:
    with MUTEX:
        candidates = []
        for run_id, job in RUNS.items():
            if job.get("status") not in ("completed", "imported"):
                continue
            folder = OUT / run_id
            info = completed_checkpoint_stats(folder)
            if info["files"]:
                candidates.append({"id": run_id, **info})
        return {"sessions": candidates, "checkpoint_files": sum(x["files"] for x in candidates),
                "reclaimable_bytes": sum(x["bytes"] for x in candidates)}


def compact_historical_sessions() -> dict:
    """Explicit, authenticated maintenance operation, forbidden during a live run."""
    with MUTEX:
        if any(j.get("status") in ("starting", "running") for j in RUNS.values()):
            raise RuntimeError("Сначала останови или заверши текущую симуляцию")
        processed = []
        files = 0
        freed = 0
        for run_id, job in RUNS.items():
            if job.get("status") not in ("completed", "imported"):
                continue
            folder = OUT / run_id
            if not completed_checkpoint_stats(folder)["files"]:
                continue
            inspection = audit_session(job)
            if not inspection["ok"]:
                continue
            result = compact_completed_checkpoints(folder)
            if result["files"]:
                write_integrity_manifest(folder)
                processed.append(run_id)
                files += result["files"]
                freed += result["bytes"]
        free = shutil.disk_usage(OUT).free
        return {"sessions_compacted": processed, "files_removed": files,
                "bytes_reclaimed": freed, "free_bytes": free}


def audit_session(job: dict) -> dict:
    """Inspect actual persisted files, reports and tournament checkpoint counts."""
    folder = OUT / job["id"]
    expected = [
        "tournament_report.json", "performance.json", "metadata.json",
        "tournaments.csv", "tournament_players.csv", "leaderboard.csv",
        "summary_all.csv", "by_hand_169_all.csv", "by_hand_position_169_all.csv",
        "simulation.log", "job.json",
    ]
    partial = job.get("status") not in ("completed", "imported")
    missing = [name for name in (["job.json"] if partial else expected)
               if not (folder / name).is_file()]
    checked = sum(1 for path in folder.rglob("*") if path.is_file() and not path.is_symlink()) if folder.exists() else 0
    checkpoints = folder / "_checkpoints"
    saved = len(list(checkpoints.glob("[0-9][0-9][0-9][0-9][0-9][0-9].json.gz"))) if checkpoints.is_dir() else 0
    observations = []
    if not partial:
        try:
            real = json.loads((folder / "tournament_report.json").read_text(encoding="utf-8"))
            completed = real["tournaments_completed"]
            if sum(r["wins"] for r in real["leaderboard"]) != completed:
                observations.append("Число побед не равно числу завершённых турниров")
            if completed + real["tournaments_unfinished"] != real["tournaments_requested"]:
                observations.append("Несогласованное количество турниров")
        except (OSError, ValueError, KeyError, TypeError):
            observations.append("Не удалось проверить tournament_report.json")
    checksum_file = folder / "integrity.json"
    if checksum_file.is_file():
        try:
            manifest = json.loads(checksum_file.read_text(encoding="utf-8"))
            files = manifest.get("files")
            if not isinstance(files, dict):
                raise ValueError("Неправильная структура SHA")
            for name, expected_sha in files.items():
                path = folder / name
                if not path.is_file() or sha256_file(path) != expected_sha:
                    observations.append("SHA-256 отличается или файл отсутствует: " + name)
        except (OSError, ValueError, TypeError):
            observations.append("Невозможно прочитать integrity.json")
    elif not partial:
        observations.append("Нет SHA-256 манифеста (историческая сессия)")
    if partial and saved:
        observations.append(f"Есть {saved} сохранённых checkpoints; возможен рестарт")
    return {
        "id": job["id"], "status": job.get("status"), "files": checked,
        "checkpoints": saved, "missing": missing, "observations": observations,
        "ok": not missing and not any(
            x.startswith(("SHA-256", "Невозможно", "Не удалось", "Несогласованное", "Число побед"))
            for x in observations),
    }


def worker(job: dict) -> None:
    config = job["config"]
    output = OUT / job["id"]
    output.mkdir(parents=True, exist_ok=True)
    cmd = [
        sys.executable, "-u", str(ROOT / "export_preflop_ranges_v4.py"),
        "--players", ",".join(config["players"]),
        "--tournaments", str(config["tournaments"]),
        "--parallel", str(config["parallel"]),
        "--seed", str(config["seed"]),
        "--chips", str(config["chips"]),
        "--sb", str(config["sb"]), "--bb", str(config["bb"]),
        "--blind-increase-every", str(config["blind_increase_every"]),
        "--max-hands", str(config["max_hands"]),
        "--seat-mode", config["seat_mode"],
        "--button-policy",config.get("button_policy","moving"),
        "--out", str(output),
        "--checkpoint-dir", str(output / "_checkpoints"),
    ]
    log_path = output / "simulation.log"
    try:
        env = dict(os.environ, THAI_ENGINE_IMPL="legacy", PYTHONUNBUFFERED="1",
                   POKER_PLAN_SNAPSHOT_DIR=str(output / "plan_snapshots"),
                   POKER_PREFLOP_PROTOCOL=config.get("preflop_protocol","legacy"))
        with log_path.open("a", encoding="utf-8") as log:
            log.write("\n[runner] Start or resume at " + now() +
                      " | preflop_protocol="+config.get("preflop_protocol","legacy")+"\n")
            proc = subprocess.Popen(
                cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
                start_new_session=True,
            )
            with MUTEX:
                job["process"] = proc
                if job.get("cancelled"):
                    os.killpg(proc.pid, signal.SIGTERM)
            assert proc.stdout is not None
            for line in proc.stdout:
                log.write(line)
                log.flush()
                with MUTEX:
                    job["log"].append(line.rstrip())
                    match = PROGRESS_RE.search(line)
                    if match:
                        job["progress"] = {
                            "done": int(match.group(1)), "total": int(match.group(2)),
                            "tpm": float(match.group(3)), "hps": float(match.group(4))
                        }
                    job["updated"] = now()
                    if match:
                        persist(job)
            exit_code = proc.wait()
        report_file = output / "tournament_report.json"
        report = json.loads(report_file.read_text(encoding="utf-8")) if report_file.exists() else None
        if report is not None and exit_code == 0:
            # All exports are durable and consistent: checkpoints have served
            # their resume purpose. Keep only CSV/JSON + audit manifest.
            compact_completed_checkpoints(output)
            write_integrity_manifest(output)
        with MUTEX:
            job["returncode"] = exit_code
            job["report"] = report
            if report is not None:
                job["stats"] = stats_for_folder(output)
                perf_file = output / "performance.json"
                job["performance"] = json.loads(perf_file.read_text(encoding="utf-8")) if perf_file.is_file() else None
                job["progress"] = {
                    "done": report.get("tournaments_completed", 0),
                    "total": report.get("tournaments_requested", 0),
                    "tpm": job.get("progress", {}).get("tpm") if job.get("progress") else None,
                    "hps": job.get("progress", {}).get("hps") if job.get("progress") else None,
                }
            job["status"] = ("cancelled" if job.get("cancelled")
                             else "completed" if exit_code == 0 and report is not None else "failed")
            if job["status"] == "failed":
                if exit_code in (-9, 137):
                    reason = ("Экспортёр завершился по SIGKILL (вероятный OOM: "
                              "недостаточно RAM на Railway). Контрольные точки "
                              "сохранены; можно возобновить после исправления.")
                elif exit_code != 0 and any(
                        ("No space left on device" in line or "Railway /data:" in line)
                        for line in job["log"]):
                    reason = ("На Railway закончилось место для контрольных точек турниров. "
                              "Открой «Освободить место» в разделе сессий; "
                              "незавершённые контрольные точки сохраняются. "
                              "Если места не хватит, увеличь том poker-results.")
                elif exit_code != 0:
                    reason = f"Экспортёр завершился с кодом {exit_code}; см. последние строки журнала."
                else:
                    reason = "Нет итогового tournament_report.json после выхода экспортёра."
                job["error"] = reason
                job["log"].append("[runner] " + reason)
            else:
                job["error"] = None
            job["updated"] = now()
            job.pop("process", None)
            persist(job)
    except Exception as exc:
        with MUTEX:
            job["log"].append("Сбой запуска/обработки результатов: " + repr(exc))
            job["error"] = "Ошибка обработки итоговых файлов: " + repr(exc)
            job["status"] = "failed"
            job["updated"] = now()
            job.pop("process", None)
            persist(job)


def pin_saved_plans(config: dict, folder: Path) -> None:
    """Copy exact plan revisions into session data before launching workers."""
    from bots.saved_plan_bot import PLAN_TOKEN, ref_for
    tokens = sorted({row["pre"] for row in config.get("bots", [])
                     if PLAN_TOKEN.fullmatch(row.get("pre", ""))})
    if not tokens:
        return
    target = folder / "plan_snapshots"
    target.mkdir(parents=True, exist_ok=True)
    for token in tokens:
        doc = planner_core.get_saved(ref_for(token))
        snapshot_path = target / (token + ".json")
        with snapshot_path.open("x", encoding="utf-8") as handle:
            json.dump(doc, handle, ensure_ascii=False, separators=(",", ":"))


def start_run(config: dict) -> dict:
    with MUTEX:
        if any(j["status"] in {"running", "starting"} for j in RUNS.values()):
            raise RuntimeError("Уже запущена серия турниров; дождитесь завершения или остановите её")
        OUT.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(OUT).free
        if free < 40 * 1024 * 1024:
            raise RuntimeError("На Railway /data осталось меньше 40 МБ. Открой «Освободить место» "
                               "для очистки чекпойнтов завершённых сессий или увеличь том. "
                               "Сырые чекпойнты незавершённых сессий сохраняются.")
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(3)
        job = {
            "id": run_id, "status": "starting", "created": now(), "updated": now(),
            "config": config, "returncode": None, "report": None,
            "progress": {"done": 0, "total": config["tournaments"], "tpm": None, "hps": None},
            "stats": {}, "performance": None, "strategy_fingerprint": strategy_fingerprint(),
            "log": deque(maxlen=MAX_LOG_LINES),
        }
        folder = OUT / run_id
        folder.mkdir(parents=True, exist_ok=False)
        try:
            pin_saved_plans(config, folder)
        except Exception:
            shutil.rmtree(folder, ignore_errors=True)
            raise
        RUNS[run_id] = job
        persist(job)
        job["status"] = "running"
        persist(job)
    threading.Thread(target=worker, args=(job,), daemon=True).start()
    return snapshot(job)


def resume_run(run_id: str) -> dict:
    with MUTEX:
        job = RUNS.get(run_id)
        if not job:
            raise KeyError(run_id)
        if job["status"] not in ("failed", "interrupted", "cancelled"):
            raise RuntimeError("Возобновить можно только прерванную или неуспешную сессию")
        if any(x["status"] in ("running", "starting") for x in RUNS.values()):
            raise RuntimeError("Другая серия уже выполняется")
        if not job["config"].get("players"):
            raise ValueError("Старая сессия не содержит полного состава игроков")
        # Permit the one audited exporter-only memory fix. This source change
        # does not touch gameplay or bot behavior; the exporter separately
        # checks each legacy checkpoint's exact configuration and task tuple.
        current_fingerprint = strategy_fingerprint()
        prior_fingerprint = strategy_fingerprint("c95b365dd2af4051db541b27781b94e9ccbd113477ca6c3740fcbd6c9b5d40b2")
        pre_storage_fingerprint = strategy_fingerprint("4c8d51ea7819a274c1f974b5743f9ba40b77b525ef20153ac540bc53887e8c34")
        if job.get("strategy_fingerprint") not in (current_fingerprint, prior_fingerprint, pre_storage_fingerprint):
            raise RuntimeError("Версия старой сессии неизвестна или изменилась; безопасное продолжение невозможно. Скачай ZIP для архива.")
        job["cancelled"] = False
        job["status"] = "running"
        job["returncode"] = None
        job["error"] = None
        job["updated"] = now()
        persist(job)
    threading.Thread(target=worker, args=(job,), daemon=True).start()
    return snapshot(job)


def cancel_run(run_id: str) -> dict:
    with MUTEX:
        job = RUNS.get(run_id)
        if not job:
            raise KeyError(run_id)
        if job["status"] not in {"running", "starting"}:
            return snapshot(job)
        job["cancelled"] = True
        proc = job.get("process")
        if proc is not None and proc.poll() is None:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except (OSError, ProcessLookupError):
                proc.terminate()
        return snapshot(job)


def delete_session(run_id: str) -> None:
    with MUTEX:
        job = RUNS.get(run_id)
        if job is None:
            raise KeyError(run_id)
        if job["status"] in ("running", "starting"):
            raise RuntimeError("Идущую симуляцию сначала останови")
        folder = OUT / run_id
        if not RUN_ID_RE.fullmatch(run_id) or not folder.is_dir():
            raise ValueError("Некорректная сессия")
        trash = OUT / ".trash"
        trash.mkdir(exist_ok=True)
        destination = trash / run_id
        if destination.exists():
            raise RuntimeError("В корзине уже есть сессия с таким ID")
        os.replace(folder, destination)
        del RUNS[run_id]


def purge_trash() -> int:
    """Explicit irreversible purge of archived sessions, isolated from live RUNS.

    Active tournament folders are outside .trash; the same mutex serializes
    backup, restore and deletion, so no tournament needs to be interrupted.
    """
    with MUTEX:
        trash = OUT / ".trash"
        if not trash.is_dir():
            return 0
        deleted = 0
        for entry in trash.iterdir():
            if entry.is_dir() and not entry.is_symlink() and RUN_ID_RE.fullmatch(entry.name):
                if (entry / "job.json").is_file():
                    shutil.rmtree(entry)
                    deleted += 1
        return deleted


def restore_deleted(run_id: str) -> dict:
    if not RUN_ID_RE.fullmatch(run_id):
        raise ValueError("Некорректный ID")
    with MUTEX:
        directory = OUT / ".trash" / run_id
        if not (directory / "job.json").is_file() or (OUT / run_id).exists():
            raise KeyError(run_id)
        os.replace(directory, OUT / run_id)
        manifest = json.loads((OUT / run_id / "job.json").read_text(encoding="utf-8"))
        manifest["log"] = deque(["Сессия восстановлена из корзины"], maxlen=MAX_LOG_LINES)
        RUNS[run_id] = manifest
        return snapshot(manifest)


def import_session(raw: bytes | str | Path) -> dict:
    """Safely import one exported session ZIP. File contents are never executed."""
    if isinstance(raw, (str, Path)):
        source = Path(raw)
        if source.stat().st_size > MAX_ZIP_BODY:
            raise ValueError("Архив слишком большой")
    else:
        if len(raw) > MAX_ZIP_BODY:
            raise ValueError("Архив слишком большой")
        source = io.BytesIO(raw)
    try:
        archive = zipfile.ZipFile(source)
    except (OSError, zipfile.BadZipFile):
        raise ValueError("Некорректный ZIP") from None
    with archive:
        entries = archive.infolist()
        if len(entries) > MAX_ARCHIVE_FILES:
            raise ValueError("В архиве слишком много файлов")
        if sum(entry.file_size for entry in entries) > MAX_ZIP_UNPACKED:
            raise ValueError("Превышен допустимый размер данных")
        for entry in entries:
            name = entry.filename
            if (not (ARCHIVE_NAME_RE.fullmatch(name) or CHECKPOINT_RE.fullmatch(name)) or
                    not (name.endswith((".csv", ".json", ".log", ".json.gz"))) or
                    entry.is_dir() or (entry.external_attr >> 16 & 0o170000) == 0o120000):
                raise ValueError("В архиве есть недопустимый файл")
        if "tournament_report.json" not in archive.namelist() and "session_manifest.json" not in archive.namelist():
            raise ValueError("Нет отчёта или манифеста частичной сессии")
        try:
            report = (json.loads(archive.read("tournament_report.json"))
                      if "tournament_report.json" in archive.namelist() else None)
            if report is not None and (not isinstance(report, dict) or not isinstance(report.get("leaderboard"), list)):
                raise ValueError("Неизвестный формат отчёта")
            manifest = (json.loads(archive.read("session_manifest.json"))
                        if "session_manifest.json" in archive.namelist() else {})
        except (ValueError, json.JSONDecodeError, KeyError):
            raise ValueError("Повреждённые метаданные") from None
        if not isinstance(manifest, dict):
            raise ValueError("Неправильный manifest")
        with MUTEX:
            if any(j["status"] in ("running", "starting") for j in RUNS.values()):
                raise RuntimeError("Импорт после завершения текущего запуска")
            run_id = "import_" + secrets.token_hex(8)
            folder = OUT / run_id
            folder.mkdir(parents=True)
            try:
                for entry in entries:
                    if entry.filename in ("job.json", "session_manifest.json"):
                        continue
                    dest = folder / entry.filename
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with archive.open(entry) as incoming, dest.open("wb") as outgoing:
                        shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
                integrity = folder / "integrity.json"
                if integrity.is_file():
                    check = json.loads(integrity.read_text(encoding="utf-8"))
                    hashes = check.get("files", {})
                    if not isinstance(hashes, dict):
                        raise ValueError("Неверный SHA-256 манифест")
                    for name, sha in hashes.items():
                        if (not isinstance(name, str) or
                                not (ARCHIVE_NAME_RE.fullmatch(name) or CHECKPOINT_RE.fullmatch(name))):
                            raise ValueError("Неподдерживаемый путь в SHA-256 манифесте")
                        file = folder / name
                        if not file.is_file() or sha256_file(file) != sha:
                            raise ValueError("Контрольная сумма ZIP не совпадает: " + name)
                config = manifest.get("config") or {}
                if not isinstance(config, dict):
                    config = {}
                job = {
                    "id": run_id, "status": "imported" if report else "interrupted",
                    "created": now(), "updated": now(),
                    "config": config, "returncode": 0 if report else None, "report": report,
                    "progress": {"done": (report or {}).get("tournaments_completed", 0),
                                 "total": (report or {}).get("tournaments_requested", config.get("tournaments", 0))},
                    "strategy_fingerprint": manifest.get("strategy_fingerprint"),
                    "stats": stats_for_folder(folder),
                    "performance": (json.loads((folder / "performance.json").read_text(encoding="utf-8"))
                                    if (folder / "performance.json").is_file() else None),
                    "log": deque((folder / "simulation.log").read_text(encoding="utf-8", errors="replace").splitlines()[-MAX_LOG_LINES:]
                                  if (folder / "simulation.log").is_file() else ["Сессия загружена из ZIP"],
                                  maxlen=MAX_LOG_LINES),
                }
                persist(job)
                RUNS[run_id] = job
                return snapshot(job)
            except Exception:
                shutil.rmtree(folder, ignore_errors=True)
                raise



def write_full_backup(stream) -> dict:
    """Full export of session folders and trash; download it to independent storage."""
    if any(j["status"] in ("running", "starting") for j in RUNS.values()):
        raise RuntimeError("Дождись завершения активной серии перед резервным копированием")
    details = {"format": "SKACHKOV_FULL_BACKUP_V1", "created": now(),
               "strategy_fingerprint": strategy_fingerprint(),
               "runs": [], "trash": []}
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=3) as archive:
        for prefix, root in (("runs", OUT), ("trash", OUT / ".trash")):
            if not root.exists():
                continue
            for directory in sorted(root.iterdir()):
                if not directory.is_dir() or not RUN_ID_RE.fullmatch(directory.name):
                    continue
                if not (directory / "job.json").is_file():
                    continue
                details[prefix].append(directory.name)
                for item in sorted(directory.rglob("*")):
                    if item.is_file() and not item.is_symlink():
                        arcname = f"{prefix}/{directory.name}/{item.relative_to(directory).as_posix()}"
                        archive.write(item, arcname=arcname)
        for name in ("a17_v5.json", "available_bases.json"):
            catalog = ROOT / "strategy_catalog" / name
            if catalog.is_file():
                archive.write(catalog, arcname="reference/" + name)
        # Strategy revisions are stored separately from experiment sessions.
        import planner_core
        revisions = []
        if planner_core.STORE.is_dir():
            for directory in sorted(planner_core.STORE.iterdir()):
                if directory.is_dir() and not directory.is_symlink() and planner_core.ID.fullmatch(directory.name):
                    for file in sorted(directory.glob("v[0-9][0-9][0-9][0-9][0-9].json")):
                        revisions.append(json.loads(file.read_text(encoding="utf-8")))
        details["strategy_revisions"] = len(revisions)
        archive.writestr("reference/saved_strategies.json",
                         json.dumps(revisions, ensure_ascii=False, separators=(",", ":")))
        archive.writestr("backup_manifest.json", json.dumps(details, ensure_ascii=False, indent=2))
    return details


def import_full_backup(source: str | Path) -> dict:
    """Restore archive folders safely without overwriting existing experiments."""
    if any(j["status"] in ("running", "starting") for j in RUNS.values()):
        raise RuntimeError("Дождись завершения серии для восстановления")
    if Path(source).stat().st_size > MAX_ZIP_BODY:
        raise ValueError("Резервная копия превышает лимит импорта")
    temp_dir = OUT / (".restore_" + secrets.token_hex(8))
    temp_dir.mkdir(parents=True, exist_ok=False)
    committed = []
    try:
        with zipfile.ZipFile(source) as archive:
            entries = archive.infolist()
            if len(entries) > MAX_ARCHIVE_FILES:
                raise ValueError("Слишком много файлов в резервной копии")
            if sum(e.file_size for e in entries) > MAX_ZIP_UNPACKED:
                raise ValueError("Распакованная копия превышает лимит")
            if "backup_manifest.json" not in archive.namelist():
                raise ValueError("Отсутствует backup_manifest.json")
            manifest = json.loads(archive.read("backup_manifest.json"))
            if manifest.get("format") != "SKACHKOV_FULL_BACKUP_V1":
                raise ValueError("Неподдерживаемый формат резервной копии")
            import planner_core
            plans = (json.loads(archive.read("reference/saved_strategies.json"))
                     if "reference/saved_strategies.json" in archive.namelist() else [])
            if not isinstance(plans, list) or len(plans) > 10000:
                raise ValueError("Некорректные версии стратегий в архиве")
            plan_dirs = {}
            seen_plan_versions = set()
            for record in plans:
                if not isinstance(record, dict):
                    raise ValueError("Повреждённая стратегия в архиве")
                old_id = record.get("id")
                version = record.get("version")
                if (not isinstance(old_id, str) or not planner_core.ID.fullmatch(old_id)
                        or type(version) is not int or not 1 <= version <= 99999):
                    raise ValueError("Неверный ID или версия стратегии в архиве")
                key = (old_id, version)
                if key in seen_plan_versions:
                    raise ValueError("Повторная версия стратегии в архиве")
                seen_plan_versions.add(key)
                validated = planner_core.validate_plan(record)
                new_id = plan_dirs.setdefault(old_id, secrets.token_hex(6))
                source = {**validated, "id": new_id, "version": version,
                          "ref": f"saved:{new_id}@v{version}",
                          "created": record.get("created"), "updated": record.get("updated"),
                          "source": "user"}
                stage = temp_dir / "plans" / new_id
                stage.mkdir(parents=True, exist_ok=True)
                (stage / f"v{version:05d}.json").write_text(
                    json.dumps(source, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            destinations = {}
            used_paths = set()
            for entry in entries:
                name = entry.filename
                if name == "backup_manifest.json" or name.startswith("reference/"):
                    continue
                segments = name.split("/")
                if (len(segments) not in (3, 4)
                        or segments[0] not in ("runs", "trash")
                        or not RUN_ID_RE.fullmatch(segments[1])
                        or (len(segments) == 4 and (segments[2] != "_checkpoints"
                            or not CHECKPOINT_RE.fullmatch("/".join(segments[2:]))))
                        or (len(segments) == 3 and not ARCHIVE_NAME_RE.fullmatch(segments[2]))
                        or entry.is_dir() or (entry.external_attr >> 16 & 0o170000) == 0o120000):
                    raise ValueError("Недопустимый путь в полной резервной копии")
                if not name.endswith((".json", ".csv", ".log", ".json.gz")):
                    raise ValueError("Недопустимый тип файла в копии")
                if name in used_paths:
                    raise ValueError("Дублирование файла в копии")
                used_paths.add(name)
                key = (segments[0], segments[1])
                if key not in destinations:
                    new_id = "restore_" + secrets.token_hex(8)
                    destinations[key] = new_id
                dest = temp_dir / segments[0] / destinations[key] / "/".join(segments[2:])
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as incoming, dest.open("wb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing, length=1024 * 1024)
            if not destinations and not plan_dirs:
                raise ValueError("В резервной копии нет сессий или стратегий")
            # Validate every job before promoting any restored directory.
            for (kind, _old), id_ in destinations.items():
                stage = temp_dir / kind / id_
                manifest_file = stage / "job.json"
                if not manifest_file.is_file():
                    raise ValueError("В резервной копии отсутствует job.json")
                job = json.loads(manifest_file.read_text(encoding="utf-8"))
                if not isinstance(job, dict) or not isinstance(job.get("config"), dict):
                    raise ValueError("Повреждён манифест сессии")
                job["id"] = id_
                if job.get("status") in ("running", "starting"):
                    job["status"] = "interrupted"
                manifest_file.write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
                checksum = stage / "integrity.json"
                if checksum.is_file():
                    hashes = json.loads(checksum.read_text(encoding="utf-8")).get("files", {})
                    if not isinstance(hashes, dict):
                        raise ValueError("Некорректный SHA-манифест в копии")
                    for path, sha in hashes.items():
                        if (not isinstance(path, str) or
                                not (ARCHIVE_NAME_RE.fullmatch(path) or CHECKPOINT_RE.fullmatch(path))):
                            raise ValueError("Некорректный путь в SHA-манифесте")
                        target = stage / path
                        if not target.is_file() or sha256_file(target) != sha:
                            raise ValueError("Повреждён файл полной копии: " + path)
            with MUTEX:
                for (kind, _old), id_ in destinations.items():
                    final = (OUT if kind == "runs" else OUT / ".trash") / id_
                    final.parent.mkdir(parents=True, exist_ok=True)
                    if final.exists():
                        raise RuntimeError("Конфликт нового ID при восстановлении")
                    os.replace(temp_dir / kind / id_, final)
                    committed.append(id_)
                    if kind == "runs":
                        job = json.loads((final / "job.json").read_text(encoding="utf-8"))
                        logfile = final / "simulation.log"
                        job["log"] = deque(logfile.read_text(encoding="utf-8", errors="replace").splitlines()[-MAX_LOG_LINES:]
                                           if logfile.is_file() else [], maxlen=MAX_LOG_LINES)
                        RUNS[id_] = job
                for new_id in plan_dirs.values():
                    final = planner_core.STORE / new_id
                    final.parent.mkdir(parents=True, exist_ok=True)
                    if final.exists():
                        raise RuntimeError("Конфликт ID стратегии при восстановлении")
                    os.replace(temp_dir / "plans" / new_id, final)
        return {"restored_count": len(committed), "ids": committed,
                "strategy_revisions_restored": len(plans), "strategies_restored": len(plan_dirs)}
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)


def zip_results(job: dict, stream=None) -> bytes | None:
    # Generate ZIP on demand. Avoid archives as part of Git history.
    folder = OUT / job["id"]
    data = stream if stream is not None else io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(folder.rglob("*")):
            if path.is_file() and not path.is_symlink() and path.name not in ("job.json", "session_manifest.json"):
                archive.write(path, arcname=str(path.relative_to(folder)))
        archive.writestr("session_manifest.json", json.dumps(
            {"format": "SKACHKOV_SESSION_V2", "config": job.get("config", {}),
             "created": job.get("created"), "source_id": job["id"],
             "status": job.get("status"), "strategy_fingerprint": job.get("strategy_fingerprint")},
            ensure_ascii=False, indent=2))
    return data.getvalue() if stream is None else None


class Handler(BaseHTTPRequestHandler):
    server_version = "SKACHKOV-Simulator/2.1"

    def reply(self, code: int, data: dict):
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(body)

    def allowed(self) -> bool:
        if not TOKEN:
            self.reply(503, {"error": "Укажи POKER_RUNNER_KEY в Railway Variables и перезапусти"})
            return False
        supplied = self.headers.get("X-Runner-Key", "")
        if not secrets.compare_digest(supplied, TOKEN):
            self.reply(401, {"error": "Неверный ключ доступа"})
            return False
        return True

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/", "/plan", "/s100", "/analysis"):
            html = ((ROOT / "replit_ui" / "river_board.html") if path == "/s100"
                    else ANALYSIS_UI if path == "/analysis"
                    else PLAN_UI if path == "/plan" else UI).read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy",
                             "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'")
            self.end_headers()
            self.wfile.write(html)
            return
        if path == "/health":
            self.reply(200 if TOKEN else 503, {"ok": bool(TOKEN), "engine": "legacy", "configured": bool(TOKEN)})
            return
        if not self.allowed():
            return
        if planner_api.get_route(self,path):
            return
        if path == "/api/postflop/board150-catalog":
            catalog = ROOT / "data" / "postflop_board150_catalog.json"
            try:
                self.reply(200, json.loads(catalog.read_text(encoding="utf-8")))
            except (OSError,ValueError):
                self.reply(503, {"error": "Каталог P/S/F/SF/A недоступен"})
            return
        if path == "/api/postflop/composite-catalog":
            # Small reviewed static JSON; generated offline from the exact census.
            catalog = ROOT / "data" / "postflop_composite_catalog.json"
            try:
                self.reply(200, json.loads(catalog.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                self.reply(503, {"error": "Каталог составных сценариев пока недоступен"})
            return
        if path == "/api/s100":
            from bots.s100_postflop import CATALOG
            self.reply(200, CATALOG)
            return
        if path == "/api/catalog":
            self.reply(200, strategy_catalog())
            return
        if path == "/api/backup":
            with MUTEX:
                if any(j["status"] in ("running", "starting") for j in RUNS.values()):
                    self.reply(409, {"error": "Сначала заверши текущий запуск"})
                    return
            with tempfile.TemporaryFile() as archive:
                write_full_backup(archive)
                size = archive.tell()
                archive.seek(0)
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", 'attachment; filename="SKACHKOV_ALL_SESSIONS.zip"')
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                shutil.copyfileobj(archive, self.wfile, length=1024 * 1024)
            return
        if path == "/api/trash":
            trash = OUT / ".trash"
            ids = sorted([p.name for p in trash.iterdir() if (p / "job.json").is_file()], reverse=True) if trash.exists() else []
            self.reply(200, {"deleted": ids})
            return
        if path == "/api/storage":
            disk = shutil.disk_usage(OUT)
            self.reply(200, {"volume": {"total_bytes": disk.total,
                                        "used_bytes": disk.used, "free_bytes": disk.free},
                              "compaction": storage_compaction_preview(),
                              "breakdown": storage_directory_breakdown()})
            return
        if path == "/api/integrity":
            with MUTEX:
                ids = sorted(RUNS)
            with MUTEX:
                inspections = [audit_session(RUNS[run_id]) for run_id in ids if run_id in RUNS]
            disk = shutil.disk_usage(OUT)
            self.reply(200, {"session_count": len(inspections),
                             "healthy_sessions": sum(x["ok"] for x in inspections),
                             "issues": [x for x in inspections if not x["ok"]],
                             "sessions": inspections,
                             "volume": {"path": str(OUT), "total_bytes": disk.total,
                                        "used_bytes": disk.used, "free_bytes": disk.free},
                             "strategy_fingerprint": strategy_fingerprint()})
            return
        if path == "/api/runs":
            with MUTEX:
                jobs = sorted(RUNS.values(), key=lambda x: x["created"], reverse=True)
                data = [{
                    "id": j["id"], "status": j["status"],
                    "created": j["created"], "updated": j["updated"]
                } for j in jobs]
            self.reply(200, {"runs": data})
            return
        match = re.fullmatch(r"/api/runs/([A-Za-z0-9_]+)/download", path)
        if match:
            run_id = match.group(1)
            with MUTEX:
                job = RUNS.get(run_id)
                if not job:
                    self.reply(404, {"error": "Серия не найдена"})
                    return
                if job["status"] in {"running", "starting"}:
                    self.reply(409, {"error": "Дождитесь завершения серии"})
                    return
            with tempfile.TemporaryFile() as data:
                zip_results(job, stream=data)
                size = data.tell()
                data.seek(0)
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="SKACHKOV_{run_id}.zip"')
                self.send_header("Content-Length", str(size))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                shutil.copyfileobj(data, self.wfile, length=1024 * 1024)
            return
        match = re.fullmatch(r"/api/runs/([A-Za-z0-9_]+)", path)
        if match:
            with MUTEX:
                job = RUNS.get(match.group(1))
                data = snapshot(job) if job else None
            self.reply(200 if data else 404, data or {"error": "Серия не найдена"})
            return
        self.reply(404, {"error": "Не найдено"})

    def do_DELETE(self):
        path = urlparse(self.path).path
        if not self.allowed():
            return
        if planner_api.delete_route(self,path):
            return
        if path == "/api/trash":
            try:
                self.reply(200, {"purged": purge_trash()})
            except RuntimeError as exc:
                self.reply(409, {"error": str(exc)})
            return
        match = re.fullmatch(r"/api/runs/([A-Za-z0-9_]+)", path)
        if not match:
            self.reply(404, {"error": "Не найдено"})
            return
        try:
            delete_session(match.group(1))
            self.reply(200, {"ok": True})
        except KeyError:
            self.reply(404, {"error": "Сессия не найдена"})
        except (ValueError, RuntimeError) as exc:
            self.reply(409, {"error": str(exc)})

    def do_POST(self):
        path = urlparse(self.path).path
        if not self.allowed():
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            limit = (MAX_ZIP_BODY if path in ("/api/runs/import", "/api/backup/restore")
                     else MAX_PLAN_BODY if path == "/api/plan/strategies" else MAX_BODY)
            if size <= 0 or size > limit:
                self.reply(413, {"error": "Слишком большой запрос"})
                return
            if path in ("/api/runs/import", "/api/backup/restore"):
                with tempfile.NamedTemporaryFile(prefix="poker_upload_", suffix=".zip") as upload:
                    remaining = size
                    while remaining:
                        chunk = self.rfile.read(min(1024 * 1024, remaining))
                        if not chunk:
                            raise ValueError("Неполный ZIP")
                        upload.write(chunk)
                        remaining -= len(chunk)
                    upload.flush()
                    try:
                        self.reply(201, import_session(upload.name) if path == "/api/runs/import"
                                   else import_full_backup(upload.name))
                    except ValueError as exc:
                        self.reply(400, {"error": str(exc)})
                    except RuntimeError as exc:
                        self.reply(409, {"error": str(exc)})
                return
            payload = json.loads(self.rfile.read(size))
        except (ValueError, json.JSONDecodeError):
            self.reply(400, {"error": "Некорректный JSON"})
            return
        if path == "/api/postflop/compare":
            from postflop_strategy_compare import compare_request
            try:
                self.reply(200, compare_request(payload))
            except ValueError as e:
                self.reply(400, {"error": str(e)})
            return
        if path == "/api/postflop/board150-classify":
            from postflop_board150 import classify_request
            try:
                self.reply(200, classify_request(payload))
            except (ValueError,TypeError) as exc:
                self.reply(400, {"error": str(exc)})
            return
        if path == "/api/postflop/composite":
            from postflop_composite_classifier import classify_composite_request
            try:
                self.reply(200, classify_composite_request(payload))
            except ValueError as e:
                self.reply(400, {"error": str(e)})
            return
        if path == "/api/postflop/board-texture":
            from flop_board_structure import classify_flop_request
            try:
                self.reply(200, classify_flop_request(payload))
            except ValueError as e:
                self.reply(400, {"error": str(e)})
            return
        if path == "/api/postflop/classify":
            from postflop_numeric_classifier import classify_request
            try:
                self.reply(200, classify_request(payload))
            except ValueError as e:
                self.reply(400, {"error": str(e)})
            return
        if path == "/api/s100/inspect":
            from bots.s100_postflop import inspect_request
            try:
                self.reply(200, inspect_request(payload))
            except ValueError as e:
                self.reply(400, {"error": str(e)})
            return
        if path.startswith("/api/plan/"):
            with MUTEX:
                busy = any(j["status"] in ("running","starting") for j in RUNS.values())
            if planner_api.post_route(self,path,payload,busy=busy):
                return
        if path == "/api/storage/compact":
            if payload.get("confirm") is not True:
                self.reply(400, {"error": "Требуется подтверждение очистки завершённых сессий"})
                return
            try:
                self.reply(200, compact_historical_sessions())
            except RuntimeError as exc:
                self.reply(409, {"error": str(exc)})
            return
        if path == "/api/runs":
            try:
                config = validate_config(payload)
                self.reply(202, start_run(config))
            except ValueError as e:
                self.reply(400, {"error": str(e)})
            except RuntimeError as e:
                self.reply(409, {"error": str(e)})
            return
        match = re.fullmatch(r"/api/trash/([A-Za-z0-9_]+)/restore", path)
        if match:
            try:
                self.reply(200, restore_deleted(match.group(1)))
            except KeyError:
                self.reply(404, {"error": "Не найдено в корзине"})
            except (ValueError, RuntimeError) as e:
                self.reply(409, {"error": str(e)})
            return
        match = re.fullmatch(r"/api/runs/([A-Za-z0-9_]+)/resume", path)
        if match:
            try:
                self.reply(202, resume_run(match.group(1)))
            except KeyError:
                self.reply(404, {"error": "Сессия не найдена"})
            except (ValueError, RuntimeError) as e:
                self.reply(409, {"error": str(e)})
            return
        match = re.fullmatch(r"/api/runs/([A-Za-z0-9_]+)/cancel", path)
        if match:
            try:
                self.reply(200, cancel_run(match.group(1)))
            except KeyError:
                self.reply(404, {"error": "Серия не найдена"})
            return
        self.reply(404, {"error": "Не найдено"})


def restore_history():
    OUT.mkdir(parents=True, exist_ok=True)
    for manifest in sorted(OUT.glob("*/job.json"), reverse=True):
        try:
            job = json.loads(manifest.read_text(encoding="utf-8"))
            if job["id"] != manifest.parent.name or not RUN_ID_RE.fullmatch(job["id"]):
                continue
            log_file = manifest.parent / "simulation.log"
            tail = deque(maxlen=MAX_LOG_LINES)
            if log_file.is_file():
                with log_file.open(encoding="utf-8", errors="replace") as log:
                    tail.extend(line.rstrip() for line in log)
            job["log"] = tail
            job["status"] = "interrupted" if job["status"] in ("starting", "running") else job["status"]
            checkpoint_dir = manifest.parent / "_checkpoints"
            if checkpoint_dir.is_dir() and job.get("progress"):
                saved = len(list(checkpoint_dir.glob("*.json.gz")))
                job["progress"]["done"] = max(job["progress"].get("done", 0), saved)
            if job.get("report"):
                # Refresh derived analysis views after an application upgrade.
                # Raw CSV files are authoritative; historic job.json stats may
                # predate newly available position / table-size metrics.
                updated_stats = stats_for_folder(manifest.parent)
                if updated_stats:
                    job["stats"] = updated_stats
            perf = manifest.parent / "performance.json"
            if perf.is_file() and not job.get("performance"):
                job["performance"] = json.loads(perf.read_text(encoding="utf-8"))
            RUNS[job["id"]] = job
        except (KeyError, OSError, ValueError):
            pass


if __name__ == "__main__":
    restore_history()
    try:
        cache_report = planner_api.enforce_cache_limit()
        print("[cache-retention] startup " + json.dumps(cache_report), flush=True)
    except OSError as exc:
        print("[cache-retention] startup failed: " + str(exc), flush=True)
    try:
        print("[storage-diagnostics] " + json.dumps(storage_directory_breakdown(), ensure_ascii=False), flush=True)
    except OSError as exc:
        print("[storage-diagnostics] unavailable: " + str(exc), flush=True)
    print(f"SKACHKOV simulator listening on 0.0.0.0:{PORT}; key configured: {bool(TOKEN)}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
