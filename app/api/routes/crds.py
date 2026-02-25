from fastapi import APIRouter
from pydantic import BaseModel
from app.core.security import CurrentUser
from app.db.supabase import get_supabase

from typing import Optional
from app.services.graphrag_service import GraphRAGService
import re

router = APIRouter()

class CRDApproval(BaseModel):
    status: str # 'approved' or 'rejected'
    ai_reasoning_override: Optional[str] = None

@router.get("/")
async def list_pending_crds(user: CurrentUser):
    """
    Fetches all CRDs with status='pending' that belong to documents owned by members of the same org.
    Documents may have organization_id=null (sandbox origin) so we resolve via owner's org membership.
    """
    supabase = get_supabase()
    user_id = user.get("sub")
    
    org_check = supabase.table("organization_users").select("organization_id, role").eq("user_id", user_id).limit(1).execute()
    if not org_check.data or len(org_check.data) == 0:
        return {"message": "Pending CRDs", "crds": []}
        
    org_id = org_check.data[0].get("organization_id")
    role = org_check.data[0].get("role")
    
    # Only Admins and SuperAdmins should see the pending queue
    if role not in ["admin", "super_admin"]:
        return {"message": "Pending CRDs", "crds": []}

    # Get all user_ids in this org
    org_members_resp = supabase.table("organization_users").select("user_id").eq("organization_id", org_id).execute()
    org_member_ids = [m["user_id"] for m in (org_members_resp.data or [])]

    # Fetch all pending CRDs with document title info (no inner join filter on organization_id)
    response = supabase.table("crds").select("*, documents(title, type, organization_id, owner_id)").eq("status", "pending").order("created_at", desc=True).execute()
    all_crds = getattr(response, 'data', [])
    
    # Keep only CRDs whose doc is org-owned OR doc owner is in this org (catches sandbox docs)
    filtered = []
    for crd in all_crds:
        doc = crd.get("documents") or {}
        doc_org_id = doc.get("organization_id")
        doc_owner_id = doc.get("owner_id")
        if doc_org_id == org_id or doc_owner_id in org_member_ids:
            filtered.append(crd)

    return {"message": "Pending CRDs", "crds": filtered}

@router.post("/{crd_id}/approve")
async def approve_crd(crd_id: str, action: CRDApproval, user: CurrentUser):
    """
    Handles HITL (Human-in-the-loop) explicit approvals for AI drafted Document Changes.
    """
    supabase = get_supabase()
    supabase.table("crds").update({"status": action.status, "ai_reasoning": action.ai_reasoning_override}).eq("id", crd_id).execute()
    
    crd_resp = supabase.table("crds").select("document_id, documents(organization_id)").eq("id", crd_id).execute()
    if not crd_resp.data or len(crd_resp.data) == 0:
        return {"message": "CRD not found", "status": "error"}
        
    doc_id = crd_resp.data[0]["document_id"]
    org_id = crd_resp.data[0]["documents"]["organization_id"]
    
    if action.status == "approved":
        # 1. Fetch the pending version and root doc type
        ver_resp = supabase.table("document_versions").select("id, content_text, created_at").eq("document_id", doc_id).eq("status", "pending_review").order("created_at", desc=True).limit(1).execute()
        if ver_resp.data and len(ver_resp.data) > 0:
            version_id = ver_resp.data[0]["id"]
            raw_html = ver_resp.data[0]["content_text"]
            
            doc_meta = supabase.table("documents").select("type, domain_id").eq("id", doc_id).single().execute()
            doc_type = doc_meta.data.get("type", "PANDORA_DOC").upper() if doc_meta.data else "PANDORA_DOC"
            domain_id = doc_meta.data.get("domain_id") if doc_meta.data else None
            
            # Strip HTML tags for clean vector embeddings
            clean_text = re.sub(r'<[^>]+>', ' ', raw_html)
            clean_text = ' '.join(clean_text.split())
            
            # 2. Ingest into Weaviate
            GraphRAGService.ingest_document(doc_id, clean_text, organization_id=org_id, source_type=doc_type, created_at=ver_resp.data[0]["created_at"], domain_id=domain_id)
            
            # 3. Update version status
            supabase.table("document_versions").update({"status": "published"}).eq("id", version_id).execute()
            
        # 4. Ensure Root Document is Published
        supabase.table("documents").update({"status": "published", "updated_at": "now()"}).eq("id", doc_id).execute()

    elif action.status == "rejected":
        # Mark the drafted version as rejected, the author can keep working on a new draft.
        # Root document stays strictly published (or draft).
        ver_resp = supabase.table("document_versions").select("id").eq("document_id", doc_id).eq("status", "pending_review").order("created_at", desc=True).limit(1).execute()
        if ver_resp.data and len(ver_resp.data) > 0:
            supabase.table("document_versions").update({"status": "rejected"}).eq("id", ver_resp.data[0]["id"]).execute()

    return {"message": f"CRD {crd_id} handled.", "status": action.status}
