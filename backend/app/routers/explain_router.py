import pandas as pd
from fastapi import APIRouter, HTTPException

from app.celery_app import celery_app
from app.schemas.explain_schema import ExplainChartRequest, ExplainChartResponse, ExplainChartTaskResponse, ExplainChartResult
from app.schemas.explain_schema import ExplainModelRequest, ExplainModelResponse, ExplainModelTaskResponse, ReferenceChartResult, ExplainModelResult
from app.schemas.explain_schema import (
    ExplainSimilarChartRequest, ExplainSimilarChartResponse, ExplainSimilarChartResult, ExplainSimilarChartTaskResponse,
    SimilarChart, SimilarChartStats, DifferenceStats
)
from app.tasks.explain_chart_task import explain_chart_task
from app.tasks.explain_model_task import explain_model_task
from app.tasks.explain_similar_chart_task import explain_similar_chart_task

router = APIRouter()

@router.post("/model/", response_model=ExplainModelResponse)
async def explain(req: ExplainModelRequest) -> ExplainModelResponse:
    task = explain_model_task.delay(
        model_name=req.model_name,
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
        inference_time=req.inference_time
    )
    return ExplainChartResponse(task_id=task.id)


@router.get("/chart/{task_id}", response_model=ExplainChartTaskResponse)
async def get_chart_explanation(task_id: str) -> ExplainChartTaskResponse:
    explanation = explain_chart_task.AsyncResult(task_id, app=celery_app)
    results = None
    if explanation.successful():
        results = ExplainChartResult(**explanation.result)
    return ExplainChartTaskResponse(
        task_id=explanation.id,
        status=explanation.status,
        results=results
    )

@router.post("/similar_chart/", response_model=ExplainSimilarChartResponse)
async def explain_similar_chart(req: ExplainSimilarChartRequest) -> ExplainSimilarChartResponse:
    task = explain_similar_chart_task.delay(
        coin_symbol=req.coin_symbol,
        timeframe=req.timeframe,
        inference_time=req.inference_time,
        search_start=req.search_start,
        search_end=req.search_end
    )
    return ExplainSimilarChartResponse(task_id=task.id)

@router.get("/similar_chart/{task_id}", response_model=ExplainSimilarChartTaskResponse)
async def get_similar_chart_explanation(task_id: str) -> ExplainSimilarChartTaskResponse:
    explanation = explain_similar_chart_task.AsyncResult(task_id, app=celery_app)
    if explanation.successful():
        similar_charts = [SimilarChart(**chart) for chart in explanation.result["top_similar_charts"]]
        explanation.result["top_similar_charts"] = similar_charts
        stats_payload = explanation.result["similar_chart_stats"]
        feature_stats = {
            stat_key: DifferenceStats(**stat_value)
            for stat_key, stat_value in stats_payload["feature_stats"].items()
        }
        similar_chart_stats = SimilarChartStats(
            price_up_count=stats_payload["price_up_count"],
            price_down_count=stats_payload["price_down_count"],
            feature_stats=feature_stats
        )
        explanation.result["similar_chart_stats"] = similar_chart_stats
        results = ExplainSimilarChartResult(**explanation.result)
    return ExplainSimilarChartTaskResponse(
        task_id=explanation.id,
        status=explanation.status,
        results=results if explanation.successful() else None
    )