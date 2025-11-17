# ai/Dockerfile
FROM python:3.11-slim

RUN apt-get update && apt-get install -y \
    redis-server \
    libgomp1 \
    build-essential \
    bash \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

ENV VIRTUAL_ENV=/opt/venv
RUN python -m venv $VIRTUAL_ENV && \
    $VIRTUAL_ENV/bin/pip install --no-cache-dir --upgrade pip

COPY requirements.txt /app/requirements.txt
RUN $VIRTUAL_ENV/bin/pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

ENV PATH="$VIRTUAL_ENV/bin:$PATH"
ENV PYTHONPATH=/app
ENV CELERY_BROKER_URL=redis://localhost:6379/0
ENV CELERY_RESULT_BACKEND=redis://localhost:6379/1
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

CMD ["python", "/app/entrypoint.py"]
