"""API endpoints for the Historical Replay Simulator."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException
from pydantic import BaseModel, Field

from app.services.supabase_client import get_supabase_admin
from app.services.simulator import run_simulation
from app.services.ai_trader import MODELS, PERSONALITIES

router = APIRouter()

# SQL to create tables (run once via /setup)
CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS sim_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at timestamptz NOT NULL DEFAULT now(),
    name text,
    start_date date NOT NULL,
    end_date date NOT NULL,
    trader_count int NOT NULL DEFAULT 0,
    overrides jsonb,
    status text NOT NULL DEFAULT 'pending',
    summary jsonb
);

CREATE TABLE IF NOT EXISTS sim_trades (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES sim_runs(id),
    trader_label text NOT NULL,
    sim_date date NOT NULL,
    symbol text NOT NULL,
    asset_type text NOT NULL,
    side text NOT NULL,
    quantity numeric(18,8) NOT NULL,
    price numeric(18,8) NOT NULL,
    total numeric(18,8) NOT NULL,
    reasoning text,
    modules_used text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS sim_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id uuid NOT NULL REFERENCES sim_runs(id),
    trader_label text NOT NULL,
    sim_date date NOT NULL,
    total_value numeric(18,2) NOT NULL,
    cash_balance numeric(18,2) NOT NULL,
    invested_value numeric(18,2) NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_sim_trades_run ON sim_trades(run_id);
CREATE INDEX IF NOT EXISTS idx_sim_snapshots_run ON sim_snapshots(run_id);
CREATE INDEX IF NOT EXISTS idx_sim_snapshots_run_date ON sim_snapshots(run_id, sim_date);
"""


class SimulationRequest(BaseModel):
    name: str | None = Field(None, max_length=100)
    start_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    end_date: str = Field(..., pattern=r"^\d{4}-\d{2}-\d{2}$")
    traders: list[dict] | None = Field(
        None,
        description="List of {personality_key, model_key, label}. Omit for all 20 AI traders.",
    )
    overrides: dict | None = Field(
        None,
        description=(
            "A/B test overrides: toolkit (list[dict]), risk_params (dict), "
            "temperature (float), system_prompt_append (str)"
        ),
    )


@router.post("/run")
async def trigger_simulation(body: SimulationRequest, background_tasks: BackgroundTasks):
    """Start a historical replay simulation. Runs in the background."""
    db = get_supabase_admin()

    # Validate date range has stored briefs
    briefs = (
        db.table("market_briefs")
        .select("brief_date", count="exact")
        .gte("brief_date", body.start_date)
        .lte("brief_date", body.end_date)
        .execute()
    )
    if not briefs.count or briefs.count == 0:
        raise HTTPException(400, f"No market briefs found for {body.start_date} to {body.end_date}")

    # Build trader configs
    trader_configs = body.traders or []
    if not trader_configs:
        trader_configs = [
            {
                "personality_key": pkey,
                "model_key": mkey,
                "label": f"{pinfo['name']} ({minfo['label']})",
            }
            for pkey, pinfo in PERSONALITIES.items()
            for mkey, minfo in MODELS.items()
        ]

    # Validate trader configs
    for tc in trader_configs:
        if tc.get("personality_key") not in PERSONALITIES:
            raise HTTPException(400, f"Unknown personality: {tc.get('personality_key')}")
        if tc.get("model_key") not in MODELS:
            raise HTTPException(400, f"Unknown model: {tc.get('model_key')}")
        if "label" not in tc:
            pname = PERSONALITIES[tc["personality_key"]]["name"]
            mlabel = MODELS[tc["model_key"]]["label"]
            tc["label"] = f"{pname} ({mlabel})"

    row = db.table("sim_runs").insert({
        "name": body.name or f"Sim {body.start_date} to {body.end_date}",
        "start_date": body.start_date,
        "end_date": body.end_date,
        "trader_count": len(trader_configs),
        "overrides": body.overrides,
        "status": "pending",
    }).execute()

    run_id = row.data[0]["id"]
    background_tasks.add_task(
        run_simulation, run_id, body.start_date, body.end_date, trader_configs, body.overrides
    )

    # Estimate API calls
    api_calls = len(trader_configs) * briefs.count

    return {
        "run_id": run_id,
        "status": "running",
        "days": briefs.count,
        "traders": len(trader_configs),
        "estimated_api_calls": api_calls,
        "estimated_minutes": round(api_calls * 3 / 60, 1),  # ~3s per call
    }


@router.get("/runs")
async def list_runs():
    """List all simulation runs."""
    db = get_supabase_admin()
    result = (
        db.table("sim_runs")
        .select("id, created_at, name, start_date, end_date, trader_count, status, overrides")
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    return {"runs": result.data}


@router.get("/runs/{run_id}")
async def get_run(run_id: str):
    """Get full results for a simulation run."""
    db = get_supabase_admin()
    run_row = db.table("sim_runs").select("*").eq("id", run_id).single().execute()
    if not run_row.data:
        raise HTTPException(404, "Simulation run not found")
    return run_row.data


@router.get("/runs/{run_id}/snapshots")
async def get_run_snapshots(run_id: str, trader: str | None = None):
    """Get daily portfolio snapshots for a simulation run (equity curves)."""
    db = get_supabase_admin()
    query = (
        db.table("sim_snapshots")
        .select("trader_label, sim_date, total_value, cash_balance, invested_value")
        .eq("run_id", run_id)
        .order("sim_date")
    )
    if trader:
        query = query.eq("trader_label", trader)
    result = query.execute()
    return {"snapshots": result.data}


@router.get("/runs/{run_id}/trades")
async def get_run_trades(run_id: str, trader: str | None = None):
    """Get all trades from a simulation run."""
    db = get_supabase_admin()
    query = (
        db.table("sim_trades")
        .select("*")
        .eq("run_id", run_id)
        .order("sim_date")
    )
    if trader:
        query = query.eq("trader_label", trader)
    result = query.execute()
    return {"trades": result.data}


@router.get("/runs/{run_id}/compare")
async def compare_to_production(run_id: str):
    """Compare simulation results to actual production performance over the same period."""
    db = get_supabase_admin()

    run_row = db.table("sim_runs").select("*").eq("id", run_id).single().execute()
    if not run_row.data:
        raise HTTPException(404, "Run not found")
    if run_row.data["status"] != "complete":
        raise HTTPException(400, "Simulation not complete yet")

    start = run_row.data["start_date"]
    end = run_row.data["end_date"]
    sim_summary = run_row.data.get("summary", {})

    # Get production snapshots for the same period
    prod_snapshots = (
        db.table("portfolio_snapshots")
        .select("user_id, snapshot_date, total_value")
        .gte("snapshot_date", start)
        .lte("snapshot_date", end)
        .order("snapshot_date")
        .execute()
    )

    # Get AI profile names
    ai_profiles = (
        db.table("profiles")
        .select("id, display_name")
        .eq("is_ai", True)
        .execute()
    )
    profile_map = {p["id"]: p["display_name"] for p in ai_profiles.data}

    # Compute production returns per trader
    prod_returns = {}
    for snap in prod_snapshots.data:
        name = profile_map.get(snap["user_id"])
        if not name:
            continue
        if name not in prod_returns:
            prod_returns[name] = {"first": snap["total_value"], "last": snap["total_value"]}
        prod_returns[name]["last"] = snap["total_value"]

    prod_results = []
    for name, vals in prod_returns.items():
        first = float(vals["first"])
        last = float(vals["last"])
        ret = round((last / first - 1) * 100, 2) if first > 0 else 0
        prod_results.append({"trader": name, "return_pct": ret, "final_value": last})

    return {
        "period": f"{start} to {end}",
        "simulation": {
            "overrides": run_row.data.get("overrides"),
            "avg_return_pct": sim_summary.get("avg_return_pct"),
            "results": sim_summary.get("results", []),
        },
        "production": {
            "avg_return_pct": round(
                sum(r["return_pct"] for r in prod_results) / max(len(prod_results), 1), 2
            ),
            "results": prod_results,
        },
    }


@router.get("/available-dates")
async def get_available_dates():
    """Return the date range of stored market briefs (available for simulation)."""
    db = get_supabase_admin()
    result = (
        db.table("market_briefs")
        .select("brief_date")
        .order("brief_date")
        .execute()
    )
    dates = [r["brief_date"] for r in result.data]
    return {
        "dates": dates,
        "count": len(dates),
        "earliest": dates[0] if dates else None,
        "latest": dates[-1] if dates else None,
    }


@router.get("/config")
async def get_sim_config():
    """Return available personalities and models for simulation."""
    return {
        "personalities": {
            k: {"name": v["name"], "toolkit_modules": [t["module"] for t in v.get("toolkit", [])]}
            for k, v in PERSONALITIES.items()
        },
        "models": {
            k: {"label": v["label"], "model_id": v["model_id"]}
            for k, v in MODELS.items()
        },
    }


@router.get("/local-llm")
async def check_local_llm():
    """Check if local Ollama instance is available and list models."""
    from app.services.llm import is_ollama_available, get_ollama_models
    from app.config import get_settings

    settings = get_settings()
    available = await is_ollama_available()
    models = await get_ollama_models() if available else []

    return {
        "configured": bool(settings.ollama_base_url),
        "base_url": settings.ollama_base_url or None,
        "available": available,
        "models": models,
        "default_model": settings.ollama_model,
        "small_model": settings.ollama_small_model,
    }


@router.get("/setup")
async def setup_tables():
    """Return the SQL needed to create simulator tables (run in Supabase dashboard)."""
    return {"sql": CREATE_TABLES_SQL}
