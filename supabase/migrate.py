import asyncio
import os
import sys

# Add the backend root to the python path so imports work
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings
from supabase import create_client, Client

async def run_migration():
    print(f"Connecting to Supabase at {settings.SUPABASE_URL}...")
    
    # We must use the SERVICE_ROLE_KEY to bypass RLS and execute schema changes
    # If the current key is the Anon Key, things might fail without Postgres connection strings,
    # but the Supabase REST API has a /rpc endpoint we can use if we wrap the SQL in a Postgres function.
    
    # Actually, supabase-py doesn't currently support raw SQL execution natively without postgres:// connection strings
    # or having RPC functions pre-defined in the DB.
    # We will try to execute it by falling back to `psycopg2` or `asyncpg` if the connection string is present,
    # otherwise we have to inform the user.
    
    psql_url = os.environ.get("DATABASE_URL")
    
    if not psql_url:
        print("ERROR: In order to execute raw DDL (CREATE TABLE) statements programmatically,")
        print("I need a direct Postgres connection string (DATABASE_URL) exported as an environment variable.")
        print("Since I don't see one, please copy the contents of `backend/supabase/schema.sql`")
        print("and run it in your Supabase SQL Editor manually!")
        sys.exit(1)
        
    try:
        import asyncpg
    except ImportError:
        print("asyncpg not installed, but required for direct Postgres schema building.")
        sys.exit(1)

    with open(os.path.join(os.path.dirname(__file__), "schema.sql"), "r") as f:
        sql = f.read()

    print("Executing schema.sql...")
    conn = await asyncpg.connect(psql_url)
    try:
        await conn.execute(sql)
        print("Schema applied successfully!")
    except Exception as e:
        print(f"Failed to apply schema: {e}")
    finally:
        await conn.close()

if __name__ == "__main__":
    asyncio.run(run_migration())
