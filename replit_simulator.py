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

ROOT = Path(__file__).resolve().parent
UI = ROOT / "replit_ui" / "index.html"
OUT = Path(os.environ.get("POKER_DATA_DIR", str(ROOT / "output" / "replit_runs"))).resolve()
PORT = int(os.environ.get("PORT", "3000"))
TOKEN = os.environ.get("POKER_RUNNER_KEY", "").strip()
MAX_BODY = 32_768
MAX_ZIP_BODY = 32 * 1024 * 1024
MAX_ZIP_UNPACKED = 120 * 1024 * 1024
MAX_LOG_LINES = 200
MAX_ZIP_BODY = 256 * 1024 * 1024
MAX_ZIP_UNPACKED = 400 * 1024 * 1024
MAX_ARCHIVE_FILES = 5000
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
    "smart", "gto", "gto_fixed", "a17_preflop", "a17_preflop_legacy", "a17_tag", "a17_tag_legacy",
    "tag_punisher", "baseline_sane", "pressure_filler",
    "wide_defender", "nit", "loose_passive", "maniac",
    "maniac_mixed", "random", "random_2", "random_3",
}
SPLIT_PARTS = frozenset(json.loads(
    (ROOT / "strategy_catalog" / "available_bases.json").read_text(encoding="utf-8")
)["bases"])

# Each of the nine player seats has a separately editable preflop/postflop policy.
# Blank means INCOMPLETE, never automatic inheritance.
DEFAULT_BOT_ROWS = [
    {"pre": "gto", "post": "smart"},
    {"pre": "gto", "post": "gto"},
    {"pre": "gto", "post": "tag_punisher"},
    {"pre": "gto", "post": "maniac_mixed"},
    {"pre": "gto", "post": "baseline_sane"},
    {"pre": "a17_preflop", "post": "tag_punisher"},
    {"pre": "gto", "post": "random"},
    {"pre": "gto", "post": "random_2"},
    {"pre": "gto", "post": "pressure_filler"},
]
PROGRESS_RE = re.compile(
    r"(\d+)/(\d+) tournaments\s*·\s*([\d.]+) tournaments/min\s*·\s*([\d.]+) hands/s"
)
RUN_ID_RE = re.compile(r"^[A-Za-z0-9_]{5,64}$")
ARCHIVE_NAME_RE = re.compile(r"^[A-Za-z0-9_.-]{1,120}$")
CHECKPOINT_RE = re.compile(r"^_checkpoints/(?:config\.json|[0-9]{6}\.json\.gz)$")

def strategy_fingerprint():
    # Binds experiment to implementation, including future policy modules.
    paths = sorted((ROOT / "bots").glob("*.py")) + sorted((ROOT / "core").glob("*.py"))
    paths += [ROOT / "export_preflop_ranges_v4.py",
              ROOT / "run_tournament_stats.py", ROOT / "strategy_catalog" / "a17_v5.json"]
    digest = hashlib.sha256()
    for path in paths:
        if path.is_file():
            digest.update(str(path.relative_to(ROOT)).encode())
            digest.update(hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()

def strategy_catalog():
    options = sorted(SPLIT_PARTS)
    return {"strategies": options, "a17_version": "A17_V5",
            "code_fingerprint": strategy_fingerprint(), "workers_max": 1 if os.environ.get("RAILWAY_PROJECT_ID") else 4,
            "required_streets": ["pre", "post"]}




def valid_bot(bot: str) -> bool:
    if bot in BASE_BOTS:
        return True
    parts = bot.split(":")
    return len(parts) == 3 and parts[0] == "split" and all(
        p in SPLIT_PARTS for p in parts[1:]
    )


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
        for i, row in enumerate(raw_rows, start=1):
            if not isinstance(row, dict):
                raise ValueError(f"P{i}: выбери обе стратегии")
            pre, post = row.get("pre", ""), row.get("post", "")
            if not isinstance(pre, str) or not isinstance(post, str):
                raise ValueError(f"P{i}: некорректная стратегия")
            if not pre or not post:
                raise ValueError(f"P{i}: Preflop и Postflop обязательны; пустое поле запрещает запуск")
            if pre not in SPLIT_PARTS or post not in SPLIT_PARTS:
                raise ValueError(f"P{i}: неподдерживаемая стратегия {pre}/{post}")
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
    config = {
        "players": bots, "bots": rows,
        "tournaments": bounded_int(data.get("tournaments", 90), "Турниры", 1, 3000),
        "parallel": bounded_int(data.get("parallel", 1), "Потоки", 1, 4),
        "seed": bounded_int(data.get("seed", 2042), "Seed", 0, 2_147_483_647),
        "chips": bounded_int(data.get("chips", 500), "Стек", 10, 1_000_000),
        "sb": sb, "bb": bb,
        "blind_increase_every": bounded_int(
            data.get("blind_increase_every", 50), "Рост блайндов", 0, 10000
        ),
        "max_hands": bounded_int(data.get("max_hands", 10000), "Лимит рук", 100, 100_000),
        "seat_mode": seat_mode,
    }
    if os.environ.get("RAILWAY_PROJECT_ID") and config["parallel"] > 1:
        raise ValueError("Railway с текущими ресурсами: максимум 1 процесс. Ранее параллельный запуск приводил к BrokenProcessPool.")
    return config


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def snapshot(job: dict) -> dict:
    return {
        "id": job["id"], "status": job["status"], "created": job["created"],
        "updated": job["updated"], "config": job["config"],
        "log": list(job["log"]), "returncode": job["returncode"],
        "report": job.get("report"),
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
    """Actual observed preflop metrics and placement data; never infer bb/100."""
    observed = {}
    for row in _read_rows(folder / "summary_all.csv"):
        profile = row.get("bot", "")
        if not profile:
            continue
        observed[profile] = {
            metric: (float(row[metric + "_pct"]) if row.get(metric + "_pct", "") not in ("", None) else None)
            for metric in ("vpip", "pfr", "rfi", "threebet", "fourbet")
        }
        observed[profile]["hands_observed"] = int(row.get("hands_observed") or 0)
    placement = {}
    for row in _read_rows(folder / "tournament_players.csv"):
        if row.get("completed") != "1":
            continue
        name = row.get("bot", "")
        entry = placement.setdefault(name, {"places": [], "top3": 0})
        try:
            place = int(row.get("position") or 0)
        except ValueError:
            continue
        if place < 1:
            continue
        entry["places"].append(place)
        entry["top3"] += int(place <= 3)
    for name, data in placement.items():
        result = observed.setdefault(name, {})
        positions = data["places"]
        result["top3_pct"] = round(data["top3"] / len(positions) * 100, 2) if positions else None
        result["median_position"] = statistics.median(positions) if positions else None
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
        "--out", str(output),
        "--checkpoint-dir", str(output / "_checkpoints"),
    ]
    log_path = output / "simulation.log"
    try:
        env = dict(os.environ, THAI_ENGINE_IMPL="legacy", PYTHONUNBUFFERED="1")
        with log_path.open("a", encoding="utf-8") as log:
            log.write("\n[runner] Start or resume at " + now() + "\n")
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
            job["updated"] = now()
            job.pop("process", None)
            persist(job)
    except Exception as exc:
        with MUTEX:
            job["log"].append("Сбой запуска: " + repr(exc))
            job["status"] = "failed"
            job["updated"] = now()
            job.pop("process", None)
            persist(job)


def start_run(config: dict) -> dict:
    with MUTEX:
        if any(j["status"] in {"running", "starting"} for j in RUNS.values()):
            raise RuntimeError("Уже запущена серия турниров; дождитесь завершения или остановите её")
        OUT.mkdir(parents=True, exist_ok=True)
        free = shutil.disk_usage(OUT).free
        if free < 40 * 1024 * 1024:
            raise RuntimeError("На томе с результатами меньше 40 МБ свободного места; скачай резервные ZIP и освободи место")
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(3)
        job = {
            "id": run_id, "status": "starting", "created": now(), "updated": now(),
            "config": config, "returncode": None, "report": None,
            "progress": {"done": 0, "total": config["tournaments"], "tpm": None, "hps": None},
            "stats": {}, "performance": None, "strategy_fingerprint": strategy_fingerprint(),
            "log": deque(maxlen=MAX_LOG_LINES),
        }
        RUNS[run_id] = job
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / run_id).mkdir(parents=True, exist_ok=True)
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
        if not job.get("strategy_fingerprint") or job["strategy_fingerprint"] != strategy_fingerprint():
            raise RuntimeError("Версия старой сессии неизвестна или изменилась; безопасное продолжение невозможно. Скачай ZIP для архива.")
        job["cancelled"] = False
        job["status"] = "running"
        job["returncode"] = None
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
    server_version = "SKACHKOV-Simulator/2.0"

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
        if path == "/":
            html = UI.read_bytes()
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
        if path == "/api/catalog":
            self.reply(200, strategy_catalog())
            return
        if path == "/api/trash":
            trash = OUT / ".trash"
            ids = sorted([p.name for p in trash.iterdir() if (p / "job.json").is_file()], reverse=True) if trash.exists() else []
            self.reply(200, {"deleted": ids})
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
            limit = MAX_ZIP_BODY if path == "/api/runs/import" else MAX_BODY
            if size <= 0 or size > limit:
                self.reply(413, {"error": "Слишком большой запрос"})
                return
            if path == "/api/runs/import":
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
                        self.reply(201, import_session(upload.name))
                    except ValueError as exc:
                        self.reply(400, {"error": str(exc)})
                    except RuntimeError as exc:
                        self.reply(409, {"error": str(exc)})
                return
            payload = json.loads(self.rfile.read(size))
        except (ValueError, json.JSONDecodeError):
            self.reply(400, {"error": "Некорректный JSON"})
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
            if job.get("report") and not job.get("stats"):
                job["stats"] = stats_for_folder(manifest.parent)
            perf = manifest.parent / "performance.json"
            if perf.is_file() and not job.get("performance"):
                job["performance"] = json.loads(perf.read_text(encoding="utf-8"))
            RUNS[job["id"]] = job
        except (KeyError, OSError, ValueError):
            pass


if __name__ == "__main__":
    restore_history()
    print(f"SKACHKOV simulator listening on 0.0.0.0:{PORT}; key configured: {bool(TOKEN)}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
