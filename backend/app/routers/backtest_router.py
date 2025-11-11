from fastapi import APIRouter, HTTPException

from app.celery_app import celery_app
from app.schemas.backtest_schema import BacktestRequest, BacktestResponse, BacktestTaskResponse
from app.tasks.backtest_task import backtest_task

router = APIRouter()

@router.post("/", response_model=BacktestResponse)
async def backtest(req: BacktestRequest) -> BacktestResponse:
    backtest_start, backtest_end = req.start.isoformat(), req.end.isoformat()
    task = backtest_task.delay(req.model_name, req.param_name, req.coin_symbol, req.timeframe, backtest_start, backtest_end)
    return BacktestResponse(task_id=task.id)

@router.get("/{task_id}", response_model=BacktestTaskResponse)
async def get_backtest_task_status(task_id: str) -> BacktestTaskResponse:
    task = backtest_task.AsyncResult(task_id, app=celery_app)
    return BacktestTaskResponse(task_id=task.id, status=task.status, results=task.result if task.successful() else {})