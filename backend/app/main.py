import logging
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.db.database import Base, engine
from app.db import models as db_models
from app.routers import auth_router, watchlist_router
from app.routers import data_router, models_router, score_chart_router
from app.routers import backtest_router, decide_router, train_router, explain_router

# App
app = FastAPI(title="cryptolab API", version="0.1.0")
app.state.ingest_ready = False

# Basic CORS -- adjust origins in real deployments
app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"],
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)

app.include_router(decide_router.router, prefix="/decide", tags=["decide"])
app.include_router(train_router.router, prefix="/train", tags=["train"])
app.include_router(backtest_router.router, prefix="/backtest", tags=["backtest"])
app.include_router(models_router.router, prefix="/models", tags=["models"])
app.include_router(explain_router.router, prefix="/explain", tags=["explain"])
app.include_router(score_chart_router.router, prefix="/score-chart", tags=["score-chart"])
app.include_router(data_router.router, prefix="/data", tags=["data"])
app.include_router(auth_router.router, prefix="/auth", tags=["auth"])
app.include_router(watchlist_router.router, prefix="/watchlist", tags=["watchlist"])

@app.middleware("http")
async def ensure_ingest_ready(request: Request, call_next):
    if getattr(app.state, "ingest_ready", False):
        return await call_next(request)
    return JSONResponse(status_code=503, content={"detail": "Initial OHLCV ingest pending"})

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)
    _run_initial_ingest()

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# import uvicorn
# uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

def _run_initial_ingest() -> None:
    """Run a single OHLCV collection cycle before serving other endpoints."""
    from app.db.database import SessionLocal
    from app.services.ohlcv_service import OHLCVIngestService

    session = SessionLocal()
    service = OHLCVIngestService()
    try:
        service.collect_latest(session)
    finally:
        session.close()
    app.state.ingest_ready = True
