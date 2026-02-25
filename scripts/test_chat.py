import asyncio
from app.db.supabase import get_supabase
from app.api.routes.graphrag import semantic_search

async def test():
    supabase = get_supabase()
    user_res = supabase.table("organization_users").select("user_id").limit(1).execute()
    user_id = user_res.data[0]["user_id"]
    from app.api.routes.graphrag import get_permitted_document_ids
    
    org_res = supabase.table("organization_users").select("organization_id, role").eq("user_id", user_id).limit(1).execute()
    org_id = org_res.data[0]["organization_id"]
    role = org_res.data[0]["role"]
    print(f"Org ID: {org_id}, Role: {role}")
    allowed_ids = get_permitted_document_ids(user_id, org_id)
    print(f"Allowed IDs: {allowed_ids}")

    # Simulating the exact service call to bypass semantic_search's wrapper
    from app.services.graphrag_service import GraphRAGService
    print("Testing with full filter (work remotely):")
    res1 = GraphRAGService.search_similar_content("work remotely", org_id, 3, allowed_ids)
    print(len(res1))
    
    print("Testing with full filter (on which days can employees work remotely):")
    res2 = GraphRAGService.search_similar_content("on which days can employees work remotely", org_id, 3, allowed_ids)
    print(len(res2))

if __name__ == "__main__":
    asyncio.run(test())
