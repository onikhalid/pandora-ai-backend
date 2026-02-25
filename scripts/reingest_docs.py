
import os
import re
from app.db.supabase import get_supabase
from app.services.graphrag_service import GraphRAGService

def reingest_all():
    print("Starting re-ingestion of all published documents...")
    supabase = get_supabase()
    
    # 1. Fetch all published documents
    docs_res = supabase.table("documents").select("id, type, organization_id, domain_id").eq("status", "published").execute()
    docs = docs_res.data or []
    print(f"Found {len(docs)} published documents.")
    
    for doc in docs:
        doc_id = doc["id"]
        doc_type = (doc.get("type") or "PANDORA_DOC").upper()
        org_id = doc.get("organization_id")
        domain_id = doc.get("domain_id")
        
        # 2. Fetch the latest published version
        ver_res = supabase.table("document_versions").select("content_text, created_at").eq("document_id", doc_id).eq("status", "published").order("created_at", desc=True).limit(1).execute()
        
        if ver_res.data:
            content = ver_res.data[0]["content_text"]
            created_at = ver_res.data[0]["created_at"]
            
            # 3. Clean and Ingest
            # Strip HTML tags
            clean_text = re.sub(r'<[^>]+>', ' ', content)
            clean_text = ' '.join(clean_text.split())
            
            print(f"Ingesting {doc_id} (Type: {doc_type}, Org: {org_id}, Domain: {domain_id})...")
            # Delete existing chunks to prevent duplicates
            GraphRAGService.delete_document(doc_id)
            
            chunks = GraphRAGService.chunk_text(clean_text)
            print(f"Created {len(chunks)} chunks for {doc_id}")
            
            res = GraphRAGService.ingest_document(
                document_id=doc_id,
                content=clean_text,
                organization_id=org_id,
                source_type=doc_type,
                created_at=created_at,
                domain_id=domain_id
            )
            print(f"Ingest result: {res}")
        else:
            print(f"Skipping {doc_id}: No published version found.")

if __name__ == "__main__":
    reingest_all()
    print("Re-ingestion complete.")
