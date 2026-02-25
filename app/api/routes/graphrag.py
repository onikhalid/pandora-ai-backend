from fastapi import APIRouter, HTTPException
from app.core.security import CurrentUser
from app.services.graphrag_service import GraphRAGService
from app.db.supabase import get_supabase
from app.core.config import settings

router = APIRouter()


def get_permitted_document_ids(user_id: str, org_id: str) -> list:
    """
    Computes the list of document IDs a user is explicitly allowed to see.
    Returns None if the user is an admin (admins see all), or a list of IDs.
    """
    supabase = get_supabase()
    
    # Check role
    org_check = supabase.table("organization_users").select("role").eq("user_id", user_id).eq("organization_id", org_id).limit(1).execute()
    if not org_check.data:
        return []
    
    role = org_check.data[0].get("role")
    
    # Private sandbox rule: NOBODY (not even admins) can see another user's private doc
    # until it has been submitted for review (pending_review version exists) or is_public=True.
    # Admins CAN see docs that have a pending_review version (i.e. awaiting their approval).
    
    # Docs user owns (including sandbox ones which might have null org_id)
    owned_resp = supabase.table("documents").select("id").eq("owner_id", user_id).execute()
    owned_ids = [d["id"] for d in (owned_resp.data or [])]
    
    # Public docs in the org OR globally public docs
    # We fetch docs that are globally is_public OR (is_public_to_org and match org_id)
    # Using 'or' in Supabase postgrest query
    public_resp = supabase.table("documents").select("id").or_(f"is_public.eq.true,and(is_public_to_org.eq.true,organization_id.eq.{org_id})").execute()
    public_ids = [d["id"] for d in (public_resp.data or [])]
    
    # Docs user is a collaborator on
    collab_resp = supabase.table("document_collaborators").select("document_id").eq("user_id", user_id).execute()
    collab_ids = [d["document_id"] for d in (collab_resp.data or [])]
    
    # For admins: also include docs that have a pending_review version (for the approval queue)
    pending_ids = []
    if role in ["admin", "super_admin"]:
        # Find all docs with a pending_review version in this org — admins need to see these for approval
        pending_resp = supabase.table("document_versions").select("document_id").eq("status", "pending_review").execute()
        pending_ids = [d["document_id"] for d in (pending_resp.data or [])]
    
    all_ids = list(set(owned_ids + public_ids + collab_ids + pending_ids))
    return all_ids


@router.get("/trace/{document_id}")
async def get_document_trace(document_id: str, user: CurrentUser):
    """
    Returns the GraphRAG lineage for a specific document.
    Outputs nodes and edges required for the React interactive Graph Viewer.
    E.g. [Figma Node] -> [ClickUp Task] -> [GitHub Commit]
    """
    if document_id == "new":
        return {"message": "New Document Trace", "nodes": [], "edges": [], "weaviate_nodes": []}
        
    supabase = get_supabase()
    user_id = user.get("sub")
    user_check = supabase.table("organization_users").select("organization_id").eq("user_id", user_id).limit(1).execute()
    
    if not user_check.data or len(user_check.data) == 0:
        raise HTTPException(status_code=403, detail="Not a member of an organization")
        
    org_id = user_check.data[0].get("organization_id")
    allowed_ids = get_permitted_document_ids(user_id, org_id)
    
    try:
        res = GraphRAGService.search_similar_content(document_id, organization_id=org_id, limit=5, allowed_document_ids=allowed_ids)
    except Exception as e:
        print(f"Weaviate search failed: {e}")
        res = []
    
    response = supabase.table("crds").select("lineage_data").eq("document_id", document_id).order("created_at", desc=True).limit(1).execute()
    
    lineage_data = []
    if getattr(response, 'data', None) and len(response.data) > 0:
        lineage_data = response.data[0].get("lineage_data") or []

    nodes = []
    edges = []
    
    doc_node_id = f"doc_{document_id}"
    nodes.append({
        "id": doc_node_id,
        "label": "Document Source",
        "type": "document",
        "subtitle": f"PANDORA ID: {document_id}"
    })
    
    prev_id = doc_node_id
    
    # 1. Construct nodes from MCP Lineage (ClickUp, GitHub, etc)
    for i, trace in enumerate(lineage_data):
        t_id = f"trace_{i}"
        source_type = trace.get("source", "task")
        nodes.append({
            "id": t_id,
            "label": trace.get("ref", "Reference"),
            "type": source_type,
            "subtitle": trace.get("reason", "")
        })
        edges.append({"source": prev_id, "target": t_id})
        prev_id = t_id

    # 2. Append Semantic Knowledge Base matches from Weaviate as traces 
    for i, w_node in enumerate(res):
        t_id = f"weaviate_{i}"
        node_type = w_node.get("source_type", "document").lower()
        if node_type == "pandora_doc":
            node_type = "document"
            
        nodes.append({
            "id": t_id,
            "label": w_node.get("external_id") or f"Semantic Vector Context",
            "type": node_type,
            "subtitle": "Knowledge Base Match"
        })
        edges.append({"source": prev_id, "target": t_id})
        prev_id = t_id
    
    return {"message": "Traceability Graph", "nodes": nodes, "edges": edges, "weaviate_nodes": res}

@router.get("/search")
async def semantic_search(query: str, user: CurrentUser, doc_type: str = None, domain_id: str = None):
    """
    Exposes the Weaviate semantic search for the Global AI Chat UI.
    Results are personalized to only the documents this user is allowed to read.
    """
    supabase = get_supabase()
    user_id = user.get("sub")
    user_check = supabase.table("organization_users").select("organization_id").eq("user_id", user_id).limit(1).execute()
    
    if not user_check.data or len(user_check.data) == 0:
        raise HTTPException(status_code=403, detail="Not a member of an organization")
        
    org_id = user_check.data[0].get("organization_id")
    
    # Compute personalized document list for this user
    allowed_ids = get_permitted_document_ids(user_id, org_id)
    
    # If searching for reports, we want broader context for better synthesis across weeks
    search_limit = 10 if doc_type and doc_type.lower() == "report" else 3
    
    try:
        results = GraphRAGService.search_similar_content(
            query, 
            organization_id=org_id, 
            limit=search_limit, 
            allowed_document_ids=allowed_ids,
            source_type=doc_type.upper() if doc_type else None,
            domain_id=domain_id
        )
        
        def format_date(d_str):
            if not d_str or d_str == 'Unknown Date': return 'Unknown Date'
            try:
                from datetime import datetime
                d_str = d_str.replace('Z', '+00:00')
                dt = datetime.fromisoformat(d_str)
                return dt.strftime("%B %d, %Y at %I:%M %p")
            except Exception:
                return d_str
                
        # Fetch metadata to inject privacy/visibility context
        snippet_doc_ids = list({r.get("document_id") for r in results if r.get("document_id")})
        doc_metadata_map = {}
        if snippet_doc_ids:
            try:
                meta_resp = supabase.table("documents").select("id, is_public, is_public_to_org, organization_id").in_("id", snippet_doc_ids).execute()
                for d in (meta_resp.data or []):
                    visibility = "Official Public Document"
                    if d.get("organization_id") is None:
                        visibility = "Private Personal Sandbox Document"
                    elif not d.get("is_public") and not d.get("is_public_to_org"):
                        visibility = "Restricted Internal Document"
                    doc_metadata_map[d["id"]] = visibility
            except Exception:
                pass
                
        context_parts = []
        for r in results:
            did = r.get("document_id")
            vis = doc_metadata_map.get(did, "Unknown Visibility")
            formatted_date = format_date(r.get('created_at', 'Unknown Date'))
            context_parts.append(f"[Visibility: {vis}] [Reported on {formatted_date}]: {r.get('content', '')}")
            
        context_text = "\n\n".join(context_parts)
        
        ai_response = "I couldn't find anything relevant in your organization's knowledge base."
        if results and settings.GOOGLE_API_KEY:
            from langchain_google_genai import ChatGoogleGenerativeAI
            from langchain_core.prompts import PromptTemplate
            
            # Specialized persona for Reports vs General Search
            if doc_type and doc_type.lower() == "report":
                system_prompt = (
                    "You are the PANDORA Reports AI Analyst.\n"
                    "Your mission is to synthesize results from departmental weekly reports. "
                    "Focus on identifying: 1) Concrete progress made, 2) Persistent blockers, and 3) Priorities for next week. "
                    "Use the [Reported on Date] to identify trends over time. "
                )
            else:
                system_prompt = (
                    "You are an intelligent organizational AI assistant named PANDORA Core.\n"
                    "Answer the user's question clearly and concisely based ONLY on the following context. "
                )

            llm = ChatGoogleGenerativeAI(model="gemini-2.5-flash", google_api_key=settings.GOOGLE_API_KEY, temperature=0.2)
            prompt_str = (
                f"{system_prompt}\n"
                "Constraints: Use ONLY the provided context. If multiple snippets conflict, use dates to clarify the chronology. "
                "Format dates in a friendly, human-readable way. DO NOT output raw ISO timestamps.\n"
                "If you don't know the answer based on the context, politely say so. DO NOT make up information.\n\n"
                "Context:\n{context}\n\n"
                "Question:\n{question}\n\n"
                "Answer:"
            )
            prompt = PromptTemplate.from_template(prompt_str)
            chain = prompt | llm
            try:
                msg = chain.invoke({"context": context_text, "question": query})
                ai_response = msg.content
            except Exception as llm_e:
                print(f"LLM Generation Error: {llm_e}")
                ai_response = "I found relevant context, but my language model failed to synthesize an answer."
        elif results:
            ai_response = "I found relevant documents, but AI synthesis is disabled (missing GOOGLE_API_KEY)."
    except Exception as e:
        print(f"Weaviate semantic search failed: {e}")
        results = []
        ai_response = "Sorry, I encountered an error communicating with the Vector Database."
        
    return {"message": "Search results", "query": query, "results": results, "ai_response": ai_response}
