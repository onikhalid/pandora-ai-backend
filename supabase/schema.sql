-- PANDORA Supabase Schema and RLS Setup
-- Warning: Ensure you are running this against a fresh database or carefully handle existing data!

-- 1. ENUMS (Dropping existing if necessary)
DROP TYPE IF EXISTS org_role CASCADE;
DROP TYPE IF EXISTS user_role CASCADE;
DROP TYPE IF EXISTS document_status CASCADE;
DROP TYPE IF EXISTS crd_status CASCADE;

CREATE TYPE org_role AS ENUM ('super_admin', 'admin', 'member');
CREATE TYPE user_role AS ENUM ('owner', 'contributor', 'viewer');
CREATE TYPE document_status AS ENUM ('draft', 'in_review', 'published', 'archived');
CREATE TYPE crd_status AS ENUM ('pending', 'approved', 'rejected');

-- 2. TABLES (Dropping existing to force schema upgrade!)

DROP TABLE IF EXISTS crds CASCADE;
DROP TABLE IF EXISTS document_versions CASCADE;
DROP TABLE IF EXISTS documents CASCADE;
DROP TABLE IF EXISTS project_users CASCADE;
DROP TABLE IF EXISTS projects CASCADE;
DROP TABLE IF EXISTS organization_integrations CASCADE;
DROP TABLE IF EXISTS user_identities CASCADE;
DROP TABLE IF EXISTS domains CASCADE;
DROP TABLE IF EXISTS organization_users CASCADE;
DROP TABLE IF EXISTS support_tickets CASCADE;
DROP TABLE IF EXISTS organizations CASCADE;

-- Organization (Tenant)
CREATE TABLE IF NOT EXISTS organizations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Domain (Departments - configurable by Org Admins)
CREATE TABLE IF NOT EXISTS domains (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Organization Users (Tenant Membership)
CREATE TABLE IF NOT EXISTS organization_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    user_id UUID NOT NULL, -- References auth.users later via application logic if not direct FK
    role org_role NOT NULL DEFAULT 'member',
    email TEXT NOT NULL, -- Keep email handy for pending invites MVP
    status TEXT DEFAULT 'active', -- 'pending' or 'active' MVP flag
    domain_ids UUID[] DEFAULT '{}', -- An array of department IDs they belong to. Super Admins ignore this.
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(organization_id, user_id)
);

-- External User Identities (Mapping PANDORA accounts to external integrators)
CREATE TABLE IF NOT EXISTS user_identities (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL, 
    provider TEXT NOT NULL, -- e.g., 'github', 'clickup', 'figma'
    provider_id TEXT NOT NULL, 
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(user_id, provider)
);

-- Organization Integrations (Tenant-wide API Access for MCP)
CREATE TABLE IF NOT EXISTS organization_integrations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    provider TEXT NOT NULL, 
    encrypted_token TEXT NOT NULL, 
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(organization_id, provider)
);


-- Project
CREATE TABLE IF NOT EXISTS projects (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    description TEXT,
    github_repo TEXT, 
    is_public BOOLEAN DEFAULT false, 
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Project Domains (Many-to-Many mapping for Cross-Department Projects)
CREATE TABLE IF NOT EXISTS project_domains (
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    domain_id UUID REFERENCES domains(id) ON DELETE CASCADE,
    PRIMARY KEY (project_id, domain_id)
);

-- User Role Mapping
CREATE TABLE IF NOT EXISTS project_users (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    user_id UUID NOT NULL, 
    role user_role NOT NULL DEFAULT 'viewer',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(project_id, user_id)
);

-- Document (Metadata only)
CREATE TABLE IF NOT EXISTS documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE, 
    domain_id UUID REFERENCES domains(id) ON DELETE SET NULL,
    owner_id UUID NOT NULL, 
    title TEXT NOT NULL,
    type TEXT NOT NULL,
    status document_status DEFAULT 'draft',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Document Versions (Infinite History)
CREATE TABLE IF NOT EXISTS document_versions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    content_text TEXT NOT NULL,
    created_by UUID NOT NULL, 
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Change Request Document (CRD - generated between two versions)
CREATE TABLE IF NOT EXISTS crds (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    project_id UUID REFERENCES projects(id) ON DELETE CASCADE,
    status crd_status DEFAULT 'pending',
    changes_summary TEXT,
    lineage_data JSONB,
    ai_reasoning TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Support Ticket
CREATE TABLE IF NOT EXISTS support_tickets (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID REFERENCES organizations(id) ON DELETE CASCADE,
    urgency TEXT,
    category TEXT,
    resolution_status TEXT DEFAULT 'open',
    query_text TEXT,
    resolution_text TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- 3. ROW LEVEL SECURITY (RLS) POLICIES

-- Helper Functions (all SECURITY DEFINER to bypass RLS when called internally)

-- Returns the current user's organization_id without triggering RLS recursion
CREATE OR REPLACE FUNCTION get_my_org_id()
RETURNS UUID AS $$
    SELECT organization_id FROM organization_users 
    WHERE user_id = auth.uid() 
    LIMIT 1;
$$ LANGUAGE sql SECURITY DEFINER STABLE;

CREATE OR REPLACE FUNCTION get_user_org_role(org_id UUID)
RETURNS org_role AS $$
    SELECT organization_users.role FROM organization_users 
    WHERE organization_users.organization_id = $1 AND organization_users.user_id = auth.uid() 
    LIMIT 1;
$$ LANGUAGE sql SECURITY DEFINER STABLE;

CREATE OR REPLACE FUNCTION get_user_domain_ids(org_id UUID)
RETURNS UUID[] AS $$
    SELECT organization_users.domain_ids FROM organization_users 
    WHERE organization_users.organization_id = $1 AND organization_users.user_id = auth.uid() 
    LIMIT 1;
$$ LANGUAGE sql SECURITY DEFINER STABLE;


-- Organizations (Anyone can create, only members can view)
ALTER TABLE organizations ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can create orgs" ON organizations FOR INSERT WITH CHECK (true);
CREATE POLICY "Users can view orgs they belong to" ON organizations FOR SELECT USING (
    id = get_my_org_id()
);
CREATE POLICY "Super Admins can update orgs" ON organizations FOR UPDATE USING (
    get_user_org_role(id) = 'super_admin'
);

-- Organization Users
-- KEY FIX: Use get_my_org_id() (SECURITY DEFINER) instead of a self-referential subquery
-- that would cause infinite recursion (policy querying itself indefinitely).
ALTER TABLE organization_users ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Users can read fellow org members" ON organization_users FOR SELECT USING (
    organization_id = get_my_org_id()
);
CREATE POLICY "Anyone can insert themselves during onboarding" ON organization_users FOR INSERT WITH CHECK (
    user_id = auth.uid()
);
CREATE POLICY "SuperAdmins and Admins can update org users" ON organization_users FOR UPDATE USING (
    get_user_org_role(organization_id) IN ('super_admin', 'admin')
);
CREATE POLICY "SuperAdmins can delete org users" ON organization_users FOR DELETE USING (
    get_user_org_role(organization_id) = 'super_admin'
);

-- Domains (Departments)
ALTER TABLE domains ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Members can view org domains" ON domains FOR SELECT USING (
    organization_id IN (SELECT organization_id FROM organization_users WHERE user_id = auth.uid())
);
CREATE POLICY "SuperAdmins and Admins can manage domains" ON domains FOR ALL USING (
    get_user_org_role(organization_id) IN ('super_admin', 'admin')
);

-- Projects
ALTER TABLE projects ENABLE ROW LEVEL SECURITY;
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

-- Project Domains
ALTER TABLE project_domains ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Members can view project domains" ON project_domains FOR SELECT USING (
    domain_id IN (SELECT id FROM domains WHERE organization_id = get_my_org_id())
);

CREATE POLICY "Admins can manage project domains" ON project_domains FOR ALL USING (
    domain_id IN (SELECT id FROM domains WHERE organization_id = get_my_org_id() AND get_user_org_role(organization_id) IN ('admin', 'super_admin'))
);

-- Documents
ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Members can view org documents" ON documents FOR SELECT USING (
    organization_id IN (SELECT organization_id FROM organization_users WHERE user_id = auth.uid())
);
CREATE POLICY "Members can create and update their OWN documents" ON documents FOR ALL USING (
    owner_id = auth.uid() 
);
CREATE POLICY "Super Admins can manage ALL documents" ON documents FOR ALL USING (
    get_user_org_role(organization_id) = 'super_admin'
);

-- Note: In production, further granular policies on project_users, crds, and tickets follow the same pattern 
-- checking 'auth.uid()' against the mapped foreign keys!
