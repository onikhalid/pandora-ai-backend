import weaviate
import weaviate.classes as wvc
from app.core.config import settings

def get_weaviate_client():
    """
    Returns a configured Weaviate Python Client (v4).
    Connects to the WEAVIATE_URL defined in settings.
    """
    url = settings.WEAVIATE_URL
    scheme = "https" if url.startswith("https") else "http"
    host_port = url.replace(f"{scheme}://", "").split(":")
    host = host_port[0]
    port = int(host_port[1]) if len(host_port) > 1 else (443 if scheme == "https" else 80)
    
    client = weaviate.connect_to_custom(
        http_host=host,
        http_port=port,
        http_secure=(scheme == "https"),
        grpc_host=host,
        grpc_port=50051,
        grpc_secure=False
    )
    return client

def init_weaviate_schema():
    """
    Initializes the GraphRAG classes in Weaviate if they don't exist,
    rebuilding them if needed to enforce the organization_id schema.
    """
    client = get_weaviate_client()
    try:
        # For development schema upgrades, we recreate. In production, use migrations.
        if client.collections.exists("DocumentNode"):
            client.collections.delete("DocumentNode")
             
        client.collections.create(
            name="DocumentNode",
            properties=[
                wvc.config.Property(name="content", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="document_id", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="source_type", data_type=wvc.config.DataType.TEXT), 
                wvc.config.Property(name="external_id", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="organization_id", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="created_at", data_type=wvc.config.DataType.TEXT),
                wvc.config.Property(name="domain_id", data_type=wvc.config.DataType.TEXT),
            ],
            # Need to index null states to allow filtering by is_none() for sandbox docs
            inverted_index_config=wvc.config.Configure.inverted_index(index_null_state=True),
            # Using local free transformers for vector embeddings
            vectorizer_config=wvc.config.Configure.Vectorizer.text2vec_transformers()
        )
        print("DocumentNode collection created.")
            
        # In a full GraphRAG, you'd define edges (CrossReferences/References) here
        # E.g. DocumentNode -> references -> DocumentNode
        
    finally:
        client.close()
