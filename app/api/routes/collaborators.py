from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.core.security import CurrentUser
from app.db.supabase import get_supabase

router = APIRouter()

class CollaboratorAdd(BaseModel):
    email: str
    role: str = "viewer"  # 'viewer' or 'contributor'

class CollaboratorRemove(BaseModel):
    user_id: str


@router.get("/{document_id}/collaborators")
async def list_collaborators(document_id: str, user: CurrentUser):
    """
    Lists all collaborators on a specific document.
    """
    supabase = get_supabase()
    resp = supabase.table("document_collaborators")\
        .select("user_id, role, created_at")\
        .eq("document_id", document_id)\
        .execute()
    
    collaborators = resp.data or []
    
    # Enrich with emails via separate lookup (no FK between document_collaborators and organization_users)
    for c in collaborators:
        try:
            user_resp = supabase.table("organization_users").select("email").eq("user_id", c["user_id"]).limit(1).execute()
            c["email"] = user_resp.data[0].get("email", "") if user_resp.data else ""
        except Exception:
            c["email"] = ""
    
    return {"collaborators": collaborators}


@router.post("/{document_id}/collaborators")
async def add_collaborator(document_id: str, payload: CollaboratorAdd, user: CurrentUser):
    """
    Adds a user as a collaborator (viewer or contributor) on a document.
    Only the owner or an Admin can do this.
    """
    supabase = get_supabase()
    user_id = user.get("sub")
    
    # Verify current user has access to manage this document
    doc = supabase.table("documents").select("owner_id, organization_id").eq("id", document_id).single().execute()
    if not doc.data:
        raise HTTPException(status_code=404, detail="Document not found")
    
    org_id = doc.data.get("organization_id")  # May be None for private sandbox docs
    is_owner = doc.data["owner_id"] == user_id
    user_role = "member"
    
    if org_id:
        org_check = supabase.table("organization_users").select("role").eq("user_id", user_id).eq("organization_id", org_id).limit(1).execute()
        user_role = org_check.data[0].get("role") if org_check.data else "member"
    
    if not is_owner and user_role not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Only the document owner or an Admin can manage collaborators")
    
    # Look up target user: in org if org_id exists, otherwise any user by user_id directly
    if org_id:
        target_user_resp = supabase.table("organization_users").select("user_id, email").eq("organization_id", org_id).eq("email", payload.email).limit(1).execute()
        if not target_user_resp.data:
            raise HTTPException(status_code=404, detail=f"User with email '{payload.email}' not found in your organization")
        target_user_id = target_user_resp.data[0]["user_id"]
    else:
        # Private sandbox — look up by email globally in organization_users
        target_user_resp = supabase.table("organization_users").select("user_id").eq("email", payload.email).limit(1).execute()
        if not target_user_resp.data:
            raise HTTPException(status_code=404, detail=f"User with email '{payload.email}' not found")
        target_user_id = target_user_resp.data[0]["user_id"]
    
    # Upsert collaborator record
    supabase.table("document_collaborators").upsert({
        "document_id": document_id,
        "user_id": target_user_id,
        "role": payload.role
    }, on_conflict="document_id,user_id").execute()
    
    return {"message": f"{payload.email} added as {payload.role}", "user_id": target_user_id}


@router.delete("/{document_id}/collaborators")
async def remove_collaborator(document_id: str, payload: CollaboratorRemove, user: CurrentUser):
    """
    Removes a collaborator from a document.
    """
    supabase = get_supabase()
    user_id = user.get("sub")
    
    doc = supabase.table("documents").select("owner_id, organization_id").eq("id", document_id).single().execute()
    if not doc.data:
        raise HTTPException(status_code=404, detail="Document not found")
    
    org_id = doc.data.get("organization_id")
    is_owner = doc.data["owner_id"] == user_id
    user_role = "member"
    
    if org_id:
        org_check = supabase.table("organization_users").select("role").eq("user_id", user_id).eq("organization_id", org_id).limit(1).execute()
        user_role = org_check.data[0].get("role") if org_check.data else "member"
    
    if not is_owner and user_role not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Only the document owner or an Admin can manage collaborators")
    
    supabase.table("document_collaborators").delete().eq("document_id", document_id).eq("user_id", payload.user_id).execute()
    
    return {"message": "Collaborator removed"}
