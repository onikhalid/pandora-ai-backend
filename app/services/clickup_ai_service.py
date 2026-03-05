"""
ClickUp AI Service
Handles async tasks triggered by ClickUp Webhooks:
1. ingest_clickup_task() → Vectorize task into Weaviate for AI search
2. trigger_changelog_for_task() → Generate an AI changelog entry when a task closes
"""
import httpx
from app.db.supabase import get_supabase
from app.services.graphrag_service import GraphRAGService
from app.core.config import settings

CLICKUP_API_BASE = "https://api.clickup.com/api/v2"


async def _fetch_task_with_token(task_id: str, token: str) -> dict:
    """Fetch a single task from ClickUp using a provided token."""
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.get(
            f"{CLICKUP_API_BASE}/task/{task_id}",
            headers={"Authorization": token}
        )
        if resp.status_code >= 400:
            raise Exception(f"ClickUp API error fetching task {task_id}: {resp.text}")
        return resp.json()


async def _get_token_for_task(task_id: str) -> tuple[str, str]:
    """
    Find the org that owns this ClickUp task by looking up all connected orgs.
    Returns (token, org_id).
    """
    supabase = get_supabase()
    connections = supabase.table("clickup_connections").select("organization_id, access_token").execute()
    if not connections.data:
        raise Exception("No ClickUp connections found in database.")
    
    # Try each org's token until we successfully fetch the task
    for conn in connections.data:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(
                    f"{CLICKUP_API_BASE}/task/{task_id}",
                    headers={"Authorization": conn["access_token"]}
                )
                if resp.status_code == 200:
                    return conn["access_token"], conn["organization_id"]
        except Exception:
            continue
    
    raise Exception(f"Could not find an org with access to task {task_id}")


async def ingest_clickup_task(task_id: str):
    """
    Vectorize a ClickUp task into Weaviate for AI search.
    Called from the webhook listener on taskCreated/taskUpdated.
    """
    token, org_id = await _get_token_for_task(task_id)
    task = await _fetch_task_with_token(task_id, token)
    
    title = task.get("name", "")
    description = task.get("description", "") or ""
    status = task.get("status", {}).get("status", "")
    assignees = ", ".join([a.get("username", "") for a in task.get("assignees", [])])
    list_name = task.get("list", {}).get("name", "")
    space_name = task.get("space", {}).get("id", "")
    
    # Build a rich text blob for embedding
    content = f"""Task: {title}
Status: {status}
List: {list_name}
Assignees: {assignees}
Description: {description}"""
    
    # Delete old vectors for this task first
    try:
        client = __import__("app.db.weaviate", fromlist=["get_weaviate_client"]).get_weaviate_client()
        collection = client.collections.get("DocumentNode")
        collection.data.delete_many(
            where=__import__("weaviate.classes.query", fromlist=["Filter"]).Filter.by_property("external_id").equal(task_id)
        )
    except Exception as e:
        print(f"[ClickUp AI] Could not clean old vectors for task {task_id}: {e}")
    
    # Ingest updated content
    GraphRAGService.ingest_document(
        document_id=task_id,
        content=content,
        organization_id=org_id,
        source_type="CLICKUP_TASK",
        external_id=task_id,
        created_at=str(task.get("date_created", "")),
    )
    print(f"[ClickUp AI] Weaviate: ingested task {task_id} ({title})")


async def trigger_changelog_for_task(task_id: str):
    """
    Generate an AI changelog entry when a task is closed/completed.
    Finds any Pandora documents linked to this task and generates
    an AI summary of the changes.
    """
    import google.generativeai as genai
    
    try:
        token, org_id = await _get_token_for_task(task_id)
        task = await _fetch_task_with_token(task_id, token)
    except Exception as e:
        print(f"[ClickUp AI] Cannot fetch task {task_id} for changelog: {e}")
        return

    task_name = task.get("name", "Unknown Task")
    description = task.get("description", "") or "No description provided."
    task_url = task.get("url", "")
    
    # Generate a concise AI summary of what this task accomplished
    genai.configure(api_key=settings.GOOGLE_API_KEY)
    model = genai.GenerativeModel("gemini-1.5-flash")
    prompt = f"""A ClickUp task was just marked as complete. Write a concise, professional 2-3 sentence changelog entry describing what was accomplished.

Task name: {task_name}
Task description: {description}

The changelog entry should be factual, past-tense, and written for a technical team audience."""
    
    try:
        response = model.generate_content(prompt)
        ai_summary = response.text.strip()
    except Exception as e:
        ai_summary = f"Task '{task_name}' was marked as complete."
        print(f"[ClickUp AI] Gemini summary failed, using fallback: {e}")
    
    # Find any Pandora documents linked to this task
    supabase = get_supabase()
    docs_res = supabase.table("documents").select("id").eq("organization_id", org_id).execute()
    
    if docs_res.data:
        # Store the changelog entry against the first document in the org
        # In a full implementation, tasks would be explicitly linked to docs
        doc_id = docs_res.data[0]["id"]
        supabase.table("task_changelog_entries").insert({
            "organization_id": org_id,
            "document_id": doc_id,
            "clickup_task_id": task_id,
            "clickup_task_name": task_name,
            "clickup_task_url": task_url,
            "ai_summary": ai_summary,
        }).execute()
        print(f"[ClickUp AI] Changelog entry created for task '{task_name}'")
    else:
        print(f"[ClickUp AI] No documents found for org {org_id} to attach changelog.")
