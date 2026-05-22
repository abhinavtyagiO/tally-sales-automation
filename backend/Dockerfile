FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend ./backend

RUN mkdir -p /data

ENV APP_ENV=production
ENV CONNECTOR_MODE=polling
ENV LOCAL_AGENT_BOOTSTRAP_ENABLED=false
ENV LEGACY_ENDPOINTS_ENABLED=false
ENV ALLOW_DEV_AUTH=false
ENV SQLITE_DB_PATH=/data/tally_sales.db

EXPOSE 8000

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
