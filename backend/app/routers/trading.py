from fastapi import APIRouter, Request

from app.schemas.trading import TradeRequest
from app.services.auth import get_user_id_from_token
from app.services.trading import execute_trade

router = APIRouter()


@router.post("/trade")
async def place_trade(request: Request, trade: TradeRequest):
    user_id = get_user_id_from_token(request)
    result = await execute_trade(
        user_id=user_id,
        symbol=trade.symbol.upper(),
        asset_type=trade.asset_type,
        side=trade.side,
        quantity=trade.quantity,
    )
    return result
