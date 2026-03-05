"""
ClickUp Integration Router
Connects Pandora orgs to ClickUp via OAuth or Personal Token.
Provides hierarchy proxy endpoints and a webhook listener.
"""
import httpx
from fastapi import APIRouter, HTTPException, Body
from typing import Optional

from app.core.config import settings
from app.core.security import CurrentUser
from app.db.supabase import get_supabase

CLICKUP_API_BASE = "https://api.clickup.com/api/v2"

router = APIRouter()


# ─────────────────────────────────────────────
# Internal Helpers
# ─────────────────────────────────────────────

def _get_org_id(user: dict) -> str:
    """Get org ID for the current user from Supabase, raises 403 if not found."""
    user_id = user.get("sub")
    supabase = get_supabase()
    res = supabase.table("organization_users").select("organization_id").eq("user_id", user_id).limit(1).execute()
    if not res.data:
        raise HTTPException(status_code=403, detail="Not part of any organization.")
    return res.data[0]["organization_id"]


def _get_token(org_id: str) -> str:
    """Retrieve the stored ClickUp access token for the given org."""
    supabase = get_supabase()
    res = supabase.table("clickup_connections").select("access_token").eq("organization_id", org_id).limit(1).execute()
    if not res.data:
        raise HTTPException(
            status_code=404,
            detail="ClickUp not connected. Go to Settings > Integrations to connect."
        )
    return res.data[0]["access_token"]


async def _cu_get(path: str, token: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(f"{CLICKUP_API_BASE}{path}", headers={"Authorization": token})
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=f"ClickUp API: {resp.text}")
        return resp.json()


async def _cu_post(path: str, token: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(f"{CLICKUP_API_BASE}{path}", headers={"Authorization": token, "Content-Type": "application/json"}, json=body)
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=f"ClickUp API: {resp.text}")
        return resp.json()


async def _cu_put(path: str, token: str, body: dict) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.put(f"{CLICKUP_API_BASE}{path}", headers={"Authorization": token, "Content-Type": "application/json"}, json=body)
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=f"ClickUp API: {resp.text}")
        return resp.json()


async def _cu_delete(path: str, token: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.delete(f"{CLICKUP_API_BASE}{path}", headers={"Authorization": token})
        if resp.status_code >= 400:
            raise HTTPException(status_code=resp.status_code, detail=f"ClickUp API: {resp.text}")
        return resp.json()


# ─────────────────────────────────────────────
# Auth / Connection
# ─────────────────────────────────────────────

@router.get("/connect/oauth-url")
async def get_oauth_url():
    """Generate the OAuth URL to start the ClickUp connection flow."""
    url = (
        f"https://app.clickup.com/api"
        f"?client_id={settings.CLICKUP_CLIENT_ID}"
        f"&redirect_uri={settings.CLICKUP_REDIRECT_URI}"
    )
    return {"oauth_url": url}


@router.post("/connect/oauth-callback")
async def oauth_callback(user: CurrentUser, code: str = Body(..., embed=True)):
    """Exchange OAuth authorization code for an access token and store it."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        token_resp = await client.post(
            "https://api.clickup.com/api/v2/oauth/token",
            data={
                "client_id": settings.CLICKUP_CLIENT_ID,
                "client_secret": settings.CLICKUP_CLIENT_SECRET,
                "code": code,
            }
        )
        if token_resp.status_code != 200:
            raise HTTPException(status_code=400, detail=f"Failed to get ClickUp token: {token_resp.text}")
        access_token = token_resp.json().get("access_token")

    workspaces_data = await _cu_get("/team", access_token)
    first_workspace = workspaces_data.get("teams", [{}])[0]
    workspace_id = first_workspace.get("id", "")
    workspace_name = first_workspace.get("name", "")

    org_id = _get_org_id(user)
    supabase = get_supabase()
    supabase.table("clickup_connections").upsert({
        "organization_id": org_id,
        "access_token": access_token,
        "clickup_workspace_id": workspace_id,
        "clickup_workspace_name": workspace_name,
    }, on_conflict="organization_id").execute()

    return {"message": "ClickUp connected successfully", "workspace_name": workspace_name}


@router.post("/connect/personal-token")
async def connect_personal_token(user: CurrentUser, token: str = Body(..., embed=True)):
    """Connect using a ClickUp Personal API Token (pk_...) — great for testing."""
    workspaces_data = await _cu_get("/team", token)
    first_workspace = workspaces_data.get("teams", [{}])[0]
    if not first_workspace:
        raise HTTPException(status_code=400, detail="Invalid token or no workspaces found.")
    workspace_id = first_workspace.get("id", "")
    workspace_name = first_workspace.get("name", "")

    org_id = _get_org_id(user)
    supabase = get_supabase()
    supabase.table("clickup_connections").upsert({
        "organization_id": org_id,
        "access_token": token,
        "clickup_workspace_id": workspace_id,
        "clickup_workspace_name": workspace_name,
    }, on_conflict="organization_id").execute()

    return {"message": f"Connected to ClickUp workspace '{workspace_name}'"}


@router.get("/status")
async def connection_status(user: CurrentUser):
    """Check connection status for the current user's org."""
    org_id = _get_org_id(user)
    supabase = get_supabase()
    res = supabase.table("clickup_connections").select(
        "clickup_workspace_id, clickup_workspace_name, updated_at"
    ).eq("organization_id", org_id).limit(1).execute()
    if res.data:
        return {"connected": True, **res.data[0]}
    return {"connected": False}


@router.delete("/disconnect")
async def disconnect(user: CurrentUser):
    """Disconnect ClickUp from this org."""
    org_id = _get_org_id(user)
    supabase = get_supabase()
    supabase.table("clickup_connections").delete().eq("organization_id", org_id).execute()
    return {"message": "ClickUp disconnected."}


# ─────────────────────────────────────────────
# Hierarchy Proxy (Read)
# ─────────────────────────────────────────────

@router.get("/workspaces")
async def get_workspaces(user: CurrentUser):
    """List all ClickUp Workspaces for the connected account."""
    token = _get_token(_get_org_id(user))
    data = await _cu_get("/team", token)
    return data.get("teams", [])


@router.get("/workspaces/{workspace_id}/spaces")
async def get_spaces(workspace_id: str, user: CurrentUser):
    """List all Spaces in a ClickUp Workspace."""
    token = _get_token(_get_org_id(user))
    data = await _cu_get(f"/team/{workspace_id}/space?archived=false", token)
    return data.get("spaces", [])


@router.get("/spaces/{space_id}/folders")
async def get_folders(space_id: str, user: CurrentUser):
    """List all Folders in a Space."""
    token = _get_token(_get_org_id(user))
    data = await _cu_get(f"/space/{space_id}/folder?archived=false", token)
    return data.get("folders", [])


@router.get("/spaces/{space_id}/lists")
async def get_lists_in_space(space_id: str, user: CurrentUser):
    """List all Lists directly in a Space (folderless)."""
    token = _get_token(_get_org_id(user))
    data = await _cu_get(f"/space/{space_id}/list?archived=false", token)
    return data.get("lists", [])


@router.get("/folders/{folder_id}/lists")
async def get_lists_in_folder(folder_id: str, user: CurrentUser):
    """List all Lists inside a Folder."""
    token = _get_token(_get_org_id(user))
    data = await _cu_get(f"/folder/{folder_id}/list?archived=false", token)
    return data.get("lists", [])


@router.get("/lists/{list_id}/tasks")
async def get_tasks(list_id: str, user: CurrentUser, page: int = 0, subtasks: bool = True):
    """List all Tasks in a List."""
    token = _get_token(_get_org_id(user))
    data = await _cu_get(
        f"/list/{list_id}/task?archived=false&include_closed=true&subtasks={str(subtasks).lower()}&page={page}",
        token
    )
    return data.get("tasks", [])


@router.get("/tasks/{task_id}")
async def get_task(task_id: str, user: CurrentUser):
    """Get full details for a single ClickUp task including custom fields."""
    token = _get_token(_get_org_id(user))
    return await _cu_get(f"/task/{task_id}", token)


# ─────────────────────────────────────────────
# Task Mutations (Write-through to ClickUp)
# ─────────────────────────────────────────────

@router.post("/lists/{list_id}/tasks")
async def create_task(list_id: str, user: CurrentUser, body: dict = Body(...)):
    """Create a new task in a ClickUp List."""
    token = _get_token(_get_org_id(user))
    return await _cu_post(f"/list/{list_id}/task", token, body)


@router.put("/tasks/{task_id}")
async def update_task(task_id: str, user: CurrentUser, body: dict = Body(...)):
    """Update a ClickUp task (status, assignees, fields, etc.)."""
    token = _get_token(_get_org_id(user))
    return await _cu_put(f"/task/{task_id}", token, body)


@router.delete("/tasks/{task_id}")
async def delete_task(task_id: str, user: CurrentUser):
    """Delete a ClickUp task."""
    token = _get_token(_get_org_id(user))
    return await _cu_delete(f"/task/{task_id}", token)


@router.post("/tasks/{task_id}/comment")
async def add_comment(task_id: str, user: CurrentUser, body: dict = Body(...)):
    """Add a comment to a ClickUp task."""
    token = _get_token(_get_org_id(user))
    return await _cu_post(f"/task/{task_id}/comment", token, body)


# ─────────────────────────────────────────────
# RACI Augmentation (Pandora-side storage)
# ─────────────────────────────────────────────

@router.get("/tasks/{task_id}/raci")
async def get_raci(task_id: str, user: CurrentUser):
    """Get the RACI matrix for a ClickUp task (stored in Pandora DB)."""
    supabase = get_supabase()
    org_id = _get_org_id(user)
    res = supabase.table("task_raci").select("*").eq("clickup_task_id", task_id).eq("organization_id", org_id).limit(1).execute()
    return res.data[0] if res.data else {}


@router.post("/tasks/{task_id}/raci")
async def upsert_raci(task_id: str, user: CurrentUser, body: dict = Body(...)):
    """Create or update RACI matrix for a ClickUp task."""
    org_id = _get_org_id(user)
    supabase = get_supabase()
    payload = {
        "organization_id": org_id,
        "clickup_task_id": task_id,
        "responsible_user_id": body.get("responsible_user_id"),
        "accountable_user_id": body.get("accountable_user_id"),
        "consulted_user_ids": body.get("consulted_user_ids", []),
        "informed_user_ids": body.get("informed_user_ids", []),
    }
    supabase.table("task_raci").upsert(payload, on_conflict="organization_id,clickup_task_id").execute()
    return {"message": "RACI updated."}


# ─────────────────────────────────────────────
# ClickUp Webhook Listener (no auth needed – public endpoint)
# ─────────────────────────────────────────────

@router.post("/webhook")
async def clickup_webhook(body: dict = Body(...)):
    """
    Receive real-time task events from ClickUp.
    - taskStatusChanged: if status becomes 'closed/complete', triggers AI changelog.
    - taskCreated / taskUpdated: re-ingest task into Weaviate for AI search.
    """
    event = body.get("event", "")
    task_id = body.get("task_id")
    print(f"[ClickUp Webhook] event={event}, task_id={task_id}")

    if event == "taskStatusChanged":
        history_items = body.get("history_items", [])
        new_status = ""
        if history_items:
            new_status = history_items[0].get("after", {}).get("status", "").lower()
        if new_status in ("closed", "complete", "completed", "done"):
            try:
                from app.services.clickup_ai_service import trigger_changelog_for_task
                await trigger_changelog_for_task(task_id)
                print(f"[ClickUp Webhook] AI changelog triggered for task {task_id}")
            except Exception as e:
                print(f"[ClickUp Webhook] Changelog error: {e}")

    if event in ("taskCreated", "taskUpdated", "taskCommentPosted"):
        try:
            from app.services.clickup_ai_service import ingest_clickup_task
            await ingest_clickup_task(task_id)
            print(f"[ClickUp Webhook] Weaviate ingest done for task {task_id}")
        except Exception as e:
            print(f"[ClickUp Webhook] Weaviate ingestion error: {e}")

    return {"received": True}
