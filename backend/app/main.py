import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.db.database import Base, engine
from app.db import models as db_models
from app.routers import auth_router, watchlist_router
from app.routers import backtest_router, decide_router, models_router, train_router

# App
app = FastAPI(title="cryptolab API", version="0.1.0")

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

app.include_router(auth_router.router, prefix="/auth", tags=["auth"])
app.include_router(watchlist_router.router, prefix="/watchlist", tags=["watchlist"])

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

# Logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

# import uvicorn
# uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
