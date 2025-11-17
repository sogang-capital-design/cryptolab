import pandas as pd
from fastapi import APIRouter, HTTPException

from app.celery_app import celery_app
from app.schemas.explain_schema import ExplainChartRequest, ExplainChartResponse, ExplainChartTaskResponse, SimilarChartResult, ExplainChartResult
from app.schemas.explain_schema import ExplainModelRequest, ExplainModelResponse, ExplainModelTaskResponse, ReferenceChartResult, ExplainModelResult
from app.tasks.explain_chart_task import explain_chart_task
from app.tasks.explain_model_task import explain_model_task

router = APIRouter()

@router.post("/model/", response_model=ExplainModelResponse)
async def explain(req: ExplainModelRequest) -> ExplainModelResponse:
    task = explain_model_task.delay(
        coin_symbol=req.coin_symbol,
        timeframe=req.timeframe,
        inference_time=req.inference_time
    )
    return ExplainModelResponse(task_id=task.id)

@router.get("/model/{task_id}", response_model=ExplainModelTaskResponse)
async def get_explanation(task_id: str) -> ExplainModelTaskResponse:
    explanation = explain_model_task.AsyncResult(task_id, app=celery_app)
    if explanation.successful():
        reference_charts = [ReferenceChartResult(**chart) for chart in explanation.result["reference_charts"]]
        explanation.result["reference_charts"] = reference_charts
        results = ExplainModelResult(**explanation.result)
    return ExplainModelTaskResponse(
        task_id=explanation.id,
        status=explanation.status,
        results=results if explanation.successful() else None
    )

@router.post("/chart/", response_model=ExplainChartResponse)
async def explain_chart(req: ExplainChartRequest) -> ExplainChartResponse:
    task = explain_chart_task.delay(
        coin_symbol=req.coin_symbol,
        timeframe=req.timeframe,
        inference_time=req.inference_time,
        start=req.start,
        end=req.end
    )
    return ExplainChartResponse(task_id=task.id)


@router.get("/chart/{task_id}", response_model=ExplainChartTaskResponse)
async def get_chart_explanation(task_id: str) -> ExplainChartTaskResponse:
    explanation = explain_chart_task.AsyncResult(task_id, app=celery_app)
    if explanation.successful():
        similar_charts = [SimilarChartResult(**chart) for chart in explanation.result["similar_charts"]]
        explanation.result["similar_charts"] = similar_charts
        results = ExplainChartResult(**explanation.result)
    return ExplainChartTaskResponse(
        task_id=explanation.id,
        status=explanation.status,
        results=results if explanation.successful() else None
    )