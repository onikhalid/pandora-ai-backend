from app.core.config import settings
from langchain_google_genai import GoogleGenerativeAIEmbeddings

models = ["models/embedding-001", "models/text-embedding-004", "text-embedding-004"]
for m in models:
    try:
        embeddings = GoogleGenerativeAIEmbeddings(model=m, google_api_key=settings.GOOGLE_API_KEY)
        query_vector = embeddings.embed_query("test query")
        print(f"SUCCESS: {m}")
    except Exception as e:
        print(f"FAILED: {m} - {e}")
