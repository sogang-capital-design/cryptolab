from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import select, func
from fastapi import HTTPException, status
from app.db import models

# 제출용: 허용 심볼(Upbit 대표 심볼 샘플) — 필요시 추가
ALLOWED_UPBIT = {"BTC", "ETH", "XRP", "ADA", "SOL", "DOGE", "TRX", "DOT", "AVAX", "MATIC"}


def create_watchlist_once(db: Session, user_id: int, symbols: List[str]) -> List[str]:
    # 이미 등록했는지 검사 (한 번만 설정 가능 구조는 그대로 유지)
    existing_count = db.scalar(
        select(func.count())
        .select_from(models.Watchlist)
        .where(models.Watchlist.user_id == user_id)
    )
    if existing_count and existing_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Watchlist already set",
        )

    # 0개 이상 허용
    if len(symbols) == 0:
        # 선호 코인을 비워두는 것도 허용
        return []

    # 대문자로 정규화
    norm_symbols = [s.upper() for s in symbols]

    # 중복 체크
    if len(set(norm_symbols)) != len(norm_symbols):
        raise HTTPException(
            status_code=400,
            detail="Duplicate symbols not allowed",
        )

    # 허용 목록 체크
    invalid = [s for s in norm_symbols if s not in ALLOWED_UPBIT]
    if invalid:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid symbols: {invalid}",
        )

    # 저장
    for s in norm_symbols:
        wl = models.Watchlist(user_id=user_id, symbol=s)
        db.add(wl)
    db.commit()
    return norm_symbols


def get_watchlist(db: Session, user_id: int) -> List[str]:
    rows = db.execute(
        select(models.Watchlist.symbol).where(models.Watchlist.user_id == user_id)
    ).all()
    return [r[0] for r in rows]
