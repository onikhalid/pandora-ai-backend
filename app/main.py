from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from app.api.routes import documents, crds, tickets, graphrag, users, projects, search, collaborators
from app.core.config import settings

from app.db.weaviate import init_weaviate_schema

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    try:
        print("Initializing PANDORA connections...")
        init_weaviate_schema()
        print("Weaviate schema check completed.")
    except Exception as e:
        print(f"Warning: Could not initialize Weaviate schema. Is Docker running? Error: {e}")
        
    yield
    print("Shutting down PANDORA API.")

app = FastAPI(
    title=settings.PROJECT_NAME,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

import traceback
from fastapi.responses import JSONResponse
from fastapi import Request

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    print(f"Global Exception caught on {request.url}:")
    traceback.print_exc()
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error", "error_type": str(type(exc))})

# Set all CORS enabled origins
if settings.CORS_ORIGINS:
    origins = [orig.strip() for orig in settings.CORS_ORIGINS.split(",") if orig.strip()]
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

app.include_router(documents.router, prefix=f"{settings.API_V1_STR}/documents", tags=["documents"])
app.include_router(crds.router, prefix=f"{settings.API_V1_STR}/crds", tags=["crds"])
app.include_router(tickets.router, prefix=f"{settings.API_V1_STR}/tickets", tags=["tickets"])
app.include_router(graphrag.router, prefix=f"{settings.API_V1_STR}/graphrag", tags=["graphrag"])
app.include_router(users.router, prefix=f"{settings.API_V1_STR}/users", tags=["users"])
app.include_router(projects.router, prefix=f"{settings.API_V1_STR}/projects", tags=["projects"])
app.include_router(search.router, prefix=f"{settings.API_V1_STR}/search", tags=["search"])
app.include_router(collaborators.router, prefix=f"{settings.API_V1_STR}/documents", tags=["collaborators"])

@app.get(f"{settings.API_V1_STR}/test_weaviate")
def test_weaviate_connection():
    from app.db.weaviate import get_weaviate_client
    import os
    try:
        client = get_weaviate_client()
        client.connect()
        is_ready = client.is_ready()
        
        url = settings.WEAVIATE_URL
        scheme = "https" if url.startswith("https") else "http"
        host_port = url.replace(f"{scheme}://", "").split(":")
        host = host_port[0].strip('/')
        port = int(host_port[1].strip('/')) if len(host_port) > 1 else (443 if scheme == "https" else 8080)
        grpc_host = os.environ.get("WEAVIATE_GRPC_HOST", host)
        grpc_port = int(os.environ.get("WEAVIATE_GRPC_PORT", 50051))
        
        info = {
            "status": "success" if is_ready else "not_ready",
            "weaviate_url_env": settings.WEAVIATE_URL,
            "parsed_http": f"{scheme}://{host}:{port}",
            "parsed_grpc": f"{grpc_host}:{grpc_port}",
            "grpc_secure": str(scheme == "https" and os.environ.get("WEAVIATE_GRPC_SECURE", "false").lower() == "true")
        }
        client.close()
        return info
    except Exception as e:
        url = settings.WEAVIATE_URL
        scheme = "https" if url.startswith("https") else "http"
        host_port = url.replace(f"{scheme}://", "").split(":")
        host = host_port[0].strip('/')
        port = int(host_port[1].strip('/')) if len(host_port) > 1 else (443 if scheme == "https" else 8080)
        grpc_host = os.environ.get("WEAVIATE_GRPC_HOST", host)
        grpc_port = int(os.environ.get("WEAVIATE_GRPC_PORT", 50051))
        return {
            "status": "error",
            "error_type": str(type(e)),
            "error_message": str(e),
            "weaviate_url_env": settings.WEAVIATE_URL,
            "parsed_http": f"{scheme}://{host}:{port}",
            "parsed_grpc": f"{grpc_host}:{grpc_port}"
        }
@app.get("/")
def health_check():
    return {"status": "ok", "app": settings.PROJECT_NAME}
