from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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

@app.get("/")
def health_check():
    return {"status": "ok", "app": settings.PROJECT_NAME}
