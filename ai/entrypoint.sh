#!/bin/bash
set -e

# 1) redis 먼저 실행 (백그라운드)
redis-server --bind 0.0.0.0 --port 6379 &
sleep 1

# 2) FastAPI 실행 (백그라운드)
uvicorn app.main:app --host 0.0.0.0 --port 8000 &

# 3) Celery 워커 실행 (포그라운드)
exec celery -A app.celery_app:celery_app worker --loglevel=info
