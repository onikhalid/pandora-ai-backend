import os
import httpx
from typing import Dict, Any, Optional

from app.db.supabase import get_supabase

class FreshchatMCPClient:
    """
    Client for interacting with the Freshchat MCP server or direct API.
    Used for the Self-Healing Customer Service flow to draft replies.
    """
    def __init__(self, organization_id: str, domain: Optional[str] = None):
        self.organization_id = organization_id
        self.token = self._fetch_token("freshchat")
        self.domain = domain or "api.freshchat.com"
        self.base_url = f"https://{self.domain}/v2"
        
    def _fetch_token(self, provider: str) -> Optional[str]:
        supabase = get_supabase()
        response = supabase.table("organization_integrations").select("encrypted_token").eq("organization_id", self.organization_id).eq("provider", provider).execute()
        if getattr(response, "data", None) and len(response.data) > 0:
            return response.data[0]["encrypted_token"]
        return None

    async def inject_draft_reply(self, conversation_id: str, suggested_text: str) -> Dict[str, Any]:
        """Injects a Weaviate-sourced drafted reply directly into the agent UI as a private note/draft."""
        if not self.token:
            raise ValueError(f"No Freshchat API token found for organization {self.organization_id}")
            
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
            "accept": "application/json"
        }
        
        # In Freshchat, 'private' messages are internal notes which serve as drafts
        payload = {
            "message_parts": [{"text": {"content": f"[PANDORA Suggested Reply] {suggested_text}"}}],
            "message_type": "private"
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{self.base_url}/conversations/{conversation_id}/messages",
                headers=headers,
                json=payload
            )
            if response.status_code in [200, 201]:
                return response.json()
            return {"error": response.text}
