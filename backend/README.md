## Backend Docker Setup

`entrypoint.sh`는 `/opt/venv` 가상환경을 사용합니다. Docker 이미지 빌드 시 해당 venv가 생성되며, 컨테이너에서 로컬 프로젝트를 `/app`에 마운트해도 `/opt/venv`는 그대로 유지됩니다. Docker 없이 로컬 실행 시에는 다음과 같이 수동으로 `.venv`를 준비하세요.

1. `python3 -m venv .venv`
2. `source .venv/bin/activate`
3. `pip install -r requirements.txt`

1. 도커 데스크탑 설치 및 실행
2. backend 디렉토리로 이동
3. docker build -t backend-dev .
4. docker run --rm -it -v "$(pwd -W):/app" -p 8000:8000 backend-dev

## Environment Variables

루트 디렉토리에 `.env` 파일을 두고 실행 시 `--env-file .env`(Docker) 또는 `dotenv` 로더로 읽어 주세요.

| 변수 | 기본값 | 설명 |
| --- | --- | --- |
| `JWT_SECRET` | `dev-only-secret-change-me` | JWT 서명을 위한 비밀 키. 운영 환경에서는 반드시 고유 값으로 교체하여야 합니다. |
| `JWT_EXPIRE_SECONDS` | `7200` | 액세스 토큰 만료 시간(초). |
| `OPENAI_API_KEY` | `dev-only-secret-change-me` | openAI GPT를 사용한 설명 기능을 위한 비밀 키. 운영 환경에서는 반드시 고유 값으로 교체하여야 합니다. |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery 브로커 URL(기본 Redis). |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/1` | Celery 결과 저장 백엔드 URL. |
| `OHLCV_CONFIG_PATH` | `config/ohlcv_settings.yml` | OHLCV 수집 심볼/타임프레임 설정 파일 경로. |
| `DEFAULT_TARGET_TIMEFRAMES` | `60m,240m,1d` | 설정 파일에 target 목록이 없을 때 사용할 기본 타임프레임 집합. |
| `UPBIT_API_BASE_URL` | `https://api.upbit.com/v1` | Upbit REST API 기본 URL. |
| `OHLCV_COLLECT_START` | `2024-01-01T00:00:00` | 최초 수집 시 수집 대상 기간의 최초 일시. 이 시점부터 서버 구동 시점까지를 수집합니다. |
| `OHLCV_RETRY_LIMIT` | `1` | 누락 구간 재수집 최대 횟수. 실패 시 보간으로 대체. |
| `OHLCV_COLLECTION_INTERVAL_SECONDS` | `300` | 과거 주기형 스케줄용 값(하위 호환). |
| `OHLCV_EXECUTION_OFFSET_SECONDS` | `3` | 정각 기준 몇 초 뒤에 수집 태스크를 실행할지 오프셋. |

> Celery beat은 최소 base 타임프레임을 기준으로 정시마다 태스크를 실행하며, 워커 시작 시 즉시 한 번 실행합니다.
