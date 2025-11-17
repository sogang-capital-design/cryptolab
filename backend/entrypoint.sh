#!/bin/bash
set -e

VENV_PATH=${VENV_PATH:-/opt/venv}
# 가상환경 없으면(볼륨 마운트 등) 새로 생성
if [ ! -x "$VENV_PATH/bin/python" ]; then
  echo "[entrypoint] virtualenv missing at $VENV_PATH. Creating..."
  python -m venv "$VENV_PATH"
  "$VENV_PATH/bin/pip" install --no-cache-dir -r /app/requirements.txt
fi
source "$VENV_PATH/bin/activate"

# 1) redis 먼저 실행 (백그라운드)
redis-server --bind 0.0.0.0 --port 6379 &
sleep 1

# 2) FastAPI 실행 (백그라운드)
"$VENV_PATH/bin/uvicorn" app.main:app --host 0.0.0.0 --port 8000 &

# 3) Celery 워커 실행 (포그라운드)
exec "$VENV_PATH/bin/celery" -A app.celery_app:celery_app worker -B --loglevel=debug
