FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server ./server
COPY health_dashboard.html ./health_dashboard.html
COPY data/model_artifacts ./data/model_artifacts

RUN mkdir -p /app/data

EXPOSE 10000

CMD ["sh", "-c", "uvicorn server.main:app --host 0.0.0.0 --port ${PORT:-10000}"]
