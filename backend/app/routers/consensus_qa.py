"""API endpoints for Phase 2 Consensus Quality — Factual QA domain."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, HTTPException

from app.services.supabase_client import get_supabase_admin
from app.services.consensus_qa import (
    run_evaluation,
    QA_MODELS,
    QA_STRATEGIES,
    CONSENSUS_THRESHOLD,
)

router = APIRouter()

# SQL to create tables (run once via /setup)
CREATE_TABLES_SQL = """
CREATE TABLE IF NOT EXISTS qa_rounds (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at timestamptz NOT NULL DEFAULT now(),
    dataset text NOT NULL DEFAULT 'triviaqa',
    question_count int NOT NULL DEFAULT 0,
    status text NOT NULL DEFAULT 'pending',
    summary jsonb
);

CREATE TABLE IF NOT EXISTS qa_answers (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    round_id uuid NOT NULL REFERENCES qa_rounds(id),
    question_id text NOT NULL,
    question_text text NOT NULL,
    ground_truth text NOT NULL,
    model_id text NOT NULL,
    strategy text NOT NULL,
    raw_answer text NOT NULL,
    extracted_answer text NOT NULL,
    is_correct boolean NOT NULL DEFAULT false,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_qa_answers_round ON qa_answers(round_id);
CREATE INDEX IF NOT EXISTS idx_qa_answers_question ON qa_answers(question_id);
"""


@router.post("/evaluate")
async def trigger_evaluation(
    background_tasks: BackgroundTasks,
    dataset: str = "triviaqa",
    count: int = 50,
):
    """Trigger a QA evaluation round. Runs in the background."""
    if count < 5 or count > 200:
        raise HTTPException(400, "count must be between 5 and 200")

    db = get_supabase_admin()
    row = db.table("qa_rounds").insert({
        "dataset": dataset,
        "question_count": count,
        "status": "pending",
    }).execute()

    round_id = row.data[0]["id"]
    background_tasks.add_task(run_evaluation, round_id, dataset, count)

    agents_per_question = len(QA_MODELS) * len(QA_STRATEGIES)
    return {
        "round_id": round_id,
        "status": "running",
        "questions": count,
        "agents_per_question": agents_per_question,
        "total_api_calls": count * agents_per_question,
    }


@router.get("/rounds")
async def list_rounds():
    """List all evaluation rounds."""
    db = get_supabase_admin()
    result = (
        db.table("qa_rounds")
        .select("*")
        .order("created_at", desc=True)
        .limit(20)
        .execute()
    )
    return {"rounds": result.data}


@router.get("/rounds/{round_id}")
async def get_round(round_id: str):
    """Get detailed results for a specific round."""
    db = get_supabase_admin()
    round_row = (
        db.table("qa_rounds")
        .select("*")
        .eq("id", round_id)
        .single()
        .execute()
    )
    if not round_row.data:
        raise HTTPException(404, "Round not found")

    answers = (
        db.table("qa_answers")
        .select("question_id, model_id, strategy, extracted_answer, is_correct")
        .eq("round_id", round_id)
        .execute()
    )

    return {
        "round": round_row.data,
        "answers": answers.data,
    }


@router.get("/consensus-quality")
async def get_consensus_quality(round_id: str | None = None):
    """Get consensus quality analysis for a round (or latest)."""
    db = get_supabase_admin()

    if round_id:
        row = db.table("qa_rounds").select("*").eq("id", round_id).single().execute()
    else:
        row = (
            db.table("qa_rounds")
            .select("*")
            .eq("status", "complete")
            .order("created_at", desc=True)
            .limit(1)
            .single()
            .execute()
        )

    if not row.data:
        raise HTTPException(404, "No completed rounds found")
    if row.data["status"] != "complete":
        return {"status": row.data["status"], "message": "Round still in progress"}

    return {
        "round_id": row.data["id"],
        "dataset": row.data["dataset"],
        "question_count": row.data["question_count"],
        "created_at": row.data["created_at"],
        **row.data.get("summary", {}),
    }


@router.get("/config")
async def get_config():
    """Return the experiment configuration (models, strategies, threshold)."""
    return {
        "models": [{"id": m["id"], "model_id": m["model_id"]} for m in QA_MODELS],
        "strategies": {
            k: {"label": v["label"], "description": v["description"]}
            for k, v in QA_STRATEGIES.items()
        },
        "consensus_threshold": CONSENSUS_THRESHOLD,
        "agents_per_question": len(QA_MODELS) * len(QA_STRATEGIES),
    }


@router.get("/setup")
async def setup_tables():
    """Return the SQL needed to create QA tables (run in Supabase dashboard)."""
    return {"sql": CREATE_TABLES_SQL}
