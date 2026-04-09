from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    finnhub_api_key: str
    gemini_api_key: str = ""
    mistral_api_key: str = ""
    mistral_api_key_2: str = ""
    mistral_api_key_3: str = ""
    cerebras_api_key: str = ""
    groq_api_key: str = ""
    fred_api_key: str = ""
    starting_balance: float = 100_000.00

    # Local LLM (Ollama) — set to enable local model offloading
    ollama_base_url: str = ""  # e.g. "http://localhost:11434" or "http://macbook-air.local:11434"
    ollama_model: str = "gemma4:26b"  # preprocessing (narrative, reflections, commentary)
    ollama_small_model: str = "gemma4:e4b"  # classification tasks (sentiment scoring)

    model_config = {"env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
