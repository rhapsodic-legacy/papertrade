from fastapi import APIRouter, Request
from pydantic import BaseModel

from app.services.auth import get_user_id_from_token
from app.services.notifications import (
    get_user_notifications,
    get_unread_count,
    mark_read,
    mark_all_read,
    get_alert_rules,
    create_alert_rule,
    update_alert_rule,
    delete_alert_rule,
)

router = APIRouter()


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------

@router.get("/")
async def list_notifications(request: Request, limit: int = 50, unread_only: bool = False):
    user_id = get_user_id_from_token(request)
    notifications = get_user_notifications(user_id, limit=limit, unread_only=unread_only)
    unread = get_unread_count(user_id)
    return {"notifications": notifications, "unread_count": unread}


@router.get("/unread-count")
async def unread_count(request: Request):
    user_id = get_user_id_from_token(request)
    return {"unread_count": get_unread_count(user_id)}


class MarkReadRequest(BaseModel):
    notification_ids: list[str]


@router.post("/mark-read")
async def mark_notifications_read(request: Request, body: MarkReadRequest):
    user_id = get_user_id_from_token(request)
    count = mark_read(user_id, body.notification_ids)
    return {"marked": count}


@router.post("/mark-all-read")
async def mark_all_notifications_read(request: Request):
    user_id = get_user_id_from_token(request)
    count = mark_all_read(user_id)
    return {"marked": count}


# ---------------------------------------------------------------------------
# Alert Rules
# ---------------------------------------------------------------------------

@router.get("/alerts")
async def list_alerts(request: Request):
    user_id = get_user_id_from_token(request)
    rules = get_alert_rules(user_id)
    return {"rules": rules}


class CreateAlertRequest(BaseModel):
    type: str  # price_above, price_below, ai_follow, portfolio_pnl
    config: dict


@router.post("/alerts")
async def create_alert(request: Request, body: CreateAlertRequest):
    user_id = get_user_id_from_token(request)

    # Validate alert type
    valid_types = {"price_above", "price_below", "ai_follow", "portfolio_pnl"}
    if body.type not in valid_types:
        from fastapi import HTTPException
        raise HTTPException(400, f"Invalid alert type. Must be one of: {', '.join(valid_types)}")

    rule = create_alert_rule(user_id, body.type, body.config)
    if not rule:
        from fastapi import HTTPException
        raise HTTPException(500, "Failed to create alert rule")
    return rule


class UpdateAlertRequest(BaseModel):
    active: bool | None = None
    config: dict | None = None


@router.patch("/alerts/{rule_id}")
async def update_alert(request: Request, rule_id: str, body: UpdateAlertRequest):
    user_id = get_user_id_from_token(request)
    updates = {}
    if body.active is not None:
        updates["active"] = body.active
    if body.config is not None:
        updates["config"] = body.config
    if not updates:
        return {"message": "No updates provided"}
    rule = update_alert_rule(user_id, rule_id, updates)
    return rule or {"message": "Not found or no changes"}


@router.delete("/alerts/{rule_id}")
async def remove_alert(request: Request, rule_id: str):
    user_id = get_user_id_from_token(request)
    success = delete_alert_rule(user_id, rule_id)
    if not success:
        from fastapi import HTTPException
        raise HTTPException(404, "Alert rule not found")
    return {"message": "Deleted"}
