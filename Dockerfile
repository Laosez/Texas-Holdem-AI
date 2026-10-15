# Stage 1: lightweight, reproducible server for existing v4 simulator.
# Control bots + legacy engine use Python standard library.
# Do NOT install repo-wide requirements.txt here (torch etc. not needed for this experiment).
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 THAI_ENGINE_IMPL=legacy
WORKDIR /app
COPY . /app
# Fail the image build if Screen 1 validation, strategy import or actual engine smoke fails.
RUN python -m unittest test_replit_simulator test_screen1 test_a17_position_ranges test_reliability test_planner test_planner_http test_postflop_telemetry test_postflop_profiles -v
RUN THAI_ENGINE_IMPL=legacy python -u export_preflop_ranges_v4.py \
    --players P1=split:a17_preflop:tag_punisher,P2=split:a17_preflop_legacy:tag_punisher --tournaments 2 \
    --parallel 1 --seed 2042 --chips 500 --sb 1 --bb 2 \
    --blind-increase-every 50 --max-hands 10000 --seat-mode rotate \
    --out /tmp/screen1_smoke --checkpoint-dir /tmp/screen1_checkpoints && \
    test -f /tmp/screen1_smoke/tournament_report.json && \
    test -f /tmp/screen1_checkpoints/000001.json.gz && \
    rm -rf /tmp/screen1_smoke /tmp/screen1_checkpoints
# Control regression: prove 90 full nine-player tournaments without multiprocessing on Railway.
RUN THAI_ENGINE_IMPL=legacy python -u export_preflop_ranges_v4.py \
    --players split:gto:smart,split:gto:gto,split:gto:tag_punisher,split:gto:maniac_mixed,split:gto:baseline_sane,split:a17_preflop:tag_punisher,split:gto:random,split:gto:random_2,split:gto:pressure_filler \
    --tournaments 90 --parallel 1 --seed 2042 --chips 500 --sb 1 --bb 2 \
    --blind-increase-every 50 --max-hands 10000 --seat-mode rotate \
    --out /tmp/reliability_90 --checkpoint-dir /tmp/reliability_90_checkpoint && \
    test -f /tmp/reliability_90/tournament_report.json && \
    test -f /tmp/reliability_90_checkpoint/000090.json.gz && \
    rm -rf /tmp/reliability_90 /tmp/reliability_90_checkpoint
EXPOSE 3000
CMD ["python", "-u", "replit_simulator.py"]
