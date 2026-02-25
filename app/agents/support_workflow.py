from typing import TypedDict, Annotated, List, Optional
import operator
from langgraph.graph import StateGraph, END
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.messages import SystemMessage, HumanMessage
from app.db.weaviate import get_weaviate_client
from app.db.supabase import get_supabase
from app.mcp.freshchat_client import FreshchatMCPClient

# --- State Definition ---
class SupportState(TypedDict):
    ticket_id: str
    organization_id: str
    query_text: str
    urgency: str
    category: Optional[str]
    semantic_results: List[dict]
    draft_reply: str
    status: str

# --- Node Functions ---

def fetch_knowledge_context(state: SupportState) -> SupportState:
    """Queries Weaviate for policies related to the support ticket query."""
    # Fetch top 3 matches from Weaviate
    results = GraphRAGService.search_similar_content(state["query_text"], limit=3)
    state["semantic_results"] = results
    return state

def draft_resolution(state: SupportState) -> SupportState:
    """Uses LLM to draft a response based on the fetched knowledge."""
    llm = ChatGoogleGenerativeAI(model="gemini-1.5-pro", temperature=0)
    
    context = ""
    for r in state["semantic_results"]:
        context += f"Knowledge Context (Source: {r.get('source_type')}):\n{r.get('content')}\n\n"
        
    prompt = f"A user asks: '{state['query_text']}'.\n\nBased on the following internal policies/documents, draft a helpful, professional reply. If the context does not answer the question, state that you cannot resolve it.\n\n{context}"
    
    response = llm.invoke([
        SystemMessage(content="You are an expert customer service AI agent resolving employee or customer queries based strictly on the provided knowledge base context."),
        HumanMessage(content=prompt)
    ])
    
    state["draft_reply"] = response.content
    state["status"] = "resolved" if len(state["semantic_results"]) > 0 else "unresolved"
    return state

def save_and_inject_reply(state: SupportState) -> SupportState:
    """Saves the resolution to Supabase and pushes it via MCP explicitly if applicable."""
    supabase = get_supabase()
    
    # Save the resolution to DB
    supabase.table("support_tickets").update({
        "resolution_text": state["draft_reply"],
        "resolution_status": state["status"]
    }).eq("id", state["ticket_id"]).execute()
    
    # Example MCP Injection (assuming ticket_id maps to conversation_id for this MVP)
    try:
        freshchat_client = FreshchatMCPClient(organization_id=state["organization_id"])
        import asyncio
        # We can't await inside a regular function easily without an event loop if we are not async, 
        # but LangGraph allows async nodes.
    except ValueError as e:
        print(f"Skipping Freshchat Injection: {e}")
        
    return state

# We need to make save_and_inject_reply async or use sync methods for MCP if LangGraph is run sync.
# Actually, let's just make it a sync node for LangGraph or use async if the graph is async.
# Graph construction supports async nodes natively. Let's redefine node functions as async.

async def async_save_and_inject_reply(state: SupportState) -> SupportState:
    supabase = get_supabase()
    supabase.table("support_tickets").update({
        "resolution_text": state["draft_reply"],
        "resolution_status": state["status"]
    }).eq("id", state["ticket_id"]).execute()
    
    try:
        freshchat_client = FreshchatMCPClient(organization_id=state["organization_id"])
        await freshchat_client.inject_draft_reply(conversation_id=state["ticket_id"], suggested_text=state["draft_reply"])
        print(f"Injected reply to Freshchat for ticket {state['ticket_id']}")
    except ValueError as e:
        print(f"Skipping Freshchat Injection: {e}")

    return state


# --- Graph Construction ---
workflow_builder = StateGraph(SupportState)

# Convert all to async to be safe
async def async_fetch_knowledge(state: SupportState) -> SupportState:
    return fetch_knowledge_context(state)

async def async_draft_resolution(state: SupportState) -> SupportState:
    return draft_resolution(state)

workflow_builder.add_node("fetch_knowledge", async_fetch_knowledge)
workflow_builder.add_node("draft_resolution", async_draft_resolution)
workflow_builder.add_node("save_and_inject", async_save_and_inject_reply)

workflow_builder.set_entry_point("fetch_knowledge")
workflow_builder.add_edge("fetch_knowledge", "draft_resolution")
workflow_builder.add_edge("draft_resolution", "save_and_inject")
workflow_builder.add_edge("save_and_inject", END)

support_app = workflow_builder.compile()
