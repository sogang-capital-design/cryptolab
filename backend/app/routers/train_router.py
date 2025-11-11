from fastapi import APIRouter, HTTPException

from app.celery_app import celery_app
from app.schemas.train_schema import TrainRequest, TrainResponse, TrainTaskResponse
from app.tasks.train_task import train_task

router = APIRouter()

@router.post("/", response_model=TrainResponse)
async def train(req: TrainRequest) -> TrainResponse:
    train_start, train_end = req.start.isoformat(), req.end.isoformat()
    task = train_task.delay(req.model_name, req.param_name, req.coin_symbol, req.timeframe, train_start, train_end, req.hyperparams)
    return TrainResponse(task_id=task.id)

@router.get("/{task_id}", response_model=TrainTaskResponse)
async def get_train_task_status(task_id: str) -> TrainTaskResponse:
    task = train_task.AsyncResult(task_id, app=celery_app)
    return TrainTaskResponse(task_id=task.id, status=task.status)