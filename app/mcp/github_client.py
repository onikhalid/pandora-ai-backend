import os
import httpx
from typing import Dict, Any, Optional

from app.db.supabase import get_supabase

class GitHubMCPClient:
    """
    Client for interacting with the GitHub MCP server or direct API.
    Used for tracing code commits back to PRD changes.
    """
    def __init__(self, organization_id: str):
        self.organization_id = organization_id
        self.token = self._fetch_token("github_app")
        self.base_url = "https://api.github.com"
        
    def _fetch_token(self, provider: str) -> Optional[str]:
        supabase = get_supabase()
        response = supabase.table("organization_integrations").select("encrypted_token").eq("organization_id", self.organization_id).eq("provider", provider).execute()
        if getattr(response, "data", None) and len(response.data) > 0:
            return response.data[0]["encrypted_token"]
        return None
        
    async def fetch_recent_commits(self, repo: str) -> Dict[str, Any]:
        if not self.token:
            raise ValueError(f"No GitHub API token found for organization {self.organization_id}")
            
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github.v3+json"
        }
        async with httpx.AsyncClient() as client:
            response = await client.get(f"{self.base_url}/repos/{repo}/commits", headers=headers)
            if response.status_code == 200:
                return response.json()
            return {"error": response.text}
