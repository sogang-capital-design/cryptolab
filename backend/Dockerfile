# ai/Dockerfile

# 1. 'trixie' 대신 'bookworm' (안정 버전)을 사용하도록 명시합니다.
FROM python:3.11-slim-bookworm

# 2. 'dos2unix' 패키지를 설치 목록에 추가
RUN apt-get update && apt-get install -y \
    redis-server \
    libgomp1 \
    build-essential \
    bash \
    dos2unix \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY . /app

# 3. 실행 권한 주기 전에, 파일을 리눅스 형식으로 변환
RUN dos2unix /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENV PYTHONPATH=/app
ENV CELERY_BROKER_URL=redis://localhost:6379/0
ENV CELERY_RESULT_BACKEND=redis://localhost:6379/1
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000

CMD ["/app/entrypoint.sh"]