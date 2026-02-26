from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "PANDORA API"
    API_V1_STR: str = "/api/v1"
    
    # CORS (Comma separated list of allowed origins)
    CORS_ORIGINS: str = "http://localhost:3000,http://127.0.0.1:3000,https://pandora-ai-frontend.vercel.app,https://pandora-ai.vercel.app,https://pandora.vercel.app"
    
    # Supabase (Loaded from .env)
    SUPABASE_URL: str = ""
    SUPABASE_KEY: str = ""
    SUPABASE_JWT_SECRET: str = ""

    # Weaviate (Defaults to docker-compose service name)
    WEAVIATE_URL: str = "http://weaviate:8080"
    
    # AI Secrets
    GOOGLE_API_KEY: str = ""
    
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

settings = Settings()
