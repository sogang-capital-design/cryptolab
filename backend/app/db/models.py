from sqlalchemy import Column, Integer, String, DateTime, Float, ForeignKey, UniqueConstraint, func
from sqlalchemy.orm import relationship
from datetime import datetime
from app.db.database import Base

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, index=True)           # 중복 허용
    name = Column(String, index=True)            # 로그인 구분용
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.current_timestamp(), nullable=False)

    watchlist = relationship("Watchlist", back_populates="user", cascade="all, delete-orphan")

class Watchlist(Base):
    __tablename__ = "watchlist"
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    symbol = Column(String, nullable=False, index=True)

    user = relationship("User", back_populates="watchlist")
    __table_args__ = (
        UniqueConstraint("user_id", "symbol", name="uq_user_symbol"),  # 중복 방지
    )

class OHLCV(Base):
    __tablename__ = "ohlcv"
    timeframe = Column(String(20), primary_key=True)
    symbol = Column(String(50), primary_key=True)
    timestamp = Column(DateTime, primary_key=True)
    opening_price = Column(Float, nullable=False)
    high_price = Column(Float, nullable=False)
    low_price = Column(Float, nullable=False)
    trade_price = Column(Float, nullable=False)
    candle_acc_trade_price = Column(Float, nullable=False)
    candle_acc_trade_volume = Column(Float, nullable=False)


class OHLCVRange(Base):
    __tablename__ = "ohlcv_range"
    timeframe = Column(String(20), primary_key=True)
    symbol = Column(String(50), primary_key=True)
    start_timestamp = Column(DateTime, primary_key=True)
    end_timestamp = Column(DateTime, primary_key=True)

    @property
    def as_tuple(self) -> tuple[datetime, datetime]:
        return self.start_timestamp, self.end_timestamp
