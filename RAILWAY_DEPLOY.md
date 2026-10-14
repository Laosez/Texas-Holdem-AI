# SKACHKOV Poker System — Railway reliability release (14 Oct 2026)

## Live architecture

- Railway project `sublime-creation`, production service `Texas-Holdem-AI`.
- Server: `replit_simulator.py` (historical filename; it runs on Railway).
- Web UI: `replit_ui/index.html`. Screen 1 is implemented; screens 2–4 are future modules.
- Legacy tournament engine: `export_preflop_ranges_v4.py` with `THAI_ENGINE_IMPL=legacy`.
- Storage: Railway Volume mounted at `/data`, `POKER_DATA_DIR=/data`.
- Protection: `POKER_RUNNER_KEY` in Railway Variables; never store it in GitHub.
- Docker image: Python 3.11, no repo-wide torch/matplotlib dependency installation.
- Railway start: `python -u replit_simulator.py`; health: `GET /health`.

## Canonical strategy provenance

The authoritative A17 hand→box mapping is **`strategy_catalog/a17_v5.json`**:
169 classes, 1,326 card combinations, 17 boxes. It matches
`SKACHKOV_A17_BOXES_EDITED (5).json` in the supplied files.
**JTo and J9o are A14**, rather than A10 in the historical implementation.
`bots/a17_ranges.py` reads this JSON and fails hard on missing/incorrect classes.
`bots/a17_ranges_legacy.py` freezes the original rules; it is available as
`a17_preflop_legacy` and `a17_tag_legacy`.
Use `a17_preflop` for A17 V5 and `a17_preflop_legacy` when reproducing old
experiments. The historical `a17_tag` profile name in *older* sessions does
not prove the new V5 was used; historical restores map it explicitly to Legacy.

`strategy_catalog/available_bases.json` is the shared registry used by the
Python split-strategy factory, server validation and HTML strategy dropdown.
A blank preflop/postflop value always prevents starting.

## Crash protection

The observed `BrokenProcessPool` at 54/90 in earlier runs is compatible
with a process being killed abruptly; **OOM is plausible but not confirmed**.
Railway's measured service limit was ~1 GiB RAM / 2 vCPU.
On Railway, both UI and server now reject `parallel>1`.
For each completed tournament, the exporter writes a compressed
`_checkpoints/000001.json.gz` etc. The checkpoint is atomic and includes
the input configuration and exporter version hash.
The **Continue** button works on failed/cancelled/interrupted runs only when
the full strategy fingerprint matches. Old, unversioned runs cannot safely
resume; start a new V5 or explicit Legacy session instead.

**Build regression:** 38 unit tests plus two A17 V5-vs-Legacy smoke tournaments,
and 90 complete nine-seat tournaments with `--parallel 1`, seed 2042,
500 chips and blinds 1/2 (+50 hands), using the A17 V5+TAG control.
One Railway build verified 90/90 completed, 85.06 s, 458.9 hands/s
and 22 A17 V5+TAG wins. This result is *not* direct historical-strategy parity.

## Session preservation

Each session lives in `/data/<session_id>/` with CSV and JSON reports,
`simulation.log`, `job.json`, checkpoints, and a `integrity.json` manifest
(SHA-256 on success). Session ZIP exports also include
`session_manifest.json` (format V2, configuration and code fingerprint).
ZIP import validates safe filenames, quotas and available SHA-256 checksums.
The UI can restore configuration and view logs after a Railway restart.

Deletion is reversible: sessions move to `/data/.trash/<session_id>/`,
and the **Корзина** button restores them. Session list is lightweight and
loads detail only for the selected run. No 40-session visibility cap.

- **Аудит файлов:** checks saved files, reports, SHA-256 (where available),
  checkpoint count and volume free space.
- **Архив всех сессий:** downloads all sessions, recycle-bin entries and
  reference strategy JSON as one file.
- **Восстановить архив:** imports that complete archive with new session IDs
  without overwriting existing experiment files.
- **Автоматическая внешняя копия is NOT yet configured**: Railway Volume alone
  is not a disaster-recovery backup. Download ZIP to a separate device or
  connect an independent S3-compatible bucket with explicit resource approval.

## Rollback, deployment and safeguards

Avoid editing the production source branch while a tournament is running:
a new Railway deploy interrupts it (completed checkpoints remain on Volume).
For release, deploy a tested, pinned release branch instead of directly
tracking an actively edited feature branch. The public GitHub repository
`Laosez/Texas-Holdem-AI` is not suitable for storing private keys or
proprietary secret equity datasets without changing visibility/permissions.
Do not assume secrets or results are backed up to GitHub; they are not.
The tested 90-tournament run during Docker **build** uses `/tmp`: it is a
correctness/performance check, not an archived user session in `/data`.

## Not yet in scope

- Complete street-by-street hand replay and net bb/100 need per-hand chip
  delta tracking; current v4 preflop observation is not sufficient.
- Strategy Planner, Preflop Lab integration and original 1–5-opponent
  equity benchmark CSV have not been verified as live application datasets.
- Offsite S3 backup and secret rotation require separate operational setup.
