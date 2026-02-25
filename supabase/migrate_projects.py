import asyncio
import os
import sys

# Add the backend root to the python path so imports work
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.config import settings

async def run_migration():
    psql_url = os.environ.get("DATABASE_URL")
    
    if not psql_url:
        print("ERROR: DATABASE_URL not found in environment.")
        sys.exit(1)
        
    try:
        import asyncpg
    except ImportError:
        print("asyncpg not installed.")
        sys.exit(1)

    sql = """
    -- 1. Create project_domains table
    CREATE TABLE IF NOT EXISTS project_domains (
        project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
        domain_id UUID REFERENCES domains(id) ON DELETE CASCADE,
        PRIMARY KEY (project_id, domain_id)
    );

    -- 2. Backfill existing data
    -- Only works if the column domain_id still exists
    DO $$
    BEGIN
        IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='projects' AND column_name='domain_id') THEN
            EXECUTE 'INSERT INTO project_domains (project_id, domain_id) SELECT id, domain_id FROM projects WHERE domain_id IS NOT NULL ON CONFLICT DO NOTHING;';
        END IF;
    END
    $$;

    -- 3. Drop domain_id from projects
    ALTER TABLE projects DROP COLUMN IF EXISTS domain_id;

    -- 4. Add domain_id to documents
    ALTER TABLE documents ADD COLUMN IF NOT EXISTS domain_id UUID REFERENCES domains(id) ON DELETE SET NULL;
    """

    print("Executing project_domains data migration...")
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
