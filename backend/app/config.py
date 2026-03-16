from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    supabase_url: str
    supabase_anon_key: str
    supabase_service_role_key: str
    finnhub_api_key: str
    gemini_api_key: str = ""
    mistral_api_key: str = ""
    cerebras_api_key: str = ""
    starting_balance: float = 100_000.00

    model_config = {"env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
