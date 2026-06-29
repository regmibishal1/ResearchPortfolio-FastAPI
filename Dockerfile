FROM python:3.10-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
# Alembic migrations live alongside the app so `docker compose run --rm fastapi alembic upgrade head`
# works inside the deployed container. The runtime container itself never invokes alembic; migrations
# are run as an explicit step by the operator (see CLAUDE.md §6 in the orchestrator).
COPY alembic ./alembic
COPY alembic.ini .
EXPOSE 8000
CMD ["gunicorn", "-w", "4", "-k", "uvicorn.workers.UvicornWorker", "--bind", "0.0.0.0:8000", "src.main:app"]
