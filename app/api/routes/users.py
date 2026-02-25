from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Optional

from app.core.security import CurrentUser
from app.db.supabase import get_supabase

router = APIRouter()

class InviteRequest(BaseModel):
    email: str
    role: str = "employee"
    domain_id: Optional[str] = None

@router.post("/invite")
async def invite_user(invite: InviteRequest, user: CurrentUser):
    """
    Invites a new user. Triggers Supabase email if possible.
    Falls back gracefully if the email rate limit is hit (free tier: 2/hour).
    """
    supabase = get_supabase()
    user_id = user.get("sub")
    
    # 1. Verify the caller is admin/super_admin within an org
    admin_check = supabase.table("organization_users").select("role, organization_id").eq("user_id", user_id).execute()
    if not admin_check.data or len(admin_check.data) == 0:
        raise HTTPException(status_code=403, detail="You do not belong to an organization.")
        
    inviter_role = admin_check.data[0].get("role")
    org_id = admin_check.data[0].get("organization_id")
    
    if inviter_role not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Only admins can invite new members.")

    # 2. Try to dispatch a real Supabase invite email.
    # On free tier, this is rate-limited to 2 emails/hour. 
    # If it fails, we still record the pending membership so the user can sign up manually.
    invited_user_id = None
    email_sent = False
    email_error = None
    
    try:
        invite_res = supabase.auth.admin.invite_user_by_email(invite.email)
        if invite_res and invite_res.user:
            invited_user_id = invite_res.user.id
            email_sent = True
    except Exception as e:
        email_error = str(e)
        # Generate a temporary placeholder UUID for the pending row.
        # It will be replaced once the user actually signs up and links their account.
        import uuid
        invited_user_id = str(uuid.uuid4())

    # 3. Insert the pending org membership row regardless of email outcome
    insert_data = {
        "organization_id": org_id,
        "user_id": invited_user_id,
        "email": invite.email,
        "role": invite.role,
        "status": "pending",
        "domain_ids": [invite.domain_id] if invite.domain_id else []
    }
    
    res = supabase.table("organization_users").insert(insert_data).execute()
    
    if not hasattr(res, 'data') or len(res.data) == 0:
        raise HTTPException(status_code=500, detail="Failed to record pending invitation in database.")
    
    if email_sent:
        return {
            "message": f"Invitation email sent to {invite.email}!",
            "email_sent": True
        }
    else:
        return {
            "message": f"Invite recorded for {invite.email}, but the email could not be dispatched right now. Reason: {email_error}. The user can sign up manually at your app URL.",
            "email_sent": False,
            "warning": "email_rate_limit"
        }



@router.get("/org_data")
async def get_org_data(user: CurrentUser):
    """
    Returns org context for all authenticated users.
    - Members get: role, org_id, org_name, their departments
    - Admins / Super Admins additionally get: full users list
    - Truly unregistered users get: role=unassigned
    """
    supabase = get_supabase()
    user_id = user.get("sub")
    
    # 1. Lookup by auth UUID first
    user_check = supabase.table("organization_users").select("role, organization_id, status, email").eq("user_id", user_id).execute()
    
    # 2. If not found by UUID, try matching by email (handles placeholder-UUID invite flow)
    if not user_check.data or len(user_check.data) == 0:
        user_email = user.get("email")
        if user_email:
            email_check = supabase.table("organization_users").select("role, organization_id, status, email, user_id").eq("email", user_email).execute()
            if email_check.data and len(email_check.data) > 0:
                # Fix the placeholder UUID: update row to the real auth UUID
                placeholder_id = email_check.data[0].get("user_id")
                supabase.table("organization_users").update({
                    "user_id": user_id,
                    "status": "active"
                }).eq("user_id", placeholder_id).execute()
                user_check = email_check
                user_check.data[0]["user_id"] = user_id
                user_check.data[0]["status"] = "active"
    
    if not user_check.data or len(user_check.data) == 0:
        return {"role": "unassigned", "users": [], "domains": [], "org_name": None, "org_id": None}
        
    role = user_check.data[0].get("role")
    org_id = user_check.data[0].get("organization_id")
    
    # 3. Fetch org name
    org_res = supabase.table("organizations").select("name").eq("id", org_id).limit(1).execute()
    org_name = org_res.data[0].get("name") if hasattr(org_res, 'data') and org_res.data else "Your Organization"
    
    # 4. Fetch domains (all members can see their org's departments)
    domains_data = supabase.table("domains").select("*").eq("organization_id", org_id).order("created_at", desc=True).execute()
    
    # 5. Fetch Dashboard Stats (Active Projects & Pending Approvals)
    projects_count_res = supabase.table("projects").select("id").eq("organization_id", org_id).execute()
    projects_count = len(projects_count_res.data) if hasattr(projects_count_res, 'data') and projects_count_res.data else 0
    
    crds_res = supabase.table("crds").select("id").eq("status", "pending").execute()
    pending_approvals_count = len(crds_res.data) if hasattr(crds_res, 'data') and crds_res.data else 0
    
    # 6. Members: return limited info. Admins: return full user list
    if role not in ["admin", "super_admin"]:
        return {
            "role": role,
            "org_id": org_id,
            "org_name": org_name,
            "users": [],
            "domains": domains_data.data if hasattr(domains_data, 'data') else [],
            "projects_count": projects_count,
            "pending_approvals_count": pending_approvals_count
        }
    
    users_data = supabase.table("organization_users").select("*").eq("organization_id", org_id).order("created_at", desc=True).execute()
    
    return {
        "role": role,
        "org_id": org_id,
        "org_name": org_name,
        "users": users_data.data if hasattr(users_data, 'data') else [],
        "domains": domains_data.data if hasattr(domains_data, 'data') else [],
        "projects_count": projects_count,
        "pending_approvals_count": pending_approvals_count
    }

@router.post("/me/activate")
async def activate_me(user: CurrentUser):
    """
    Called on login to link a placeholder-invite row to the real auth user UUID.
    Updates status to 'active' if matched by email.
    """
    supabase = get_supabase()
    user_id = user.get("sub")
    user_email = user.get("email")
    
    already = supabase.table("organization_users").select("user_id").eq("user_id", user_id).execute()
    if already.data:
        # Already linked — just mark active
        supabase.table("organization_users").update({"status": "active"}).eq("user_id", user_id).execute()
        return {"status": "active", "linked": False}
    
    if user_email:
        match = supabase.table("organization_users").select("user_id").eq("email", user_email).execute()
        if match.data:
            supabase.table("organization_users").update({
                "user_id": user_id,
                "status": "active"
            }).eq("email", user_email).execute()
            return {"status": "active", "linked": True}
    
    return {"status": "unassigned", "linked": False}



class DomainRequest(BaseModel):
    name: str

@router.post("/domains")
async def create_domain(req: DomainRequest, user: CurrentUser):
    """
    Creates a new department (domain) for the organization.
    Only users with the 'admin' or 'super_admin' role can create new domains.
    """
    supabase = get_supabase()
    user_id = user.get("sub")
    
    user_check = supabase.table("organization_users").select("role, organization_id").eq("user_id", user_id).execute()
    
    if not user_check.data or len(user_check.data) == 0:
         raise HTTPException(status_code=403, detail="You are not part of an organization.")
         
    role = user_check.data[0].get("role")
    org_id = user_check.data[0].get("organization_id")
    
    if role not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Only admins can create departments.")
        
    insert_data = {
        "organization_id": org_id,
        "name": req.name,
        "description": "New Department"
    }
    
    res = supabase.table("domains").insert(insert_data).execute()
    
    if hasattr(res, 'data') and len(res.data) > 0:
        return {"message": f"Successfully created department {req.name}!", "domain": res.data[0]}
    
    raise HTTPException(status_code=500, detail="Failed to create department")

class OrganizationRequest(BaseModel):
    name: str

@router.post("/organizations")
async def create_organization(req: OrganizationRequest, user: CurrentUser):
    """
    Onboarding endpoint.
    Creates a new Tenant (Organization), assigns the user as Super Admin, 
    and sets up a default 'General' department.
    """
    supabase = get_supabase()
    user_id = user.get("sub")
    email = user.get("email", "unknown@example.com") # Depends on JWT claims
    
    # 1. Create Organization
    org_res = supabase.table("organizations").insert({
        "name": req.name
    }).execute()
    
    if not hasattr(org_res, 'data') or len(org_res.data) == 0:
        raise HTTPException(status_code=500, detail="Failed to create organization")
        
    org_id = org_res.data[0]["id"]
    
    # 2. Add User as Super Admin
    user_res = supabase.table("organization_users").insert({
        "organization_id": org_id,
        "user_id": user_id,
        "role": "super_admin",
        "email": email,
        "status": "active"
    }).execute()
    
    # 3. Create Default Department
    dept_res = supabase.table("domains").insert({
        "organization_id": org_id,
        "name": "General",
        "description": "Default workspace department"
    }).execute()
    
    return {
        "message": f"Successfully onboarded {req.name}!",
        "organization": org_res.data[0]
    }

@router.get("/org-members")
async def get_org_members(user: CurrentUser):
    """
    Returns all active members in the user's org for the Share panel team picker.
    """
    supabase = get_supabase()
    user_id = user.get("sub")
    org_check = supabase.table("organization_users").select("organization_id").eq("user_id", user_id).limit(1).execute()
    if not org_check.data:
        return {"members": []}
    org_id = org_check.data[0]["organization_id"]
    members_resp = supabase.table("organization_users").select("user_id, email, role").eq("organization_id", org_id).execute()
    # Exclude the requesting user from the list
    members = [m for m in (members_resp.data or []) if m.get("user_id") != user_id]
    return {"members": members}

@router.get("/domains")
async def get_domains(user: CurrentUser):
    """
    Returns all departments (domains) for the user's organization.
    Accessible by all authenticated members.
    """
    supabase = get_supabase()
    user_id = user.get("sub")
    
    user_check = supabase.table("organization_users").select("role, organization_id").eq("user_id", user_id).execute()
    if not user_check.data:
        return {"domains": []}
    
    org_id = user_check.data[0].get("organization_id")
    res = supabase.table("domains").select("*").eq("organization_id", org_id).order("created_at", desc=True).execute()
    
    return {"domains": res.data if hasattr(res, 'data') else [], "role": user_check.data[0].get("role")}

@router.delete("/domains/{domain_id}")
async def delete_domain(domain_id: str, user: CurrentUser):
    """Deletes a department. Only admins and super admins can do this."""
    supabase = get_supabase()
    
    user_check = supabase.table("organization_users").select("role, organization_id").eq("user_id", user.get("sub")).execute()
    if not user_check.data or user_check.data[0].get("role") not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Only admins can delete departments.")
    
    supabase.table("domains").delete().eq("id", domain_id).execute()
    return {"message": "Department deleted."}

@router.get("/domains/{domain_id}")
async def get_domain_detail(domain_id: str, user: CurrentUser):
    """
    Returns a single department's details including its members and project count.
    Accessible by admins and super admins.
    """
    supabase = get_supabase()
    user_check = supabase.table("organization_users").select("role, organization_id").eq("user_id", user.get("sub")).execute()
    if not user_check.data:
        raise HTTPException(status_code=403, detail="Not part of an organization.")
    if user_check.data[0].get("role") not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Only admins can view department details.")
    
    # Avoid .single() — it throws APIError in supabase-py v2 when 0 rows returned
    domain_res = supabase.table("domains").select("*").eq("id", domain_id).limit(1).execute()
    if not domain_res.data or len(domain_res.data) == 0:
        raise HTTPException(status_code=404, detail="Department not found.")
    
    domain = domain_res.data[0]
    org_id = user_check.data[0].get("organization_id")
    
    # Fetch ALL org members and filter client-side: who has this domain_id in their array
    all_users_res = supabase.table("organization_users").select("*").eq("organization_id", org_id).execute()
    members = [
        u for u in (all_users_res.data or [])
        if isinstance(u.get("domain_ids"), list) and domain_id in u["domain_ids"]
    ]
    
    # Fetch projects assigned to this domain — wrap in try/except in case domain_id col doesn't exist
    projects = []
    try:
        projects_res = supabase.table("projects").select("id, title, status").eq("domain_id", domain_id).execute()
        projects = projects_res.data if hasattr(projects_res, 'data') and projects_res.data else []
    except Exception:
        pass  # projects table may not have domain_id yet — silently return empty
    
    return {
        "domain": domain,
        "members": members,
        "projects": projects,
        "role": user_check.data[0].get("role")
    }

@router.post("/domains/{domain_id}/members/{target_user_id}")
async def add_member_to_domain(domain_id: str, target_user_id: str, user: CurrentUser):
    """Adds an existing org member to a department by appending domain_id to their domain_ids array."""
    supabase = get_supabase()
    user_check = supabase.table("organization_users").select("role, organization_id").eq("user_id", user.get("sub")).execute()
    if not user_check.data or user_check.data[0].get("role") not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Only admins can assign members to departments.")
    
    # Fetch target user's current domain_ids
    target_res = supabase.table("organization_users").select("domain_ids").eq("user_id", target_user_id).eq("organization_id", user_check.data[0].get("organization_id")).execute()
    if not target_res.data:
        raise HTTPException(status_code=404, detail="User not found in this organization.")
    
    current_ids = target_res.data[0].get("domain_ids") or []
    if domain_id not in current_ids:
        current_ids.append(domain_id)
        supabase.table("organization_users").update({"domain_ids": current_ids}).eq("user_id", target_user_id).execute()
    
    return {"message": "Member added to department."}

@router.delete("/domains/{domain_id}/members/{target_user_id}")
async def remove_member_from_domain(domain_id: str, target_user_id: str, user: CurrentUser):
    """Removes a member from a department by filtering domain_id out of their domain_ids array."""
    supabase = get_supabase()
    user_check = supabase.table("organization_users").select("role, organization_id").eq("user_id", user.get("sub")).execute()
    if not user_check.data or user_check.data[0].get("role") not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Only admins can remove members from departments.")
    
    target_res = supabase.table("organization_users").select("domain_ids").eq("user_id", target_user_id).eq("organization_id", user_check.data[0].get("organization_id")).execute()
    if not target_res.data:
        raise HTTPException(status_code=404, detail="User not found.")
    
    current_ids = [d for d in (target_res.data[0].get("domain_ids") or []) if d != domain_id]
    supabase.table("organization_users").update({"domain_ids": current_ids}).eq("user_id", target_user_id).execute()
    
    return {"message": "Member removed from department."}



@router.get("/integrations")
async def get_integrations(user: CurrentUser):
    """Returns all configured integrations for the organization. Super Admin only."""
    supabase = get_supabase()
    user_id = user.get("sub")
    
    user_check = supabase.table("organization_users").select("role, organization_id").eq("user_id", user_id).execute()
    if not user_check.data:
        raise HTTPException(status_code=403, detail="Not part of an organization.")
    
    role = user_check.data[0].get("role")
    org_id = user_check.data[0].get("organization_id")
    
    if role not in ["admin", "super_admin"]:
        raise HTTPException(status_code=403, detail="Only admins can view integrations.")
    
    res = supabase.table("organization_integrations").select("id, provider, created_at").eq("organization_id", org_id).execute()
    return {"integrations": res.data if hasattr(res, 'data') else []}

class IntegrationRequest(BaseModel):
    provider: str
    token: str

@router.post("/integrations")
async def save_integration(req: IntegrationRequest, user: CurrentUser):
    """Saves or updates an org integration token. Super Admin only."""
    supabase = get_supabase()
    user_id = user.get("sub")
    
    user_check = supabase.table("organization_users").select("role, organization_id").eq("user_id", user_id).execute()
    if not user_check.data or user_check.data[0].get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Only super admins can manage integrations.")
    
    org_id = user_check.data[0].get("organization_id")
    
    # Upsert (insert or update on conflict)
    res = supabase.table("organization_integrations").upsert({
        "organization_id": org_id,
        "provider": req.provider,
        "encrypted_token": req.token  # In production: encrypt before storing
    }, on_conflict="organization_id,provider").execute()
    
    return {"message": f"{req.provider} integration saved!"}

@router.delete("/integrations/{provider}")
async def delete_integration(provider: str, user: CurrentUser):
    """Removes an integration. Super Admin only."""
    supabase = get_supabase()
    
    user_check = supabase.table("organization_users").select("role, organization_id").eq("user_id", user.get("sub")).execute()
    if not user_check.data or user_check.data[0].get("role") != "super_admin":
        raise HTTPException(status_code=403, detail="Only super admins can remove integrations.")
    
    org_id = user_check.data[0].get("organization_id")
    supabase.table("organization_integrations").delete().eq("organization_id", org_id).eq("provider", provider).execute()
    return {"message": f"{provider} integration removed."}
