from supabase import create_client, Client
from app.core.config import settings
from functools import lru_cache

@lru_cache
def get_supabase() -> Client:
    """
    Returns a configured Supabase Python client using the Service Role Key or Anon Key.
    This client is used by FastAPI for backend database operations (bypassing RLS if using Service Key,
    which is standard for server-to-server operations).
    """
    # Fallback to empty strings if not configured to prevent startup crashes when keys are missing.
    url = settings.SUPABASE_URL if settings.SUPABASE_URL else "https://placeholder.supabase.co"
    key = settings.SUPABASE_KEY if settings.SUPABASE_KEY else "placeholder-key"
    
    return create_client(url, key)
