from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel
from typing import Optional

from app.core.security import CurrentUser
from app.db.supabase import get_supabase
from app.services.parsing_service import FileParsingService
from app.services.graphrag_service import GraphRAGService
from app.core.config import settings

router = APIRouter()

class DocumentCreate(BaseModel):
    title: str
    type: str
    project_id: Optional[str] = None
    organization_id: Optional[str] = None
    domain_id: Optional[str] = None
    is_public: bool = False
    is_public_to_org: bool = False

class DocumentPatch(BaseModel):
    title: Optional[str] = None
    is_public: Optional[bool] = None
    is_public_to_org: Optional[bool] = None
    domain_id: Optional[str] = None

class DocumentReviewAction(BaseModel):
    action: str # 'approved' or 'rejected'

class DraftVersionCreate(BaseModel):
    content_text: str
    title: Optional[str] = "Untitled Document"
    type: Optional[str] = "regular"
    project_id: Optional[str] = None
    domain_id: Optional[str] = None

@router.post("/")
async def create_document(doc: DocumentCreate, user: CurrentUser):
    """
    Creates a new document metadata record in Supabase.
    If project_id is None, it acts as a Private Sandbox document.
    """
    supabase = get_supabase()
    # Enforce: Public to Org implies is_public = True
    is_public = doc.is_public or doc.is_public_to_org
    data = {
        "title": doc.title,
        "type": doc.type,
        "owner_id": user.get("sub"),
        "is_public": is_public,
        "is_public_to_org": doc.is_public_to_org
    }
    if doc.project_id:
        data["project_id"] = doc.project_id
    if doc.organization_id:
        data["organization_id"] = doc.organization_id
    if doc.domain_id:
        data["domain_id"] = doc.domain_id
        
    response = supabase.table("documents").insert(data).execute()
    new_doc = response.data[0] if getattr(response, 'data', None) else None
    return {"message": "Document created", "doc": new_doc, "user_id": user.get("sub")}


@router.patch("/{document_id}")
async def patch_document(document_id: str, patch: DocumentPatch, user: CurrentUser):
    """
    Update document metadata (title, visibility).
    Only the owner or an admin can do this.
    """
    supabase = get_supabase()
    user_id = user.get("sub")

    doc = supabase.table("documents").select("owner_id").eq("id", document_id).single().execute()
    if not doc.data:
        raise HTTPException(status_code=404, detail="Document not found")
    if doc.data["owner_id"] != user_id:
        # Allow admins too
        org_check = supabase.table("organization_users").select("role").eq("user_id", user_id).limit(1).execute()
        role = org_check.data[0].get("role") if org_check.data else "member"
        if role not in ["admin", "super_admin"]:
            raise HTTPException(status_code=403, detail="Only the owner or an admin can update this document")

    update_data = {}
    if patch.title is not None:
        update_data["title"] = patch.title
    if patch.is_public_to_org is not None:
        update_data["is_public_to_org"] = patch.is_public_to_org
        # Enforce: if public_to_org, is_public must be True
        if patch.is_public_to_org:
            update_data["is_public"] = True
        elif patch.is_public is None:
            pass  # let is_public stay as-is unless explicitly set
    if patch.is_public is not None:
        update_data["is_public"] = patch.is_public
        if not patch.is_public:
            update_data["is_public_to_org"] = False  # can't be public_to_org if not public
    if patch.domain_id is not None:
        update_data["domain_id"] = patch.domain_id

    if not update_data:
        return {"message": "No changes"}

    resp = supabase.table("documents").update(update_data).eq("id", document_id).execute()
    return {"message": "Updated", "doc": resp.data[0] if resp.data else {}}


@router.post("/{document_id}/versions")
async def draft_document_version(document_id: str, payload: DraftVersionCreate, user: CurrentUser):
    """
    Drafts a new text version for a document via the TipTap editor.
    Triggers the LangGraph Diffing Agent.
    """
    supabase = get_supabase()
    
    org_check = supabase.table("organization_users").select("organization_id").eq("user_id", user.get("sub")).execute()
    org_id = org_check.data[0].get("organization_id") if org_check.data else ""

    if document_id == "new":
        doc_data = {
            "title": payload.title, 
            "type": payload.type, 
            "owner_id": user.get("sub"),
            "organization_id": org_id,
            "project_id": payload.project_id
        }
        if payload.domain_id:
            doc_data["domain_id"] = payload.domain_id
        doc_resp = supabase.table("documents").insert(doc_data).execute()
        if hasattr(doc_resp, 'data') and doc_resp.data:
            document_id = doc_resp.data[0]["id"]
    else:
        # If updating an existing doc, update its title/type if provided
        update_data = {"updated_at": "now()"}
        if payload.title and payload.title != "Untitled Document":
            update_data["title"] = payload.title
        if payload.type and payload.type != "regular":
            update_data["type"] = payload.type
        if payload.domain_id:
            update_data["domain_id"] = payload.domain_id
        supabase.table("documents").update(update_data).eq("id", document_id).execute()
        
    data = {"document_id": document_id, "content_text": payload.content_text, "created_by": user.get("sub"), "author_id": user.get("sub"), "status": "draft"}
    supabase.table("document_versions").insert(data).execute()
    
    return {"message": "Version drafted", "document_id": document_id}

@router.post("/{document_id}/upload")
async def upload_document_file(document_id: str, user: CurrentUser, file: UploadFile = File(...)):
    """
    Accepts generic uploads (PDF, Docx, MD), parses them using PyMuPDF/python-docx,
    and saves the raw text as a new document_version. 
    Triggers the LangGraph Diffing Agent.
    """
    content_text = await FileParsingService.extract_text(file)
    
    supabase = get_supabase()
    
    if document_id == "new":
        doc_data = {"title": file.filename, "type": "Uploaded File", "owner_id": user.get("sub")}
        doc_resp = supabase.table("documents").insert(doc_data).execute()
        if hasattr(doc_resp, 'data') and doc_resp.data:
            document_id = doc_resp.data[0]["id"]
    else:
        supabase.table("documents").update({"updated_at": "now()"}).eq("id", document_id).execute()
        
    org_check = supabase.table("organization_users").select("organization_id").eq("user_id", user.get("sub")).execute()
    org_id = org_check.data[0].get("organization_id") if org_check.data else ""

    data = {"document_id": document_id, "content_text": content_text, "created_by": user.get("sub"), "author_id": user.get("sub"), "status": "draft"}
    supabase.table("document_versions").insert(data).execute()
    
    return {
        "message": f"File {file.filename} uploaded and parsed successfully.", 
        "extracted_length": len(content_text),
        "content_text": content_text
    }

import re

@router.post("/{document_id}/publish")
async def publish_document(document_id: str, user: CurrentUser):
    """
    Publishes the latest drafted version of a document.
    Strips raw HTML rich text into plain text and syncs it to the Weaviate GraphRAG semantic knowledge base.
    """
    supabase = get_supabase()
    user_id = user.get("sub")
    
    org_check = supabase.table("organization_users").select("organization_id, role").eq("user_id", user_id).limit(1).execute()
    if not org_check.data or len(org_check.data) == 0:
        raise HTTPException(status_code=403, detail="Not a member of an organization")
        
    org_id = org_check.data[0].get("organization_id")
    user_role = org_check.data[0].get("role")
    
    # Get the user's latest draft version
    draft_resp = supabase.table("document_versions").select("id, content_text, created_at").eq("document_id", document_id).eq("author_id", user_id).eq("status", "draft").order("created_at", desc=True).limit(1).execute()
    if not draft_resp.data or len(draft_resp.data) == 0:
        raise HTTPException(status_code=404, detail="No un-published drafts found to publish.")
        
    draft_id = draft_resp.data[0]["id"]
    raw_html = draft_resp.data[0]["content_text"]
    ver_created_at = draft_resp.data[0]["created_at"]
    
    # Get the latest active published version for diffing
    published_resp = supabase.table("document_versions").select("content_text").eq("document_id", document_id).eq("status", "published").order("created_at", desc=True).limit(1).execute()
    
    # Strip HTML tags for clean vector embeddings
    clean_text = re.sub(r'<[^>]+>', ' ', raw_html)
    clean_text = ' '.join(clean_text.split())

    # Fetch doc to check is_public flag and domain_id
    doc_resp = supabase.table("documents").select("is_public, type, domain_id").eq("id", document_id).single().execute()
    is_public = doc_resp.data.get("is_public", False) if doc_resp.data else False
    doc_type = doc_resp.data.get("type", "PANDORA_DOC").upper() if doc_resp.data else "PANDORA_DOC"
    domain_id = doc_resp.data.get("domain_id") if doc_resp.data else None
    
    # Super admins can publish public docs directly without going through HITL
    # Regular members (and admins on non-public docs) go through the review queue
    if user_role == "member" or (user_role == "admin" and not is_public):
        # Generate an AI Diff Summary for the Admin
        ai_summary = "Initial Document Creation. No previous version to compare."
        if published_resp.data and len(published_resp.data) > 0 and settings.GOOGLE_API_KEY:
            old_html = published_resp.data[0]["content_text"]
            old_clean_text = re.sub(r'<[^>]+>', ' ', old_html)
            old_clean_text = ' '.join(old_clean_text.split())
            
            try:
                from langchain_google_genai import ChatGoogleGenerativeAI
                from langchain_core.prompts import PromptTemplate
                
                llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=settings.GOOGLE_API_KEY, temperature=0.1)
                prompt = PromptTemplate.from_template(
                    "You are a helpful AI assistant assisting an Admin in approving document changes.\n"
                    "Briefly summarize the changes made from the Old Version to the New Version in 2-3 concise bullet points.\n\n"
                    "Old Version:\n{old}\n\n"
                    "New Version:\n{new}\n\n"
                    "Summary of Changes:"
                )
                chain = prompt | llm
                msg = chain.invoke({"old": old_clean_text, "new": clean_text})
                ai_summary = msg.content
            except Exception as e:
                print(f"Failed to generate diff summary: {e}")
                ai_summary = "Failed to generate AI diff summary due to LLM error."
    
        # HITL Workflow: Members cannot publish directly. It goes to the Admin Queue.
        supabase.table("document_versions").update({"status": "pending_review"}).eq("id", draft_id).execute()
        
        # NOTE: Root document remains whatever it was (draft/published). It is NOT marked in_review.
        
        # Create a CRD Approval Ticket for Admins
        crd_data = {
            "document_id": document_id,
            "status": "pending",
            "changes_summary": ai_summary
        }
        try:
            supabase.table("crds").insert(crd_data).execute()
        except Exception as e:
            print(f"CRD Insert Error: {e}")
        
        return {
            "message": "Publish request submitted for Admin review.", 
            "status": "in_review",
            "document_id": document_id
        }
    
    # Adms/SuperAdmins: Ingest into Semantic Knowledge Base immediately
    GraphRAGService.ingest_document(document_id, clean_text, organization_id=org_id, source_type=doc_type, created_at=ver_created_at, domain_id=domain_id)
    
    # Update Version Status to Published
    supabase.table("document_versions").update({"status": "published"}).eq("id", draft_id).execute()
    # Update Root Document Status to Published (if it wasn't already)
    supabase.table("documents").update({"status": "published", "updated_at": "now()"}).eq("id", document_id).execute()
    
    return {
        "message": "Document published and synced to AI Knowledge Base successfully.", 
        "status": "published",
        "document_id": document_id
    }

@router.delete("/{document_id}")
async def delete_document(document_id: str, user: CurrentUser):
    """
    Permanently deletes a document and all its versions, CRDs, collaborators,
    and purges the associated vector nodes from the Weaviate knowledge base.
    Only the owner or an admin can delete.
    """
    supabase = get_supabase()
    user_id = user.get("sub")

    # Ownership / role check
    doc = supabase.table("documents").select("owner_id").eq("id", document_id).single().execute()
    if not doc.data:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if doc.data["owner_id"] != user_id:
        org_check = supabase.table("organization_users").select("role").eq("user_id", user_id).limit(1).execute()
        role = org_check.data[0].get("role") if org_check.data else None
        if role not in ["admin", "super_admin"]:
            raise HTTPException(status_code=403, detail="Only the owner or an admin can delete this document")

    # Purge vector DB first (soft fail so supabase cleanup still runs)
    try:
        GraphRAGService.delete_document(document_id)
    except Exception as e:
        print(f"Vector purge warning for {document_id}: {e}")

    # Delete child records then the parent document
    supabase.table("crds").delete().eq("document_id", document_id).execute()
    supabase.table("document_collaborators").delete().eq("document_id", document_id).execute()
    supabase.table("document_versions").delete().eq("document_id", document_id).execute()
    supabase.table("documents").delete().eq("id", document_id).execute()

    return {"message": "Document deleted successfully", "document_id": document_id}

@router.get("/")
async def get_documents(user: CurrentUser, type: Optional[str] = None, domain_id: Optional[str] = None):
    """
    Retrieves all documents accessible to the user, with optional filtering.
    """
    supabase = get_supabase()
    user_id = user.get("sub")
    
    org_check = supabase.table("organization_users").select("organization_id").eq("user_id", user_id).execute()
    org_id = org_check.data[0].get("organization_id") if org_check.data else None
    
    def apply_filters(query):
        if type:
            query = query.eq("type", type)
        if domain_id:
            query = query.eq("domain_id", domain_id)
        return query

    all_docs = []
    
    # 1. Fetch private sandbox docs owned by the user (no org attached)
    private_query = supabase.table("documents").select("*").eq("owner_id", user_id).is_("organization_id", "null")
    private_query = apply_filters(private_query)
    private_resp = private_query.order("updated_at", desc=True).execute()
    if private_resp.data:
        all_docs.extend(private_resp.data)
    
    # 2. Fetch org-scoped docs if user belongs to an org
    if org_id:
        org_query = supabase.table("documents").select("*").eq("organization_id", org_id)
        org_query = apply_filters(org_query)
        org_resp = org_query.order("updated_at", desc=True).execute()
        if org_resp.data:
            existing_ids = {d["id"] for d in all_docs}
            all_docs.extend([d for d in org_resp.data if d["id"] not in existing_ids])
    
    # 3. Fetch docs where user is an explicit collaborator (regardless of org/sandbox)
    collab_resp = supabase.table("document_collaborators").select("document_id").eq("user_id", user_id).execute()
    if collab_resp.data:
        collab_doc_ids = [c["document_id"] for c in collab_resp.data]
        existing_ids = {d["id"] for d in all_docs}
        missing_ids = [did for did in collab_doc_ids if did not in existing_ids]
        if missing_ids:
            for did in missing_ids:
                d_query = supabase.table("documents").select("*").eq("id", did)
                d_query = apply_filters(d_query)
                d_res = d_query.single().execute()
                if d_res.data:
                    all_docs.append(d_res.data)

    # 4. Fetch docs that are public to the organization, even if organization_id is null
    if org_id:
        public_query = supabase.table("documents").select("*").is_("organization_id", "null").eq("is_public_to_org", True)
        public_query = apply_filters(public_query)
        public_to_org_resp = public_query.order("updated_at", desc=True).execute()
        if public_to_org_resp.data:
            existing_ids = {d["id"] for d in all_docs}
            all_docs.extend([d for d in public_to_org_resp.data if d["id"] not in existing_ids])
    
    # Sort combined list by updated_at descending
    all_docs.sort(key=lambda d: d.get("updated_at", ""), reverse=True)
    
    return {"documents": all_docs}

@router.post("/{document_id}/review")
async def review_document(document_id: str, payload: DocumentReviewAction, user: CurrentUser):
    """
    Directly approve or reject a document (Admin only).
    """
    supabase = get_supabase()
    user_id = user.get("sub")
    
    org_check = supabase.table("organization_users").select("organization_id, role").eq("user_id", user_id).limit(1).execute()
    if not org_check.data or org_check.data[0].get("role") not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Unauthorized")
        
    org_id = org_check.data[0].get("organization_id")
    action = payload.action
    
    # Sync matching CRDs if they exist
    supabase.table("crds").update({"status": action}).eq("document_id", document_id).eq("status", "pending").execute()
    
    if action == "approved":
        # Fetch the pending version
        ver_resp = supabase.table("document_versions").select("id, content_text, created_at").eq("document_id", document_id).eq("status", "pending_review").order("created_at", desc=True).limit(1).execute()
        if ver_resp.data and len(ver_resp.data) > 0:
            version_id = ver_resp.data[0]["id"]
            raw_html = ver_resp.data[0]["content_text"]
            ver_created_at = ver_resp.data[0]["created_at"]
            
            # Fetch doc meta
            doc_meta = supabase.table("documents").select("type, domain_id").eq("id", document_id).single().execute()
            doc_type = doc_meta.data.get("type", "PANDORA_DOC").upper() if doc_meta.data else "PANDORA_DOC"
            domain_id = doc_meta.data.get("domain_id") if doc_meta.data else None
            
            import re
            clean_text = re.sub(r'<[^>]+>', ' ', raw_html)
            clean_text = ' '.join(clean_text.split())
            GraphRAGService.ingest_document(document_id, clean_text, organization_id=org_id, source_type=doc_type, created_at=ver_created_at, domain_id=domain_id)
            
            # Update Version Status
            supabase.table("document_versions").update({"status": "published"}).eq("id", version_id).execute()
            
        # Ensure Root Document is Published
        supabase.table("documents").update({"status": "published", "updated_at": "now()"}).eq("id", document_id).execute()
        return {"message": "Document published successfully.", "status": "published"}
        
    elif action == "rejected":
        # Mark the drafted version as rejected, the author can keep working on a new draft.
        # Root document stays strictly published (or draft).
        ver_resp = supabase.table("document_versions").select("id").eq("document_id", document_id).eq("status", "pending_review").order("created_at", desc=True).limit(1).execute()
        if ver_resp.data and len(ver_resp.data) > 0:
            supabase.table("document_versions").update({"status": "rejected"}).eq("id", ver_resp.data[0]["id"]).execute()
            
        return {"message": "Document rejected.", "status": action}
        
    raise HTTPException(status_code=400, detail="Invalid action")
