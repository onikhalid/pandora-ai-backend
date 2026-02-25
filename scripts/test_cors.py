import os
from app.core.config import settings

def test():
    print(f"CORS Origins: {settings.CORS_ORIGINS}")
    print(f"Type: {type(settings.CORS_ORIGINS)}")

if __name__ == "__main__":
    test()
