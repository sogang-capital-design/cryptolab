from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.schemas.watchlist_schema import WatchlistCreateRequest, WatchlistResponse
from app.services.watchlist_service import create_watchlist_once, get_watchlist
from app.routers.auth_router import get_current_user

router = APIRouter()

@router.post("", response_model=WatchlistResponse)
def set_watchlist(payload: WatchlistCreateRequest, db: Session = Depends(get_db), current=Depends(get_current_user)):
    symbols = create_watchlist_once(db, current.id, payload.symbols)
    return WatchlistResponse(symbols=[s.upper() for s in symbols])

@router.get("", response_model=WatchlistResponse)
def read_watchlist(db: Session = Depends(get_db), current=Depends(get_current_user)):
    symbols = get_watchlist(db, current.id)
    return WatchlistResponse(symbols=symbols)

