import asyncio
from app.db.supabase import get_supabase
from app.api.routes.search import global_search

async def test():
    supabase = get_supabase()
    user_res = supabase.table("organization_users").select("user_id").limit(1).execute()
    user_id = user_res.data[0]["user_id"]
    print(f"Testing with user_id: {user_id}")
    
    res = await global_search("remotely", {"sub": user_id})
    print(f"Search results: {res}")

if __name__ == "__main__":
    asyncio.run(test())
