import os
import httpx
from typing import Dict, Any, Optional

from app.db.supabase import get_supabase

class ClickUpMCPClient:
    """
    Client for interacting with the ClickUp MCP server or direct API.
    Used for automatically generating tasks from CRDs and tracing them back to PRDs.
    """
    def __init__(self, organization_id: str):
        self.organization_id = organization_id
        self.token = self._fetch_token("clickup_workspace")
        self.base_url = "https://api.clickup.com/api/v2"

    def _fetch_token(self, provider: str) -> Optional[str]:
        supabase = get_supabase()
        response = supabase.table("organization_integrations").select("encrypted_token").eq("organization_id", self.organization_id).eq("provider", provider).execute()
        if getattr(response, "data", None) and len(response.data) > 0:
            return response.data[0]["encrypted_token"]
        return None
        
    async def create_task(self, list_id: str, name: str, description: str) -> Dict[str, Any]:
        """Creates an engineering task from a drafted CRD."""
        if not self.token:
            raise ValueError(f"No ClickUp API token found for organization {self.organization_id}")
            
        headers = {
            "Authorization": f"{self.token}",
            "Content-Type": "application/json"
        }
        payload = {
            "name": name,
            "description": description,
            "status": "TO DO"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/list/{list_id}/task",
                headers=headers,
                json=payload
            )
            if response.status_code == 200:
                return response.json()
            return {"error": response.text}
