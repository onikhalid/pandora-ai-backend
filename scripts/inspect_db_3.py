import asyncio
from app.db.weaviate import get_weaviate_client
import weaviate.classes as wvc

def test():
    client = get_weaviate_client()
    try:
        col = client.collections.get("DocumentNode")
        res = col.query.fetch_objects(
            filters=wvc.query.Filter.by_property("document_id").equal("1eb32161-00b1-4585-a21b-6a74b828f6be"),
            limit=10
        )
        print(f"Found {len(res.objects)} chunks for 1eb32161-00b1-4585-a21b-6a74b828f6be")
        if res.objects:
            print(res.objects[0].properties)
            print(f"Has Vector: {bool(res.objects[0].vector)}")
            if res.objects[0].vector:
                vec0 = list(res.objects[0].vector.values())[0] if isinstance(res.objects[0].vector, dict) else res.objects[0].vector
                print(f"Vector Length: {len(vec0)}")
    finally:
        client.close()

if __name__ == "__main__":
    test()
