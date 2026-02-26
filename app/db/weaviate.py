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
    host = host_port[0].strip('/')
    port = int(host_port[1].strip('/')) if len(host_port) > 1 else (443 if scheme == "https" else 8080)
    
    # Check for explicit GRPC variables (e.g. if routing via a public proxy)
    import os
    grpc_host = os.environ.get("WEAVIATE_GRPC_HOST", host)
    grpc_port = int(os.environ.get("WEAVIATE_GRPC_PORT", 50051))
    
    print(f"Connecting to Weaviate -> HTTP: {scheme}://{host}:{port} | GRPC: {grpc_host}:{grpc_port}")
    
    client = weaviate.connect_to_custom(
        http_host=host,
        http_port=port,
        http_secure=(scheme == "https"),
        grpc_host=grpc_host,
        grpc_port=grpc_port,
        grpc_secure=(scheme == "https" and os.environ.get("WEAVIATE_GRPC_SECURE", "false").lower() == "true"),
        skip_init_checks=True
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
            # Using external embeddings (Google GenAI) computed in Python, so Weaviate is just a vector store
            vectorizer_config=wvc.config.Configure.Vectorizer.none()
        )
        print("DocumentNode collection created.")
            
        # In a full GraphRAG, you'd define edges (CrossReferences/References) here
        # E.g. DocumentNode -> references -> DocumentNode
        
    finally:
        client.close()
