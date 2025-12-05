from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.schemas.watchlist_schema import WatchlistCreateRequest, WatchlistResponse, WatchlistToggleRequest
from app.services.watchlist_service import create_watchlist_once, get_watchlist, add_to_watchlist, remove_from_watchlist
from app.routers.auth_router import get_current_user

router = APIRouter()

@router.post("", response_model=WatchlistResponse)
def set_watchlist(payload: WatchlistCreateRequest, db: Session = Depends(get_db), current=Depends(get_current_user)):
    symbols = create_watchlist_once(db, current.id, payload.coin_symbols)
    return WatchlistResponse(coin_symbols=[s.upper() for s in symbols])

@router.get("", response_model=WatchlistResponse)
def read_watchlist(db: Session = Depends(get_db), current=Depends(get_current_user)):
    symbols = get_watchlist(db, current.id)
    return WatchlistResponse(coin_symbols=symbols)

@router.post("/add", response_model=WatchlistResponse)
def add_watchlist_coin(payload: WatchlistToggleRequest, db: Session = Depends(get_db), current=Depends(get_current_user)):
    symbols = add_to_watchlist(db, current.id, payload.coin_symbol)
    return WatchlistResponse(coin_symbols=symbols)

@router.delete("/remove", response_model=WatchlistResponse)
def remove_watchlist_coin(payload: WatchlistToggleRequest, db: Session = Depends(get_db), current=Depends(get_current_user)):
    symbols = remove_from_watchlist(db, current.id, payload.coin_symbol)
    return WatchlistResponse(coin_symbols=symbols)

