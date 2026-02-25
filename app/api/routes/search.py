from fastapi import APIRouter
from app.core.security import CurrentUser
from app.db.supabase import get_supabase
from app.services.graphrag_service import GraphRAGService

router = APIRouter()

@router.get("/")
async def global_search(q: str, user: CurrentUser):
    supabase = get_supabase()
    user_id = user.get("sub")
    
    org_check = supabase.table("organization_users").select("organization_id, role, domain_ids").eq("user_id", user_id).limit(1).execute()
    org_id = org_check.data[0].get("organization_id") if org_check.data else None
    role = org_check.data[0].get("role") if org_check.data else "member"
    user_domains = (org_check.data[0].get("domain_ids") or []) if org_check.data else []

    # --- Projects ---
    visible_projects = []
    if org_id:
        projects_res = supabase.table("projects").select("id, name, description, is_public").eq("organization_id", org_id).ilike("name", f"%{q}%").execute()
        all_projs = projects_res.data or []

        if role in ["super_admin", "admin"]:
            visible_projects = all_projs
        else:
            project_ids = [p["id"] for p in all_projs]
            pd_map = {}
            if project_ids:
                try:
                    pd_res = supabase.table("project_domains").select("project_id, domain_id").in_("project_id", project_ids).execute()
                    for pd in (pd_res.data or []):
                        pd_map.setdefault(pd["project_id"], []).append(pd["domain_id"])
                except Exception:
                    pass
            for p in all_projs:
                p_domains = pd_map.get(p["id"], [])
                if p.get("is_public") or any(d in user_domains for d in p_domains):
                    visible_projects.append(p)

    from app.api.routes.graphrag import get_permitted_document_ids
    
    # Use centralized permissions
    allowed_ids = get_permitted_document_ids(user_id, org_id)

    # Weaviate snippets are filtered natively by IDs
    weaviate_allowed = allowed_ids

    # Search for matching titles inside the permitted docs list
    all_doc_ids_seen: set = set()
    visible_docs = []

    if allowed_ids:
        # Fetch the metadata for permitted IDs to do title matching
        # Chunking if allowed_ids is large, or use in_ filter
        docs_resp = supabase.table("documents").select("id, title, type, status, is_public, is_public_to_org").in_("id", allowed_ids).execute()
        for d in (docs_resp.data or []):
            if d["id"] not in all_doc_ids_seen and q.lower() in d.get("title", "").lower():
                all_doc_ids_seen.add(d["id"])
                visible_docs.append(d)

    snippets = []
    try:
        kb_results = GraphRAGService.search_similar_content(
            q,
            organization_id=org_id or "sandbox",
            limit=5,
            allowed_document_ids=weaviate_allowed
        )
        # Batch-fetch titles and types for all snippet document IDs
        snippet_doc_ids = list({r["document_id"] for r in kb_results if r.get("document_id")})
        doc_info_map = {}
        for did in snippet_doc_ids:
            try:
                t_resp = supabase.table("documents").select("id, title, type").eq("id", did).single().execute()
                if t_resp.data:
                    doc_info_map[did] = {
                        "title": t_resp.data.get("title", did),
                        "type": t_resp.data.get("type", "regular")
                    }
            except Exception:
                doc_info_map[did] = {"title": did, "type": "regular"}

        for r in kb_results:
            if r.get("document_id") and r.get("content"):
                doc_info = doc_info_map.get(r["document_id"], {"title": r["document_id"], "type": "regular"})
                snippets.append({
                    "document_id": r["document_id"],
                    "document_title": doc_info["title"],
                    "document_type": doc_info["type"],
                    "content": r["content"],
                    "certainty": r.get("certainty", 0)
                })
    except Exception as e:
        print(f"Error fetching snippets from Weaviate: {e}")
    
    return {
        "projects": visible_projects,
        "documents": visible_docs,
        "snippets": snippets
    }
