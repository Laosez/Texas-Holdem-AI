# Stage 1: lightweight, reproducible server for existing v4 simulator.
# Control bots + legacy engine use Python standard library.
# Do NOT install repo-wide requirements.txt here (torch etc. not needed for this experiment).
FROM python:3.11-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 THAI_ENGINE_IMPL=legacy
WORKDIR /app
COPY . /app
EXPOSE 3000
CMD ["python", "-u", "replit_simulator.py"]
