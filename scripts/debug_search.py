
import os
import asyncio
from app.services.graphrag_service import GraphRAGService
from app.api.routes.graphrag import get_permitted_document_ids
from app.db.supabase import get_supabase

async def test_search():
    # Simulate a user search
    query = "was lotto dashboard worked on last week"
    # Hardcoded test data from user request
    domain_id = "4fe92c2c-95b5-419c-a77d-6ff7ea466fe4"
    doc_type = "report"
    
    # We need a valid user_id and org_id to test permissions
    # Let's try to just test the service directly first without permission gating
    print(f"Testing GraphRAGService directly...")
    try:
        results = GraphRAGService.search_similar_content(
            query, 
            organization_id=None, # Testing with None org for now
            limit=10, 
            allowed_document_ids=None,
            source_type=doc_type.upper(),
            domain_id=domain_id
        )
        print(f"Results: {results}")
    except Exception as e:
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(test_search())
