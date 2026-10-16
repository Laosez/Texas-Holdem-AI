# Isolated one-off benchmark: no heavyweight training dependencies.
FROM python:3.11-slim
WORKDIR /app
COPY . .
ENV PYTHONUNBUFFERED=1
CMD ["sh", "-c", "python -u -m unittest discover -s tests -p 'test_monte_carlo_equity.py' && python -u profile_equity_phases.py --samples 8000 --repeats 3 --profile-samples 1000"]
