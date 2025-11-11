# Backend Docker Setup

1. 도커 데스크탑 설치 및 실행
2. backend 디렉토리로 이동
3. docker build -t backend-dev .
4. docker run --rm -it -v "$(pwd -W):/app" -p 8000:8000 backend-dev