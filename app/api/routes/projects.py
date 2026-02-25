from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from app.core.security import CurrentUser
from app.db.supabase import get_supabase

router = APIRouter()

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = None
    domain_ids: list[str] = []
    github_repo: Optional[str] = None
    is_public: bool = False

@router.get("/")
async def get_projects(user: CurrentUser):
    """
    Returns projects visible to the user within their organization.
    Super Admins/Admins see all projects in the org.
    Members see projects in their domains OR public projects.
    """
    supabase = get_supabase()
    user_id = user.get("sub")
    
    user_check = supabase.table("organization_users").select("role, organization_id, domain_ids").eq("user_id", user_id).limit(1).execute()
    if not user_check.data or len(user_check.data) == 0:
        return {"projects": []}
        
    org_id = user_check.data[0]["organization_id"]
    role = user_check.data[0]["role"]
    user_domains = user_check.data[0].get("domain_ids", [])

    # Fetch all org domains to join names client-side if needed
    domains_res = supabase.table("domains").select("id, name").eq("organization_id", org_id).execute()
    domains_map = {d["id"]: d["name"] for d in domains_res.data} if domains_res.data else {}

    # Basic fetch of all projects in domains belonging to this org
    # We first find all domain IDs for this org
    org_domains = [d["id"] for d in (domains_res.data or [])]
    
    if not org_domains:
        return {"projects": []}

    # Fetch all projects first
    projects_res = supabase.table("projects").select("*").order("created_at", desc=True).execute()
    all_projects = projects_res.data if hasattr(projects_res, 'data') and projects_res.data else []

    # Fetch project domains natively to bypass PGRST join cache errors
    project_ids = [p["id"] for p in all_projects]
    pd_map = {}
    if project_ids:
        try:
            pd_res = supabase.table("project_domains").select("project_id, domain_id").in_("project_id", project_ids).execute()
            for pd in (pd_res.data if hasattr(pd_res, 'data') and pd_res.data else []):
                pd_map.setdefault(pd["project_id"], []).append(pd["domain_id"])
        except Exception as e:
            print(f"Warning: Could not fetch project_domains: {e}")

    # Map project_domains to a clean array of domain IDs
    for p in all_projects:
        p["domain_ids"] = pd_map.get(p["id"], [])

    # Filter based on role
    visible_projects = []
    if role in ["super_admin", "admin"]:
        visible_projects = all_projects
    else:
        # Members: public projects OR projects where at least one of its domains matches the user's domains
        for p in all_projects:
            if p.get("is_public") or any(d in user_domains for d in p.get("domain_ids", [])):
                visible_projects.append(p)
                
    # Add domain names for the frontend
    for p in visible_projects:
        p["domain_names"] = [domains_map.get(d, "Unknown") for d in p.get("domain_ids", [])]

    return {"projects": visible_projects}

@router.post("/")
async def create_project(req: ProjectCreate, user: CurrentUser):
    """
    Creates a new project and automatically generates an initial PRD document attached to it.
    """
    supabase = get_supabase()
    user_id = user.get("sub")
    
    user_check = supabase.table("organization_users").select("role, organization_id").eq("user_id", user_id).limit(1).execute()
    if not user_check.data or len(user_check.data) == 0:
        raise HTTPException(status_code=403, detail="Not part of an organization.")
        
    role = user_check.data[0]["role"]
    org_id = user_check.data[0]["organization_id"]
    
    if role not in ["super_admin", "admin"]:
        raise HTTPException(status_code=403, detail="Only admins can create projects.")
        
    if not req.domain_ids or len(req.domain_ids) == 0:
        raise HTTPException(status_code=400, detail="Projects must belong to at least one department.")

    # 1. Create the project
    proj_insert = {
        "organization_id": org_id,
        "name": req.name,
        "description": req.description,
        "github_repo": req.github_repo,
        "is_public": req.is_public
    }
    
    proj_res = supabase.table("projects").insert(proj_insert).execute()
    if not proj_res.data or len(proj_res.data) == 0:
        raise HTTPException(status_code=500, detail="Failed to create project.")
        
    project = proj_res.data[0]
    
    # 2. Insert into project_domains
    pd_inserts = [{"project_id": project["id"], "domain_id": did} for did in req.domain_ids]
    supabase.table("project_domains").insert(pd_inserts).execute()
    
    # 3. Automatically generate the initial baseline documents
    base_domain = req.domain_ids[0] if req.domain_ids else None
    
    docs_to_insert = [
        {
            "organization_id": org_id,
            "project_id": project["id"],
            "owner_id": user_id,
            "domain_id": base_domain,
            "title": f"{req.name} - Product Requirements Document",
            "type": "prd",
            "status": "draft"
        },
        {
            "organization_id": org_id,
            "project_id": project["id"],
            "owner_id": user_id,
            "domain_id": base_domain,
            "title": f"{req.name} - Acceptance Criteria",
            "type": "acceptance_criteria",
            "status": "draft"
        },
        {
            "organization_id": org_id,
            "project_id": project["id"],
            "owner_id": user_id,
            "domain_id": base_domain,
            "title": f"{req.name} - Go To Market Strategy",
            "type": "go_to_market_strategy",
            "status": "draft"
        },
        {
            "organization_id": org_id,
            "project_id": project["id"],
            "owner_id": user_id,
            "domain_id": base_domain,
            "title": f"{req.name} - Test Plan",
            "type": "test_plan",
            "status": "draft"
        }
    ]
    
    doc_res = supabase.table("documents").insert(docs_to_insert).execute()
    
    # Optionally link user as project owner
    supabase.table("project_users").insert({
        "project_id": project["id"],
        "user_id": user_id,
        "role": "owner"
    }).execute()

    return {
        "message": "Project created successfully",
        "project": project,
        "initial_documents": doc_res.data if doc_res.data else []
    }
