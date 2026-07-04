from supabase import create_client, Client
from app.config import settings


def get_supabase_client(use_service_role: bool = False) -> Client:
    url = settings.SUPABASE_URL
    key = (
        settings.SUPABASE_SERVICE_ROLE_KEY
        if use_service_role
        else settings.SUPABASE_KEY
    )

    if not url or not key:
        raise RuntimeError("Database configuration error")

    return create_client(
        url,
        key,
        options={
            "timeout": 5,
            "retry_limit": 1,
        },
    )


supabase_client: Client = get_supabase_client()
admin: Client = get_supabase_client(use_service_role=True)