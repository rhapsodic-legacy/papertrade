"""Consensus Quality Engine — Phase 2: Factual QA Domain.

Tests whether multi-model consensus predicts better outcomes in factual QA,
reusing the diversity scoring from the PaperTrade convergence engine.

3 Mistral models × 4 prompting strategies = 12 agents per question.
Consensus = 2+ agents give the same normalized answer.
Outcome = correct/incorrect vs known ground truth.
"""

from __future__ import annotations

import asyncio
import re
import uuid
from collections import defaultdict

import httpx

from app.config import get_settings
from app.services.supabase_client import get_supabase_admin
from app.services.analytics import _compute_module_diversity, _compute_reasoning_overlap

# ---------------------------------------------------------------------------
# Models: 3 distinct Mistral models (Large and Large 2 share model_id)
# ---------------------------------------------------------------------------

QA_MODELS = [
    {
        "id": "mistral-small",
        "model_id": "mistral-small-latest",
        "api_key_field": "mistral_api_key_2",
    },
    {
        "id": "mistral-medium",
        "model_id": "mistral-medium-latest",
        "api_key_field": "mistral_api_key",
    },
    {
        "id": "mistral-large",
        "model_id": "mistral-large-latest",
        "api_key_field": "mistral_api_key",
    },
]

# ---------------------------------------------------------------------------
# Prompting strategy "modules" (analogous to RAG_MODULES in PaperTrade)
# ---------------------------------------------------------------------------

QA_STRATEGIES: dict[str, dict] = {
    "bare": {
        "label": "Direct Answer",
        "description": "No scaffolding. Just the question.",
        "system": "Answer the following question. Give only the answer, nothing else.",
        "user_template": "{question}",
    },
    "cot": {
        "label": "Chain of Thought",
        "description": "Step-by-step reasoning before answering.",
        "system": (
            "Answer the following question. Think step by step, "
            "then give your final answer on the last line prefixed with 'ANSWER:'."
        ),
        "user_template": "{question}",
    },
    "few_shot": {
        "label": "Few-Shot Examples",
        "description": "3 worked examples before the question.",
        "system": "Answer the following question. Give only the answer, nothing else.",
        "user_template": (
            "Q: What is the capital of France?\nA: Paris\n\n"
            "Q: Who wrote Romeo and Juliet?\nA: William Shakespeare\n\n"
            "Q: What is the chemical symbol for gold?\nA: Au\n\n"
            "Q: {question}\nA:"
        ),
    },
    "rag": {
        "label": "Retrieval-Augmented",
        "description": "Wikipedia snippet prepended as context.",
        "system": (
            "Use the provided context to answer the question. "
            "Give only the answer, nothing else."
        ),
        "user_template": "Context: {context}\n\nQuestion: {question}",
    },
}

CONSENSUS_THRESHOLD = 2  # fewer agents (12) than PaperTrade (20), so lower threshold


# ---------------------------------------------------------------------------
# Mistral API caller (standalone copy to avoid coupling with ai_trader)
# ---------------------------------------------------------------------------

async def _call_mistral(model_id: str, system: str, user_msg: str, api_key: str) -> str:
    url = "https://api.mistral.ai/v1/chat/completions"
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "temperature": 0.3,  # lower than trading — want more deterministic answers
        "max_tokens": 512,
    }
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json=payload,
        )
        if resp.status_code != 200:
            raise Exception(f"Mistral {model_id} error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        return data["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Question loading (HuggingFace datasets API — no pip install needed)
# ---------------------------------------------------------------------------

async def load_questions(dataset: str = "triviaqa", count: int = 50, offset: int = 0) -> list[dict]:
    """Fetch questions from HuggingFace datasets server."""
    url = "https://datasets-server.huggingface.co/rows"
    params = {
        "dataset": "trivia_qa",
        "config": "rc.nocontext",
        "split": "validation",
        "offset": offset,
        "length": count,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(url, params=params)
        if resp.status_code != 200:
            raise Exception(f"HuggingFace API error {resp.status_code}: {resp.text[:200]}")
        data = resp.json()

    questions = []
    for row_data in data.get("rows", []):
        row = row_data.get("row", {})
        answer_obj = row.get("answer", {})
        questions.append({
            "question_id": row.get("question_id", str(uuid.uuid4())),
            "question": row.get("question", ""),
            "ground_truth": answer_obj.get("value", ""),
            "aliases": answer_obj.get("aliases", []),
        })
    return questions


# ---------------------------------------------------------------------------
# Wikipedia context fetcher (for RAG strategy)
# ---------------------------------------------------------------------------

async def _fetch_wikipedia_context(question: str) -> str:
    """Fetch a Wikipedia intro paragraph relevant to the question."""
    # Extract likely topic: use first noun-phrase-ish chunk or full question
    search_term = question.rstrip("?").strip()
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            # Search for relevant article
            resp = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "list": "search",
                    "srsearch": search_term,
                    "srlimit": 1,
                    "format": "json",
                },
            )
            if resp.status_code != 200:
                return ""
            results = resp.json().get("query", {}).get("search", [])
            if not results:
                return ""

            title = results[0]["title"]

            # Get intro extract
            resp2 = await client.get(
                "https://en.wikipedia.org/w/api.php",
                params={
                    "action": "query",
                    "prop": "extracts",
                    "exintro": True,
                    "explaintext": True,
                    "titles": title,
                    "format": "json",
                },
            )
            if resp2.status_code != 200:
                return ""
            pages = resp2.json().get("query", {}).get("pages", {})
            for page in pages.values():
                extract = page.get("extract", "")
                # Truncate to ~500 chars to keep prompt lean
                return extract[:500] if extract else ""
    except Exception:
        return ""
    return ""


# ---------------------------------------------------------------------------
# Answer extraction and normalization
# ---------------------------------------------------------------------------

def _extract_answer(raw: str, strategy: str) -> str:
    """Extract the final answer from model output."""
    if strategy == "cot":
        # Look for "ANSWER:" prefix
        for line in reversed(raw.strip().split("\n")):
            line = line.strip()
            if line.upper().startswith("ANSWER:"):
                return line[7:].strip()
        # Fallback: last non-empty line
        lines = [l.strip() for l in raw.strip().split("\n") if l.strip()]
        return lines[-1] if lines else raw.strip()
    return raw.strip()


def _normalize_answer(text: str) -> str:
    """Normalize answer for comparison: lowercase, strip articles/punctuation."""
    text = text.lower().strip()
    # Remove common articles
    text = re.sub(r"^(the|a|an)\s+", "", text)
    # Remove punctuation
    text = re.sub(r"[^\w\s]", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _check_correctness(extracted: str, ground_truth: str, aliases: list[str]) -> bool:
    """Check if extracted answer matches ground truth or any alias."""
    norm_extracted = _normalize_answer(extracted)
    if not norm_extracted:
        return False

    candidates = [ground_truth] + aliases
    for candidate in candidates:
        norm_candidate = _normalize_answer(candidate)
        if not norm_candidate:
            continue
        # Exact match
        if norm_extracted == norm_candidate:
            return True
        # Substring match (either direction)
        if norm_extracted in norm_candidate or norm_candidate in norm_extracted:
            return True
    return False


# ---------------------------------------------------------------------------
# Core evaluation runner
# ---------------------------------------------------------------------------

async def run_evaluation(round_id: str, dataset: str, count: int) -> dict:
    """Run a full evaluation round: load questions, query all agents, score results."""
    db = get_supabase_admin()
    settings = get_settings()

    try:
        # Load questions
        questions = await load_questions(dataset, count)
        if not questions:
            db.table("qa_rounds").update({"status": "failed", "summary": {"error": "No questions loaded"}}).eq("id", round_id).execute()
            return {"error": "No questions loaded"}

        db.table("qa_rounds").update({"question_count": len(questions), "status": "running"}).eq("id", round_id).execute()

        # Rate limiter: cap concurrent Mistral calls
        semaphore = asyncio.Semaphore(5)
        all_answers = []

        async def _query_agent(question: dict, model: dict, strategy_key: str):
            strategy = QA_STRATEGIES[strategy_key]
            api_key = getattr(settings, model["api_key_field"], "")
            if not api_key:
                return None

            # Build prompt
            if strategy_key == "rag":
                context = await _fetch_wikipedia_context(question["question"])
                user_msg = strategy["user_template"].format(
                    question=question["question"], context=context or "No context available."
                )
            else:
                user_msg = strategy["user_template"].format(question=question["question"])

            async with semaphore:
                try:
                    raw = await _call_mistral(
                        model["model_id"], strategy["system"], user_msg, api_key
                    )
                except Exception as e:
                    print(f"[QA] {model['id']}/{strategy_key} failed on Q:{question['question_id'][:8]}: {e}")
                    return None

            extracted = _extract_answer(raw, strategy_key)
            is_correct = _check_correctness(extracted, question["ground_truth"], question["aliases"])

            row = {
                "round_id": round_id,
                "question_id": question["question_id"],
                "question_text": question["question"],
                "ground_truth": question["ground_truth"],
                "model_id": model["id"],
                "strategy": strategy_key,
                "raw_answer": raw[:2000],
                "extracted_answer": extracted[:500],
                "is_correct": is_correct,
            }
            return row

        # Run all agents across all questions
        tasks = []
        for q in questions:
            for model in QA_MODELS:
                for strategy_key in QA_STRATEGIES:
                    tasks.append(_query_agent(q, model, strategy_key))

        results = await asyncio.gather(*tasks)
        all_answers = [r for r in results if r is not None]

        # Batch insert answers
        if all_answers:
            # Insert in chunks to avoid payload limits
            chunk_size = 100
            for i in range(0, len(all_answers), chunk_size):
                chunk = all_answers[i : i + chunk_size]
                db.table("qa_answers").insert(chunk).execute()

        # Compute consensus analysis
        summary = _compute_consensus_quality(all_answers)
        summary["total_answers"] = len(all_answers)
        summary["total_questions"] = len(questions)

        db.table("qa_rounds").update({"status": "complete", "summary": summary}).eq("id", round_id).execute()
        print(f"[QA] Round {round_id[:8]} complete: {len(all_answers)} answers, {len(questions)} questions")
        return summary

    except Exception as e:
        print(f"[QA] Round {round_id[:8]} failed: {e}")
        db.table("qa_rounds").update({"status": "failed", "summary": {"error": str(e)[:500]}}).eq("id", round_id).execute()
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Consensus quality computation (mirrors get_convergence_quality from analytics.py)
# ---------------------------------------------------------------------------

def _compute_consensus_quality(answers: list[dict]) -> dict:
    """Analyze consensus vs independent accuracy across all answers.

    Groups answers by question, finds consensus clusters (2+ agents same answer),
    then compares consensus accuracy vs independent accuracy.
    """
    if not answers:
        return {"verdict": "insufficient_data"}

    # Group by question
    by_question: dict[str, list[dict]] = defaultdict(list)
    for a in answers:
        by_question[a["question_id"]].append(a)

    consensus_correct = 0
    consensus_total = 0
    independent_correct = 0
    independent_total = 0
    cluster_details = []

    # Strategy and model breakdowns
    by_strategy: dict[str, dict] = defaultdict(lambda: {"correct": 0, "total": 0})
    by_model: dict[str, dict] = defaultdict(lambda: {"correct": 0, "total": 0})

    # Diversity analysis
    diversity_buckets: dict[str, dict] = defaultdict(lambda: {"correct": 0, "total": 0})

    for qid, q_answers in by_question.items():
        # Track per-strategy and per-model stats
        for a in q_answers:
            by_strategy[a["strategy"]]["total"] += 1
            by_strategy[a["strategy"]]["correct"] += int(a["is_correct"])
            by_model[a["model_id"]]["total"] += 1
            by_model[a["model_id"]]["correct"] += int(a["is_correct"])

        # Cluster by normalized answer
        clusters: dict[str, list[dict]] = defaultdict(list)
        for a in q_answers:
            norm = _normalize_answer(a["extracted_answer"])
            clusters[norm].append(a)

        for norm_answer, cluster in clusters.items():
            if len(cluster) >= CONSENSUS_THRESHOLD:
                # Consensus cluster
                is_correct = cluster[0]["is_correct"]  # all share same normalized answer
                consensus_correct += len(cluster) if is_correct else 0
                consensus_total += len(cluster)

                # Compute diversity using [model_id, strategy] as module lists
                module_lists = [[a["model_id"], a["strategy"]] for a in cluster]
                diversity = _compute_module_diversity(module_lists)

                # Reasoning overlap
                reasoning_texts = [a["raw_answer"] for a in cluster]
                reasoning_overlap = _compute_reasoning_overlap(reasoning_texts)

                diversity_class = diversity["classification"]
                diversity_buckets[diversity_class]["total"] += 1
                diversity_buckets[diversity_class]["correct"] += int(is_correct)

                cluster_details.append({
                    "question_id": qid,
                    "question": cluster[0]["question_text"][:100],
                    "consensus_answer": cluster[0]["extracted_answer"][:100],
                    "ground_truth": cluster[0]["ground_truth"],
                    "is_correct": is_correct,
                    "agent_count": len(cluster),
                    "agents": [f"{a['model_id']}/{a['strategy']}" for a in cluster],
                    "diversity": diversity,
                    "reasoning_overlap": reasoning_overlap,
                })
            else:
                # Independent (non-consensus)
                for a in cluster:
                    independent_correct += int(a["is_correct"])
                    independent_total += 1

    # Compute accuracy rates
    consensus_accuracy = round(consensus_correct / max(consensus_total, 1) * 100, 1)
    independent_accuracy = round(independent_correct / max(independent_total, 1) * 100, 1)

    # Verdict
    if consensus_total < 10 or independent_total < 10:
        verdict = "insufficient_data"
    elif consensus_accuracy > independent_accuracy + 2:
        verdict = "consensus_outperforms"
    elif independent_accuracy > consensus_accuracy + 2:
        verdict = "independent_outperforms"
    else:
        verdict = "no_significant_difference"

    # Format breakdowns
    strategy_summary = {
        k: {"accuracy": round(v["correct"] / max(v["total"], 1) * 100, 1), **v}
        for k, v in by_strategy.items()
    }
    model_summary = {
        k: {"accuracy": round(v["correct"] / max(v["total"], 1) * 100, 1), **v}
        for k, v in by_model.items()
    }
    diversity_summary = {
        k: {"accuracy": round(v["correct"] / max(v["total"], 1) * 100, 1), **v}
        for k, v in diversity_buckets.items()
    }

    return {
        "consensus": {
            "total": consensus_total,
            "correct": consensus_correct,
            "accuracy": consensus_accuracy,
        },
        "independent": {
            "total": independent_total,
            "correct": independent_correct,
            "accuracy": independent_accuracy,
        },
        "verdict": verdict,
        "by_strategy": strategy_summary,
        "by_model": model_summary,
        "diversity_analysis": diversity_summary,
        "top_clusters": sorted(cluster_details, key=lambda c: c["agent_count"], reverse=True)[:20],
    }
