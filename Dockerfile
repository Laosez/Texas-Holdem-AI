# Stage 1: lightweight, reproducible server for existing v4 simulator.
# Control bots + legacy engine use Python standard library.
# Do NOT install repo-wide requirements.txt here (torch etc. not needed for this experiment).
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 THAI_ENGINE_IMPL=legacy
WORKDIR /app
COPY . /app
# Fail the image build if Screen 1 validation, strategy import or actual engine smoke fails.
RUN python -m unittest test_replit_simulator test_screen1 test_a17_position_ranges -v
RUN THAI_ENGINE_IMPL=legacy python -u export_preflop_ranges_v4.py \
    --players P1=split:gto:gto,P2=split:gto:gto --tournaments 2 \
    --parallel 1 --seed 2042 --chips 500 --sb 1 --bb 2 \
    --blind-increase-every 50 --max-hands 10000 --seat-mode rotate \
    --out /tmp/screen1_smoke && \
    test -f /tmp/screen1_smoke/tournament_report.json && \
    rm -rf /tmp/screen1_smoke
EXPOSE 3000
CMD ["python", "-u", "replit_simulator.py"]
