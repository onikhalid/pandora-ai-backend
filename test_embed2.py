from app.core.config import settings
from langchain_google_genai import GoogleGenerativeAIEmbeddings

try:
    embeddings = GoogleGenerativeAIEmbeddings(model="models/gemini-embedding-001", google_api_key=settings.GOOGLE_API_KEY)
    v = embeddings.embed_query("hello")
    print(f"SUCCESS: {len(v)} dimensions")
except Exception as e:
    print(f"FAILED: {e}")
