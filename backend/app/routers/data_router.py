from fastapi import APIRouter, HTTPException

from app.schemas.data_schema import (
    CoinInfoRequest,
    CoinInfoResponse,
    CoinListResponse,
    OHLCVRequest,
    OHLCVResponse,
    OHLCVDataPoint
)
from app.utils.data_utils import get_all_data_info, fetch_binance_klines
from app.utils.cache_utils import cache_response

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

@router.post("/ohlcv", response_model=OHLCVResponse)
@cache_response(prefix="ohlcv")
async def get_ohlcv(req: OHLCVRequest) -> OHLCVResponse:
    """Fetch OHLCV data from Binance API"""
    try:
        from datetime import timezone

        coin_symbol = req.coin_symbol.upper()
        symbol = f"{coin_symbol}USDT"

        # Ensure datetime objects are timezone-aware (UTC)
        start_time = req.start_time
        end_time = req.end_time

        if start_time.tzinfo is None:
            start_time = start_time.replace(tzinfo=timezone.utc)
        if end_time.tzinfo is None:
            end_time = end_time.replace(tzinfo=timezone.utc)

        df = fetch_binance_klines(
            symbol=symbol,
            start_dt_utc=start_time,
            end_dt_utc=end_time,
            interval=req.interval
        )

        if df.empty:
            raise HTTPException(
                status_code=404,
                detail=f"No OHLCV data found for {coin_symbol} in the specified time range"
            )

        # Convert DataFrame to list of OHLCVDataPoint
        data_points = []
        for timestamp, row in df.iterrows():
            data_points.append(
                OHLCVDataPoint(
                    datetime_utc=timestamp.to_pydatetime(),
                    open=float(row['open']),
                    high=float(row['high']),
                    low=float(row['low']),
                    close=float(row['close']),
                    volume=float(row['volume']),
                    trade_count=int(row['trade_count']),
                    price=float(row['price'])
                )
            )

        return OHLCVResponse(
            coin_symbol=coin_symbol,
            interval=req.interval,
            data=data_points
        )

    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch OHLCV data: {str(e)}")
