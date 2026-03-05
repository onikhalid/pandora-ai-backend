import requests
from app.core.config import settings

url = f"https://generativelanguage.googleapis.com/v1beta/models?key={settings.GOOGLE_API_KEY}"
response = requests.get(url)
models = response.json().get("models", [])

for m in models:
    if "embedContent" in m.get("supportedGenerationMethods", []):
        print(f"FOUND VALID MODEL: {m['name']}")
