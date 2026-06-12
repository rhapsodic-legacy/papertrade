from supabase import create_client, Client
from app.config import get_settings


def get_supabase_client() -> Client:
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_anon_key)


def get_supabase_admin() -> Client:
    settings = get_settings()
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def fetch_all_rows(query, page_size: int = 1000, max_rows: int | None = None) -> list[dict]:
    """Page through a PostgREST query. Supabase caps a single .execute() at
    1000 rows and silently truncates larger result sets — any unbounded
    fetch through .execute() alone reads only the first 1000 rows."""
    rows: list[dict] = []
    start = 0
    while True:
        resp = query.range(start, start + page_size - 1).execute()
        batch = resp.data or []
        rows.extend(batch)
        if len(batch) < page_size or (max_rows and len(rows) >= max_rows):
            break
        start += page_size
    return rows[:max_rows] if max_rows else rows
