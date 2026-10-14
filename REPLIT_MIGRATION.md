# SKACHKOV Poker System — Replit migration

Stage 1: the tournament simulator. No changes to the poker engine or bots.

## Repository and import

Source-of-truth branch: feature/separate-preflop-postflop.
Migration branch: feat/replit-simulator-20261014.

1. In Replit choose Import from GitHub for:
   https://github.com/Laosez/Texas-Holdem-AI
2. Checkout branch feat/replit-simulator-20261014. If Replit
   imported another branch, open Replit Shell:

       git fetch origin feat/replit-simulator-20261014
       git checkout feat/replit-simulator-20261014

3. Set a strong private secret in Replit Secrets named POKER_RUNNER_KEY.
   Never put it in GitHub or screenshots.
4. Press Run. File .replit launches Python server on 0.0.0.0:3000.
   Enter the same secret into the dashboard.
5. Click "Восстановить контроль V3", run 2 tournaments as smoke, then 90.
6. Download results ZIP before closing/deleting the Replit App.

## Verification in Replit Shell

    python3 -m unittest test_replit_simulator -v

    THAI_ENGINE_IMPL=legacy python3 -m unittest \
      test_a17_position_ranges test_a17_vs_3bet \
      test_a17_fixed_gto_tag test_street_split_bot -q

    THAI_ENGINE_IMPL=legacy python3 export_preflop_ranges_v4.py \
      --players a17_tag,gto --tournaments 2 --parallel 1 \
      --seed 2042 --chips 500 --sb 1 --bb 2 \
      --blind-increase-every 50 --max-hands 10000 \
      --seat-mode rotate --out output/replit_smoke

Exact control bots use Python standard library in the legacy engine.
The repository-wide requirements.txt includes additional dependencies
for other tools (e.g. torch); avoid installing them unnecessarily.

## Frozen baseline

- 9 bots: split:gto:smart, split:gto:gto,
  split:gto:tag_punisher, split:gto:maniac_mixed,
  split:gto:baseline_sane, a17_tag,
  split:gto:random, split:gto:random_2,
  split:gto:pressure_filler.
- seed: 2042; tournaments: 90; parallel: 2.
- chips: 500; blinds 1/2; escalation every 50 hands.
- max_hands: 10000; seat mode: rotate; engine: legacy.

Historical Codespaces batch produced a17_tag 23/90 wins (25.6%).
Replit parity is NOT yet verified; we must run it there.

## Runner scope

- Validates bot types and all simulation settings; no arbitrary shell.
- Single background tournament subprocess, optional cancel action.
- Live log tail and tournament leaderboard from original exporter v4.
- ZIP download: per-hand position CSVs, tournament report, performance,
  metadata, etc. They can be loaded later into the Preflop Lab.
- Files in output/replit_runs are not automatically committed to GitHub.
- Access requires POKER_RUNNER_KEY. Keep Replit workspace private.

## Operational limitations

Compute jobs can be interrupted by workspace suspension or deployment
restart. Long-running jobs may require a persistent worker/Reserved VM.
Replit CPU allotment, time, and expenses are separate from GitHub.
Backup generated experiment ZIPs before deleting the Replit workspace.
90 results are statistically noisy, and seed-based results can differ
by Python version, dependencies or execution order.

## Next stages

2. Integrate 'Анализ префлоп.html' by reading the same v4 CSV dataset
   and keeping observed action frequencies distinct from theoretical ranges.
   Complete hand replay is NOT present in exporter v4; add explicit
   replay telemetry separately if needed.
3. Integrate SKACHKOV Strategy Planner 2.0. Add JSON bot policy loader
   and automated no-change round-trip parity tests before letting the
   edited strategy run in tournaments.
