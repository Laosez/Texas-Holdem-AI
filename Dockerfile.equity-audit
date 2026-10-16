# Isolated one-off benchmark: no heavyweight training dependencies.
FROM python:3.11-slim
WORKDIR /app
COPY . .
ENV PYTHONUNBUFFERED=1
CMD ["sh", "-c", "python -u -m unittest discover -s tests -p 'test_monte_carlo_equity.py' && python -u benchmark_equity.py --repeats 1 --output /tmp/equity_benchmark.csv"]
