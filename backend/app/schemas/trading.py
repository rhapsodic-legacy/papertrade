from pydantic import BaseModel, Field
from typing import Literal
from datetime import datetime


class TradeRequest(BaseModel):
    symbol: str = Field(..., examples=["AAPL", "BTC"])
    asset_type: Literal["stock", "crypto"]
    side: Literal["buy", "sell"]
    quantity: float = Field(..., gt=0)


class TradeResponse(BaseModel):
    id: str
    symbol: str
    asset_type: str
    side: str
    quantity: float
    price: float
    total: float
    created_at: datetime


class PositionResponse(BaseModel):
    symbol: str
    asset_type: str
    quantity: float
    avg_cost_basis: float
    current_price: float | None = None
    market_value: float | None = None
    unrealized_pnl: float | None = None
    unrealized_pnl_pct: float | None = None


class PortfolioResponse(BaseModel):
    cash_balance: float
    invested_value: float
    total_value: float
    daily_pnl: float | None = None
    positions: list[PositionResponse]


class QuoteResponse(BaseModel):
    symbol: str
    asset_type: str
    price: float
    change: float | None = None
    change_pct: float | None = None
    name: str | None = None


class LeaderboardEntry(BaseModel):
    display_name: str
    total_portfolio_value: float
    cash_balance: float
    invested_value: float
    rank: int
