import sys
import os

# Add the backend root to the python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db.weaviate import init_weaviate_schema

if __name__ == "__main__":
    try:
        print("Starting Weaviate schema initialization...")
        init_weaviate_schema()
        print("Successfully initialized Weaviate schema.")
    except Exception as e:
        print(f"Error initializing Weaviate schema: {e}")
        sys.exit(1)
