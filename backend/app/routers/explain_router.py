import pandas as pd
from fastapi import APIRouter, HTTPException

from app.celery_app import celery_app
from app.schemas.explain_schema import ExplainRequest, ExplainResponse, ExplainTaskResponse, ExplainResult, SimilarChartResult
from app.tasks.explain_task import explain_task

router = APIRouter()

@router.post("/", response_model=ExplainResponse)
async def explain(req: ExplainRequest) -> ExplainResponse:
    task = explain_task.delay(
        model_name=req.model_name,
        param_name=req.param_name,
        coin_symbol=req.coin_symbol,
        timeframe=req.timeframe,
        train_start=req.train_start,
        train_end=req.train_end,
        inference_time=req.inference_time
    )
    return ExplainResponse(task_id=task.id)


@router.get("/{task_id}", response_model=ExplainTaskResponse)
async def get_explanation(task_id: str) -> ExplainTaskResponse:
    explanation = explain_task.AsyncResult(task_id, app=celery_app)
    if explanation.successful():
        similar_charts = [SimilarChartResult(**chart) for chart in explanation.result["similar_charts"]]
        explanation.result["similar_charts"] = similar_charts
        results = ExplainResult(**explanation.result)
    return ExplainTaskResponse(
        task_id=explanation.id,
        status=explanation.status,
        results=results if explanation.successful() else None
    )