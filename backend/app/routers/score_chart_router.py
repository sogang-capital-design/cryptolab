import pandas as pd
from fastapi import APIRouter, HTTPException

from app.celery_app import celery_app
from app.schemas.score_chart_schema import (
    ScoreChartRequest,
    ScoreChartResponse,
    ScoreWithExplanation,
    ScoreChartTaskResponse,
)
from app.tasks.score_chart_task import score_chart_task
from app.utils.data_utils import get_ohlcv_df

router = APIRouter()

@router.post("/", response_model=ScoreChartResponse)
async def score_chart(req: ScoreChartRequest) -> ScoreChartResponse:
    task = score_chart_task.delay(req.coin_symbol, req.timeframe, req.inference_time.isoformat(), req.history_window)
    return ScoreChartResponse(task_id=task.id)

@router.get("/{task_id}", response_model=ScoreChartTaskResponse)
async def get_score_chart(task_id: str) -> ScoreChartTaskResponse:
    task = score_chart_task.AsyncResult(task_id, app=celery_app)
    if task.successful() and isinstance(task.result, dict):
        try:
            results = {k: ScoreWithExplanation(**v) for k, v in task.result.items()}
        except Exception:
            results = None
    else:
        results = None
    return ScoreChartTaskResponse(task_id=task.id, status=task.status, results=results)

