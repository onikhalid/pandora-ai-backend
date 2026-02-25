import asyncio
from app.db.weaviate import get_weaviate_client
import weaviate.classes as wvc

def test():
    client = get_weaviate_client()
    try:
        col = client.collections.get("DocumentNode")
        with col.batch.dynamic() as batch:
            batch.add_object(
                properties={
                    "content": "test content",
                    "document_id": "test-id",
                    "organization_id": None,
                    "source_type": "REGULAR",
                    "external_id": "",
                    "created_at": None,
                    "domain_id": None
                }
            )
        
        if len(col.batch.failed_objects) > 0:
            print("Failed objects:")
            for f in col.batch.failed_objects:
                print(f.message)
        else:
            print("Inserted successfully")
            print(col.query.fetch_objects(limit=1).objects)
    finally:
        client.close()

if __name__ == "__main__":
    test()
