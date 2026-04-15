"""Central LLM routing layer.

Routes calls to either local Ollama (Gemma) or cloud APIs (Mistral/Groq/Gemini)
based on configuration. Each pipeline stage declares its preferred tier:

  - "local"   → use Ollama if available, fall back to Mistral
  - "cloud"   → always use Mistral (for trading decisions that need max quality)
  - "local_only" → use Ollama only, skip if unavailable (for new capabilities)

Set OLLAMA_BASE_URL env var to enable local routing.
"""

from __future__ import annotations

import httpx

from app.config import get_settings


async def _call_ollama(
    model: str,
    system: str,
    user_msg: str,
    base_url: str,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> str:
    """Call a local Ollama instance (OpenAI-compatible API)."""
    url = f"{base_url}/v1/chat/completions"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    async with httpx.AsyncClient(timeout=300) as client:  # local models can be slow
        resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            raise Exception(f"Ollama {model} error {resp.status_code}: {resp.text[:300]}")
        data = resp.json()
        message = data["choices"][0]["message"]
        content = message.get("content", "")
        # Gemma 4 is a thinking model — if content is empty but reasoning exists,
        # the model spent all tokens on thinking. Return whatever we got.
        if not content and message.get("reasoning"):
            print(f"[LLM] Warning: Ollama {model} returned empty content (thinking used all tokens). Increase max_tokens.")
        return content


async def _call_mistral_api(
    model_id: str,
    system: str,
    user_msg: str,
    api_key: str,
    temperature: float = 0.3,
    max_tokens: int = 2048,
) -> str:
    """Call Mistral API with retry on disconnect."""
    import asyncio
    url = "https://api.mistral.ai/v1/chat/completions"
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_msg},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    last_err = None
    for attempt in range(3):
        try:
            async with httpx.AsyncClient(timeout=180) as client:
                resp = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                    json=payload,
                )
                if resp.status_code == 429:
                    wait = 10 * (attempt + 1)
                    print(f"[MISTRAL] {model_id} rate-limited, waiting {wait}s (attempt {attempt + 1}/3)")
                    await asyncio.sleep(wait)
                    continue
                if resp.status_code != 200:
                    raise Exception(f"Mistral {model_id} error {resp.status_code}: {resp.text[:300]}")
                data = resp.json()
                return data["choices"][0]["message"]["content"]
        except (httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ConnectTimeout) as e:
            last_err = e
            wait = 8 * (attempt + 1)
            print(f"[MISTRAL] {model_id} connection error: {type(e).__name__}, retrying in {wait}s (attempt {attempt + 1}/3)")
            await asyncio.sleep(wait)
    raise Exception(f"Mistral {model_id} failed after 3 attempts: {last_err}")


async def call_llm(
    system: str,
    user_msg: str,
    tier: str = "local",
    temperature: float = 0.3,
    max_tokens: int = 2048,
    cloud_model: str = "mistral-large-latest",
    local_model: str | None = None,
) -> str:
    """Route an LLM call based on tier preference and config.

    Parameters
    ----------
    system : str
        System prompt.
    user_msg : str
        User message.
    tier : str
        "local" — prefer Ollama, fall back to Mistral.
        "cloud" — always use Mistral.
        "local_only" — Ollama only, raise if unavailable.
    temperature : float
        Sampling temperature.
    max_tokens : int
        Max output tokens.
    cloud_model : str
        Which Mistral model to use for cloud calls.
    local_model : str | None
        Override Ollama model (defaults to config's ollama_model).
    """
    settings = get_settings()
    ollama_url = settings.ollama_base_url

    # Determine if local is available
    use_local = bool(ollama_url) and tier in ("local", "local_only")

    if use_local:
        model = local_model or settings.ollama_model
        try:
            result = await _call_ollama(
                model, system, user_msg, ollama_url, temperature, max_tokens
            )
            return result
        except Exception as e:
            if tier == "local_only":
                raise
            # Fall back to cloud
            print(f"[LLM] Ollama failed ({e}), falling back to Mistral")

    # Cloud path
    if tier == "local_only":
        raise Exception("Ollama not configured and tier=local_only")

    api_key = settings.mistral_api_key
    if not api_key:
        raise Exception("No Mistral API key and Ollama not available")

    return await _call_mistral_api(
        cloud_model, system, user_msg, api_key, temperature, max_tokens
    )


async def is_ollama_available() -> bool:
    """Check if Ollama is reachable."""
    settings = get_settings()
    if not settings.ollama_base_url:
        return False
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            return resp.status_code == 200
    except Exception:
        return False


async def get_ollama_models() -> list[str]:
    """List available models on the Ollama instance."""
    settings = get_settings()
    if not settings.ollama_base_url:
        return []
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(f"{settings.ollama_base_url}/api/tags")
            if resp.status_code != 200:
                return []
            data = resp.json()
            return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []
