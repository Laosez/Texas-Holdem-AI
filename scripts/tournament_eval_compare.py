"""Compare identical tournament workloads under legacy vs fast hand evaluation.

Runs two separate processes to measure peak RSS independently. Any discrepancy
in a deterministic tournament telemetry CSV, tournament placements or equity
results exits non-zero, BLOCKING the production candidate.

Use THAI_ENGINE_IMPL=legacy because this exporter requires the legacy engine.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import resource
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
OUT = Path("/tmp/evaluator_tournament_audit")
PLAYERS = (
    "split:gto:smart,split:gto:gto,split:gto:tag_punisher,"
    "split:gto:maniac_mixed,split:gto:baseline_sane,"
    "split:a17_preflop:tag_punisher,split:gto:random,"
    "split:gto:random_2,split:gto:pressure_filler"
)
KEY_FILES = [
    "tournaments.csv", "tournament_players.csv", "leaderboard.csv",
    "blind_levels.csv", "blind_summary.csv", "postflop_summary.csv",
    "tournament_report.json",
]


def do_child(mode: str, tournaments: int):
    os.environ["THAI_HAND_EVALUATOR"] = mode
    os.environ["THAI_ENGINE_IMPL"] = "legacy"
    os.environ["PYTHONHASHSEED"] = "0"
    sys.path.insert(0, str(ROOT))
    from export_preflop_ranges_v4 import main
    destination = OUT / mode
    args = [
        "--players", PLAYERS, "--tournaments", str(tournaments),
        "--parallel", "1", "--seed", "2042", "--chips", "500",
        "--sb", "1", "--bb", "2", "--blind-increase-every", "50",
        "--max-hands", "10000", "--seat-mode", "rotate", "--out",
        str(destination),
    ]
    sys.argv = ["export_preflop_ranges_v4.py"] + args
    started = time.perf_counter()
    main()
    elapsed = time.perf_counter() - started
    report = json.loads((destination / "tournament_report.json").read_text("utf-8"))
    perf = json.loads((destination / "performance.json").read_text("utf-8"))
    if report["tournaments_completed"] != tournaments or report["wins_total"] != tournaments:
        raise AssertionError("Unfinished tournaments or missing winner")
    print("EVAL_TOURNAMENT_RESULT " + json.dumps({
        "mode": mode, "tournaments": tournaments,
        "completed": report["tournaments_completed"],
        "total_hands": report["total_hands"],
        "wall_seconds": round(elapsed, 3),
        "hands_per_second": round(report["total_hands"] / elapsed, 2),
        "simulation_wall_seconds": perf["simulation_wall_seconds"],
        "peak_rss_mib": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024, 2),
        "winners": {row["bot"]: row["wins"] for row in report["leaderboard"]},
    }, sort_keys=True), flush=True)


def run_child(mode, tournaments):
    env = dict(os.environ, THAI_ENGINE_IMPL="legacy", THAI_HAND_EVALUATOR=mode,
               PYTHONHASHSEED="0", PYTHONUNBUFFERED="1")
    cmd = [sys.executable, "-u", str(Path(__file__).resolve()), "--child-mode", mode,
           "--tournaments", str(tournaments)]
    proc = subprocess.Popen(cmd, cwd=ROOT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, bufsize=1)
    result = None
    for line in proc.stdout:
        s = line.rstrip()
        if s.startswith("EVAL_TOURNAMENT_RESULT "):
            result = json.loads(s.split(" ", 1)[1])
            print(s, flush=True)
        elif (" tournaments" in s and "/" in s) or s.startswith("Traceback") or s.startswith("Error"):
            print("TOURNAMENT_PROGRESS mode=%s %s" % (mode, s), flush=True)
    rc = proc.wait()
    if rc != 0 or result is None:
        raise RuntimeError("%s run failed with exit code %d" % (mode, rc))
    return result


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_identical():
    base = OUT / "legacy"
    candidate = OUT / "fast"
    all_csv = sorted(p.name for p in base.glob("*.csv")
                     if not p.name.startswith("bot_decision_timing"))
    names = sorted(set(all_csv + KEY_FILES))
    mismatched = []
    for name in names:
        old, new = base / name, candidate / name
        if not old.is_file() or not new.is_file() or digest(old) != digest(new):
            mismatched.append(name)
    print("TOURNAMENT_FILES_VERIFIED " + json.dumps({
        "total": len(names), "identical": len(names)-len(mismatched),
        "mismatched": mismatched
    }, sort_keys=True), flush=True)
    if mismatched:
        raise AssertionError("Different deterministic tournament results: " + ", ".join(mismatched))
    return len(names)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--tournaments", type=int, default=180)
    p.add_argument("--child-mode", choices=("fast", "legacy"))
    a = p.parse_args()
    if a.tournaments < 1:
        p.error("tournaments must be positive")
    if a.child_mode:
        do_child(a.child_mode, a.tournaments)
        return
    print("TOURNAMENT_EVALUATOR_AUDIT_BEGIN " + json.dumps({"tournaments_per_mode":a.tournaments,
          "players": PLAYERS, "seed": 2042, "chips_per_player":500}),flush=True)
    legacy = run_child("legacy", a.tournaments)
    fast = run_child("fast", a.tournaments)
    nfiles = verify_identical()
    if legacy["total_hands"] != fast["total_hands"] or legacy["winners"] != fast["winners"]:
        raise AssertionError("Tournament aggregate mismatch")
    print("TOURNAMENT_EVALUATOR_AUDIT_PASS " + json.dumps({
        "tournaments_each": a.tournaments, "total_tournaments": a.tournaments * 2,
        "same_tournament_reports": True, "compared_files": nfiles,
        "speedup": round(legacy["wall_seconds"] / fast["wall_seconds"], 3),
        "rss_saved_mib": round(legacy["peak_rss_mib"] - fast["peak_rss_mib"], 2)
    },sort_keys=True),flush=True)


if __name__ == "__main__":
    main()
