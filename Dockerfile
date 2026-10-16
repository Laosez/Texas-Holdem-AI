# Audit branch ONLY; production release Dockerfile is preserved on release branch.
FROM python:3.11-slim
WORKDIR /app
COPY . .
ENV PYTHONUNBUFFERED=1 PYTHONPATH=/app THAI_ENGINE_IMPL=legacy
CMD ["python","-u","scripts/audit_planner_mc.py"]
