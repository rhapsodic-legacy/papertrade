"""CRUD endpoints for user-created custom AI traders."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, Field

from app.services.auth import get_user_id_from_token
from app.services.supabase_client import get_supabase_admin
from app.services.ai_trader import CUSTOM_RISK_PRESETS
from app.services.rag_toolkit import RAG_MODULES

router = APIRouter()

# SQL to create the custom_traders table (run once via /setup)
CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS custom_traders (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    owner_id uuid NOT NULL REFERENCES auth.users(id),
    profile_id uuid NOT NULL REFERENCES profiles(id),
    name text NOT NULL,
    strategy_prompt text NOT NULL,
    risk_level text NOT NULL CHECK (risk_level IN ('low', 'medium', 'high')),
    asset_focus text NOT NULL CHECK (asset_focus IN ('stocks', 'crypto', 'both')),
    toolkit_modules jsonb NOT NULL DEFAULT '[]',
    is_active boolean NOT NULL DEFAULT true,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

-- RLS
ALTER TABLE custom_traders ENABLE ROW LEVEL SECURITY;

-- Allow service role full access (for pipeline)
CREATE POLICY "service_role_all" ON custom_traders
    FOR ALL TO service_role USING (true) WITH CHECK (true);

-- Allow authenticated users to read/manage their own traders
CREATE POLICY "owner_select" ON custom_traders
    FOR SELECT TO authenticated USING (owner_id = auth.uid());
CREATE POLICY "owner_insert" ON custom_traders
    FOR INSERT TO authenticated WITH CHECK (owner_id = auth.uid());
CREATE POLICY "owner_update" ON custom_traders
    FOR UPDATE TO authenticated USING (owner_id = auth.uid());
CREATE POLICY "owner_delete" ON custom_traders
    FOR DELETE TO authenticated USING (owner_id = auth.uid());
"""

VALID_MODULES = [k for k, v in RAG_MODULES.items() if not v.get("always_included")]
VALID_RISK_LEVELS = list(CUSTOM_RISK_PRESETS.keys())
VALID_ASSET_FOCUS = ["stocks", "crypto", "both"]
MAX_CUSTOM_TRADERS_PER_USER = 3
MAX_CUSTOM_TRADERS_TOTAL = 50


class CreateCustomTrader(BaseModel):
    name: str = Field(..., min_length=3, max_length=30)
    strategy_prompt: str = Field(..., min_length=10, max_length=2000)
    risk_level: str = Field(..., pattern="^(low|medium|high)$")
    asset_focus: str = Field(..., pattern="^(stocks|crypto|both)$")
    toolkit_modules: list[str] = Field(..., min_length=1, max_length=6)


class UpdateCustomTrader(BaseModel):
    name: str | None = Field(None, min_length=3, max_length=30)
    strategy_prompt: str | None = Field(None, min_length=10, max_length=2000)
    risk_level: str | None = Field(None, pattern="^(low|medium|high)$")
    asset_focus: str | None = Field(None, pattern="^(stocks|crypto|both)$")
    toolkit_modules: list[str] | None = Field(None, min_length=1, max_length=6)


def _validate_modules(modules: list[str]) -> None:
    invalid = [m for m in modules if m not in VALID_MODULES]
    if invalid:
        raise HTTPException(400, f"Invalid modules: {invalid}. Valid: {VALID_MODULES}")


@router.post("/")
async def create_custom_trader(body: CreateCustomTrader, request: Request):
    """Create a custom AI trader for the authenticated user."""
    user_id = get_user_id_from_token(request)
    _validate_modules(body.toolkit_modules)

    db = get_supabase_admin()

    # Check per-user limit
    existing = (
        db.table("custom_traders")
        .select("id")
        .eq("owner_id", user_id)
        .eq("is_active", True)
        .execute()
    )
    if len(existing.data) >= MAX_CUSTOM_TRADERS_PER_USER:
        raise HTTPException(400, f"Maximum {MAX_CUSTOM_TRADERS_PER_USER} custom traders per user")

    # Check global limit
    total = db.table("custom_traders").select("id", count="exact").eq("is_active", True).execute()
    if total.count and total.count >= MAX_CUSTOM_TRADERS_TOTAL:
        raise HTTPException(400, "Maximum custom traders reached on the platform")

    # Create a Supabase auth user for this custom AI trader
    bot_email = f"custom-{uuid.uuid4().hex[:12]}@papertrade.bot"
    display_name = f"{body.name} (Custom)"
    try:
        user_resp = db.auth.admin.create_user(
            {
                "email": bot_email,
                "password": f"custom-{uuid.uuid4().hex}-noLogin!",
                "email_confirm": True,
                "user_metadata": {"display_name": display_name},
            }
        )
        profile_id = user_resp.user.id

        # Update the auto-created profile for AI fields
        db.table("profiles").update(
            {
                "display_name": display_name,
                "is_ai": True,
                "ai_model": "custom",
            }
        ).eq("id", profile_id).execute()

    except Exception as e:
        raise HTTPException(500, f"Failed to create trader account: {e}")

    # Insert custom_traders config row
    row = {
        "owner_id": user_id,
        "profile_id": profile_id,
        "name": body.name,
        "strategy_prompt": body.strategy_prompt,
        "risk_level": body.risk_level,
        "asset_focus": body.asset_focus,
        "toolkit_modules": body.toolkit_modules,
        "is_active": True,
    }
    result = db.table("custom_traders").insert(row).execute()

    return {
        "id": result.data[0]["id"],
        "profile_id": profile_id,
        "display_name": display_name,
        "status": "created",
    }


@router.get("/")
async def list_custom_traders(request: Request):
    """List the current user's custom traders."""
    user_id = get_user_id_from_token(request)
    db = get_supabase_admin()

    traders = (
        db.table("custom_traders")
        .select("*")
        .eq("owner_id", user_id)
        .eq("is_active", True)
        .execute()
    )

    # Enrich with portfolio value from latest snapshot
    results = []
    for t in traders.data:
        profile = (
            db.table("profiles")
            .select("display_name, cash_balance")
            .eq("id", t["profile_id"])
            .single()
            .execute()
        )
        snap = (
            db.table("portfolio_snapshots")
            .select("total_value")
            .eq("user_id", t["profile_id"])
            .order("snapshot_date", desc=True)
            .limit(1)
            .execute()
        )
        total_value = snap.data[0]["total_value"] if snap.data else 100000.0

        results.append({
            **t,
            "display_name": profile.data["display_name"] if profile.data else t["name"],
            "total_value": total_value,
        })

    return {"traders": results}


@router.get("/modules")
async def get_available_modules():
    """Return the list of available data modules for custom traders."""
    return {
        "modules": [
            {
                "key": k,
                "label": v["label"],
                "description": v["description"],
                "icon": v.get("icon", ""),
                "color": v.get("color", "gray"),
            }
            for k, v in RAG_MODULES.items()
            if not v.get("always_included")
        ]
    }


@router.put("/{trader_id}")
async def update_custom_trader(trader_id: str, body: UpdateCustomTrader, request: Request):
    """Update a custom trader's configuration."""
    user_id = get_user_id_from_token(request)
    db = get_supabase_admin()

    # Verify ownership
    existing = (
        db.table("custom_traders")
        .select("*")
        .eq("id", trader_id)
        .eq("owner_id", user_id)
        .single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(404, "Custom trader not found")

    updates = {}
    if body.toolkit_modules is not None:
        _validate_modules(body.toolkit_modules)
        updates["toolkit_modules"] = body.toolkit_modules
    if body.name is not None:
        updates["name"] = body.name
    if body.strategy_prompt is not None:
        updates["strategy_prompt"] = body.strategy_prompt
    if body.risk_level is not None:
        updates["risk_level"] = body.risk_level
    if body.asset_focus is not None:
        updates["asset_focus"] = body.asset_focus

    if not updates:
        raise HTTPException(400, "No fields to update")

    db.table("custom_traders").update(updates).eq("id", trader_id).execute()

    # Update display_name on profile if name changed
    if body.name is not None:
        display_name = f"{body.name} (Custom)"
        db.table("profiles").update(
            {"display_name": display_name}
        ).eq("id", existing.data["profile_id"]).execute()

    return {"status": "updated", "id": trader_id}


@router.delete("/{trader_id}")
async def delete_custom_trader(trader_id: str, request: Request):
    """Deactivate a custom trader (preserves history)."""
    user_id = get_user_id_from_token(request)
    db = get_supabase_admin()

    existing = (
        db.table("custom_traders")
        .select("profile_id")
        .eq("id", trader_id)
        .eq("owner_id", user_id)
        .single()
        .execute()
    )
    if not existing.data:
        raise HTTPException(404, "Custom trader not found")

    # Deactivate — don't delete (preserves trade history, leaderboard data)
    db.table("custom_traders").update({"is_active": False}).eq("id", trader_id).execute()
    db.table("profiles").update({"is_ai": False}).eq("id", existing.data["profile_id"]).execute()

    return {"status": "deactivated", "id": trader_id}


@router.post("/setup")
async def setup_custom_traders_table():
    """One-time: create the custom_traders table. Idempotent."""
    db = get_supabase_admin()
    try:
        db.postgrest.rpc("exec_sql", {"query": CREATE_TABLE_SQL}).execute()
        return {"status": "ok", "message": "custom_traders table created"}
    except Exception as e:
        # Try creating via direct SQL if rpc not available
        # The table may already exist — that's fine
        return {"status": "note", "message": f"Run this SQL in Supabase dashboard: {str(e)[:200]}"}
