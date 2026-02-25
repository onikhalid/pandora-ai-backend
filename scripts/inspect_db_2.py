import asyncio
from app.db.weaviate import get_weaviate_client

def test():
    client = get_weaviate_client()
    try:
        col = client.collections.get("DocumentNode")
        for item in col.iterator():
            print(f"ID inside weaviate: {item.properties.get('document_id')}")
            content = item.properties.get('content', '')
            print(f"Content length: {len(content)}")
            print(f"Content snippet: {content[:100]}")
            print("-" * 40)
    finally:
        client.close()

if __name__ == "__main__":
    test()
