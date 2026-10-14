"""Browser-operated Replit frontend for the existing v4 tournament simulator.

Stage 1 migration. The poker engine, bots, and exporter remain unchanged.
Python standard library only; uses legacy engine for experiment parity.
"""
from __future__ import annotations

import io
import json
import os
import re
import secrets
import signal
import subprocess
import sys
import threading
import time
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
MAX_BODY = 16_384
MAX_LOG_LINES = 80
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
    "smart", "gto", "gto_fixed", "a17_preflop", "a17_tag",
    "tag_punisher", "baseline_sane", "pressure_filler",
    "wide_defender", "nit", "loose_passive", "maniac",
    "maniac_mixed", "random", "random_2", "random_3",
}
SPLIT_PARTS = BASE_BOTS - {"a17_tag", "random_2", "random_3"}
SPLIT_PARTS.update({"random_2", "random_3"})
SPLIT_PARTS.discard("a17_tag")


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
    return {
        "players": bots,
        "tournaments": bounded_int(data.get("tournaments", 90), "Турниры", 1, 3000),
        "parallel": bounded_int(data.get("parallel", 2), "Потоки", 1, 4),
        "seed": bounded_int(data.get("seed", 2042), "Seed", 0, 2_147_483_647),
        "chips": bounded_int(data.get("chips", 500), "Стек", 10, 1_000_000),
        "sb": sb, "bb": bb,
        "blind_increase_every": bounded_int(
            data.get("blind_increase_every", 50), "Рост блайндов", 0, 10000
        ),
        "max_hands": bounded_int(data.get("max_hands", 10000), "Лимит рук", 100, 100_000),
        "seat_mode": seat_mode,
    }


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def snapshot(job: dict) -> dict:
    return {
        "id": job["id"], "status": job["status"], "created": job["created"],
        "updated": job["updated"], "config": job["config"],
        "log": list(job["log"]), "returncode": job["returncode"],
        "report": job.get("report"),
    }


def persist(job: dict) -> None:
    p = OUT / job["id"] / "job.json"
    data = snapshot(job)
    data.pop("log", None)
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


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
    ]
    log_path = output / "simulation.log"
    try:
        env = dict(os.environ, THAI_ENGINE_IMPL="legacy", PYTHONUNBUFFERED="1")
        with log_path.open("w", encoding="utf-8") as log:
            proc = subprocess.Popen(
                cmd, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, bufsize=1,
                start_new_session=True,
            )
            with MUTEX:
                job["process"] = proc
            assert proc.stdout is not None
            for line in proc.stdout:
                log.write(line)
                log.flush()
                with MUTEX:
                    job["log"].append(line.rstrip())
                    job["updated"] = now()
            exit_code = proc.wait()
        report_file = output / "tournament_report.json"
        report = json.loads(report_file.read_text(encoding="utf-8")) if report_file.exists() else None
        with MUTEX:
            job["returncode"] = exit_code
            job["report"] = report
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
        run_id = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S") + "_" + secrets.token_hex(3)
        job = {
            "id": run_id, "status": "starting", "created": now(), "updated": now(),
            "config": config, "returncode": None, "report": None,
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


def zip_results(job: dict) -> bytes:
    # Generate ZIP on demand. Avoid archives as part of Git history.
    folder = OUT / job["id"]
    data = io.BytesIO()
    with zipfile.ZipFile(data, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(folder.iterdir()):
            if path.is_file() and not path.is_symlink() and path.name != "job.json":
                archive.write(path, arcname=path.name)
    return data.getvalue()


class Handler(BaseHTTPRequestHandler):
    server_version = "SKACHKOV-Simulator/1.0"

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
        if path == "/api/runs":
            with MUTEX:
                jobs = sorted(RUNS.values(), key=lambda x: x["created"], reverse=True)
                data = [snapshot(j) for j in jobs[:40]]
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
            content = zip_results(job)
            self.send_response(200)
            self.send_header("Content-Type", "application/zip")
            self.send_header("Content-Disposition", f'attachment; filename="SKACHKOV_{run_id}.zip"')
            self.send_header("Content-Length", str(len(content)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(content)
            return
        match = re.fullmatch(r"/api/runs/([A-Za-z0-9_]+)", path)
        if match:
            with MUTEX:
                job = RUNS.get(match.group(1))
                data = snapshot(job) if job else None
            self.reply(200 if data else 404, data or {"error": "Серия не найдена"})
            return
        self.reply(404, {"error": "Не найдено"})

    def do_POST(self):
        path = urlparse(self.path).path
        if not self.allowed():
            return
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if size <= 0 or size > MAX_BODY:
                self.reply(413, {"error": "Слишком большой запрос"})
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
    for manifest in sorted(OUT.glob("*/job.json"), reverse=True)[:40]:
        try:
            job = json.loads(manifest.read_text(encoding="utf-8"))
            job["log"] = deque(maxlen=MAX_LOG_LINES)
            job["status"] = "interrupted" if job["status"] in ("starting", "running") else job["status"]
            RUNS[job["id"]] = job
        except (KeyError, OSError, ValueError):
            pass


if __name__ == "__main__":
    restore_history()
    print(f"SKACHKOV simulator listening on 0.0.0.0:{PORT}; key configured: {bool(TOKEN)}")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
