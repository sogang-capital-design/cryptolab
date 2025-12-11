# CryptoLab

### AI 기반 암호화폐 투자 분석 플랫폼, CryptoLab

### https://cryptolab-frontend.vercel.app

</br>

## 프로젝트 소개

CryptoLab은 머신러닝 모델과 기술적 분석을 활용하여 암호화폐 시장을 분석하고 투자 의사결정을 지원하는 웹 애플리케이션입니다.

## 주요 기능

### 1. AI 모델 분석 결과 제공 및 설명
- LSTM, RNN, Transformer, LightGBM 등 다양한 머신러닝 모델을 통한 가격 예측
- SHAP을 활용한 모델 예측 결과의 해석 및 시각화
- 각 모델의 특징별 기여도 분석으로 예측 근거 제공

<img width="1614" height="885" alt="image" src="https://github.com/user-attachments/assets/ce4aee20-a634-4b66-89fa-c6602787d074" />

### 2. 시장 상황 분석
- 실시간 OHLCV 데이터 수집 및 분석
- 온체인 데이터를 활용한 시장 동향 파악
- 기술적 지표(TA) 기반 시장 분석

<img width="2332" height="1248" alt="image" src="https://github.com/user-attachments/assets/93e9a778-ad6c-483b-a4ed-65cf0d432af9" />


### 3. 유사 차트 검색 및 분석
- DTW(Dynamic Time Warping) 알고리즘을 활용한 차트 패턴 유사도 측정
- 과거 유사 패턴 검색을 통한 가격 움직임 예측
- 유사 차트의 이후 추세 분석 및 시각화

<img width="2322" height="1258" alt="image" src="https://github.com/user-attachments/assets/02374d0c-6198-4456-bab0-23f70ca1295f" />

<img width="2300" height="1270" alt="image" src="https://github.com/user-attachments/assets/afdc37e4-b8fa-4d69-9550-a96d3f7033a6" />


## 배포

- 배포용 Backend: https://github.com/joshua5301/cryptolab-backend
- 배포용 Frontend: https://github.com/joshua5301/cryptolab-frontend

## 기술 스택

### Frontend
- **Framework**: Next.js 15.5.4
- **UI Library**: React 19.1.0
- **Styling**: Tailwind CSS 4
- **Charts**: Chart.js, react-chartjs-2
- **API**: use-upbit-api (업비트 실시간 데이터)
- **Language**: TypeScript

### Backend
- **Framework**: FastAPI
- **ML/DL**: PyTorch, LightGBM, scikit-learn
- **Data Analysis**: pandas, numpy, scipy
- **Explainability**: SHAP
- **Technical Analysis**: TA-Lib
- **Task Queue**: Celery + Redis
- **Database**: SQLAlchemy
- **Authentication**: JWT (python-jose, passlib)
- **API Client**: OpenAI API (GPT 기반 설명 생성)

## 프로젝트 구조

```
cryptolab/
├── fe/                          # Frontend (Next.js)
│   ├── src/
│   │   ├── app/                # Next.js App Router
│   │   ├── components/         # React 컴포넌트
│   │   ├── lib/                # 유틸리티 함수
│   │   └── types/              # TypeScript 타입 
│   └── package.json
│
└── backend/                     # Backend (FastAPI)
    ├── app/
    │   ├── routers/            # API 엔드포인트
    │   ├── services/           # 비즈니스 로직
    │   ├── tasks/              # Celery 백그라운드 
    │   ├── strategies/         # 트레이딩 전략 및 
    │   ├── schemas/            # Pydantic 스키마
    │   ├── db/                 # 데이터베이스 모델
    │   └── utils/              # 유틸리티 함수
    ├── config/                 # 설정 파일
    ├── data/                   # 데이터 저장소
    └── requirements.txt
```

## 시작하기

### 사전 요구사항
- Node.js 20+
- Python 3.12+
- Docker (권장)
- Redis (Celery 브로커용)

### Frontend 실행

```bash
cd fe
npm install
npm run dev
```

프론트엔드는 [http://localhost:3000](http://localhost:3000)에서 실행됩니다.

### Backend 실행

#### Docker 사용 (권장)

```bash
cd backend
docker build -t backend-dev .
docker run --rm -it -v "$(pwd):/app" -p 8000:8000 --env-file .env backend-dev
```

#### 로컬 환경

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

백엔드 API는 [http://localhost:8000](http://localhost:8000)에서 실행됩니다.

## API 문서

백엔드 서버 실행 후 다음 URL에서 API 문서를 확인할 수 있습니다:
- Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- ReDoc: [http://localhost:8000/redoc](http://localhost:8000/redoc)
  

