from typing import List
from sqlalchemy.orm import Session
from sqlalchemy import select, func, delete
from fastapi import HTTPException, status
from app.db import models

# 제출용: 허용 심볼(Upbit 대표 심볼 샘플) — 필요시 추가
# 모든 코인을 허용하도록 변경 (빈 세트는 모든 심볼 허용을 의미)
ALLOWED_UPBIT = set()  # 빈 세트 = 모든 코인 허용

def get_watchlist(db: Session, user_id: int) -> List[str]:
    rows = db.execute(select(models.Watchlist.symbol).where(models.Watchlist.user_id == user_id)).all()
    return [r[0] for r in rows]

def add_to_watchlist(db: Session, user_id: int, symbol: str) -> List[str]:
    """관심 코인에 개별 심볼 추가"""
    symbol_upper = symbol.upper()

    # 허용 목록 체크 (설정되어 있을 경우)
    if ALLOWED_UPBIT and symbol_upper not in ALLOWED_UPBIT:
        raise HTTPException(status_code=400, detail=f"Invalid symbol: {symbol_upper}")

    # 이미 존재하는지 확인
    existing = db.scalar(
        select(models.Watchlist)
        .where(models.Watchlist.user_id == user_id)
        .where(models.Watchlist.symbol == symbol_upper)
    )

    if existing:
        # 이미 존재하면 현재 목록만 반환
        return get_watchlist(db, user_id)

    # 새로운 관심 코인 추가
    wl = models.Watchlist(user_id=user_id, symbol=symbol_upper)
    db.add(wl)
    db.commit()

    return get_watchlist(db, user_id)

def remove_from_watchlist(db: Session, user_id: int, symbol: str) -> List[str]:
    """관심 코인에서 개별 심볼 제거"""
    symbol_upper = symbol.upper()

    # 삭제 실행
    result = db.execute(
        delete(models.Watchlist)
        .where(models.Watchlist.user_id == user_id)
        .where(models.Watchlist.symbol == symbol_upper)
    )
    db.commit()

    return get_watchlist(db, user_id)

def create_watchlist_once(db: Session, user_id: int, symbols: List[str]) -> List[str]:
    # 이미 등록했는지 검사 (이제 추가 등록도 허용)
    existing_count = db.scalar(select(func.count()).select_from(models.Watchlist).where(models.Watchlist.user_id == user_id))

    # 기존 관심 코인이 있으면 개별 추가로 처리
    if existing_count and existing_count > 0:
        # 기존 목록에 새 심볼들을 추가
        for symbol in symbols:
            add_to_watchlist(db, user_id, symbol)
        return get_watchlist(db, user_id)

    # 첫 설정일 경우: 정확히 5개 & 중복 없음 & 허용 목록 체크
    if len(symbols) != 5:
        raise HTTPException(status_code=400, detail="Exactly 5 symbols required for initial setup")
    if len(set(symbols)) != 5:
        raise HTTPException(status_code=400, detail="Duplicate symbols not allowed")
    if ALLOWED_UPBIT:  # 허용 목록이 설정되어 있으면 체크
        invalid = [s for s in symbols if s.upper() not in ALLOWED_UPBIT]
        if invalid:
            raise HTTPException(status_code=400, detail=f"Invalid symbols: {invalid}")

    # 저장
    for s in symbols:
        wl = models.Watchlist(user_id=user_id, symbol=s.upper())
        db.add(wl)
    db.commit()
    return symbols

