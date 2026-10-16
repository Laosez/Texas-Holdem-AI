# Temporary audit runner: no changes to the live tournament simulator.
FROM python:3.11-slim
WORKDIR /app
COPY . .
ENV PYTHONUNBUFFERED=1
CMD ["sh", "-c", "python -u -m unittest discover -s tests -p 'test_monte_carlo_equity.py' && python -u -m unittest discover -s tests -p 'test_fast_eval.py' && python -u benchmark_fast_eval.py --samples 8000 --repeats 3"]
