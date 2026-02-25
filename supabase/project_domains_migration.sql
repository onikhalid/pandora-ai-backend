-- 1. Add organization_id to projects (must do this FIRST so we know who owns what after dropping domain_id)
ALTER TABLE projects ADD COLUMN IF NOT EXISTS organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE;

-- 2. Backfill organization_id based on the existing domain_id
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='projects' AND column_name='domain_id') THEN
        EXECUTE 'UPDATE projects SET organization_id = d.organization_id FROM domains d WHERE projects.domain_id = d.id;';
    END IF;
END
$$;

-- 3. Create project_domains table
CREATE TABLE IF NOT EXISTS project_domains (
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    domain_id UUID REFERENCES domains(id) ON DELETE CASCADE,
    PRIMARY KEY (project_id, domain_id)
);

-- 4. Backfill existing project domains
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='projects' AND column_name='domain_id') THEN
        EXECUTE 'INSERT INTO project_domains (project_id, domain_id) SELECT id, domain_id FROM projects WHERE domain_id IS NOT NULL ON CONFLICT DO NOTHING;';
    END IF;
END
$$;

-- 5. Drop the RLS Policies that break when dropping the column
DROP POLICY IF EXISTS "Members see public projects or assigned domain projects" ON projects;
DROP POLICY IF EXISTS "Admins/SuperAdmins can manage projects" ON projects;

-- 6. Drop domain_id from projects safely now
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='projects' AND column_name='domain_id') THEN
        ALTER TABLE projects DROP COLUMN domain_id CASCADE;
    END IF;
END
$$;

-- 7. Add domain_id to documents
ALTER TABLE documents ADD COLUMN IF NOT EXISTS domain_id UUID REFERENCES domains(id) ON DELETE SET NULL;

-- 8. Re-Create the RLS Policies using the new schema mapping
CREATE POLICY "Members see public projects or assigned domain projects" ON projects FOR SELECT USING (
    organization_id = get_my_org_id() AND
    (
        is_public = true 
        OR get_user_org_role(organization_id) IN ('admin', 'super_admin')
        OR EXISTS (
            SELECT 1 FROM project_domains pd
            WHERE pd.project_id = projects.id
              AND pd.domain_id = ANY(get_user_domain_ids(organization_id))
        )
    )
);

CREATE POLICY "Admins/SuperAdmins can manage projects" ON projects FOR ALL USING (
    organization_id = get_my_org_id() AND
    get_user_org_role(organization_id) IN ('admin', 'super_admin')
);

ALTER TABLE project_domains ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "Members can view project domains" ON project_domains;
CREATE POLICY "Members can view project domains" ON project_domains FOR SELECT USING (
    domain_id IN (SELECT id FROM domains WHERE organization_id = get_my_org_id())
);

DROP POLICY IF EXISTS "Admins can manage project domains" ON project_domains;
CREATE POLICY "Admins can manage project domains" ON project_domains FOR ALL USING (
    domain_id IN (SELECT id FROM domains WHERE organization_id = get_my_org_id() AND get_user_org_role(organization_id) IN ('admin', 'super_admin'))
);

-- 9. FORCE POSTGREST SCHEMA CACHE RELOAD
-- This tells the API layer to instantly recognize the new project_domains relationship.
NOTIFY pgrst, 'reload schema';
