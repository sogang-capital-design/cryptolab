from fastapi import APIRouter, HTTPException

from app.celery_app import celery_app
from app.schemas.backtest import BacktestRequest, BacktestResponse, BacktestTaskResponse
from app.tasks.backtest_task import backtest_task

router = APIRouter()

@router.post("/", response_model=BacktestResponse)
async def backtest(req: BacktestRequest) -> BacktestResponse:
    model_name, hyperparams = req.model_name, req.hyperparams
    backtest_start, backtest_end = req.start.isoformat(), req.end.isoformat()
    task = backtest_task.delay(model_name, backtest_start, backtest_end, hyperparams)
    return BacktestResponse(task_id=task.id)

@router.get("/{task_id}", response_model=BacktestTaskResponse)
async def get_backtest_task_status(task_id: str) -> BacktestTaskResponse:
    task = backtest_task.AsyncResult(task_id, app=celery_app)
    return BacktestTaskResponse(task_id=task.id, status=task.status)