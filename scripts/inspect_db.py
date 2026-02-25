import asyncio
from app.db.weaviate import get_weaviate_client

def test():
    client = get_weaviate_client()
    try:
        col = client.collections.get("DocumentNode")
        for item in col.iterator():
            print(item.properties)
            break
    finally:
        client.close()

if __name__ == "__main__":
    test()
