from fastapi import APIRouter, HTTPException

from app.schemas.data_schema import CoinInfoRequest, CoinInfoResponse, CoinListResponse
from app.utils.data_utils import get_all_data_info

router = APIRouter()

@router.get("/list", response_model=CoinListResponse)
def list_coins() -> CoinListResponse:
    info = get_all_data_info()
    all_coins = [coin for coin, _, _ in info]
    return CoinListResponse(available_coin_symbols=all_coins)

@router.post("/info", response_model=CoinInfoResponse)
def get_coin_info(req: CoinInfoRequest) -> CoinInfoResponse:
    info = get_all_data_info()
    for coin_symbol, start_time, end_time in info:
        if coin_symbol == req.coin_symbol.upper():
            return CoinInfoResponse(
                coin_symbol=coin_symbol,
                available_start=start_time.to_pydatetime(),
                available_end=end_time.to_pydatetime()
            )
    raise HTTPException(status_code=404, detail="Coin symbol not found.")
