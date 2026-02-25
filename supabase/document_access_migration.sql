-- Migration: Granular Document Access Control

-- 1. Update Enums (Adding 'pending_review' to document_status if not exists)
ALTER TYPE document_status ADD VALUE IF NOT EXISTS 'pending_review';

-- 2. Add new columns to documents
ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_public BOOLEAN DEFAULT false;

-- 3. Add new columns to document_versions
ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS author_id UUID;
ALTER TABLE document_versions ADD COLUMN IF NOT EXISTS status document_status DEFAULT 'draft';

-- Update existing versions to avoid null issues:
UPDATE document_versions SET status = 'published' WHERE status IS NULL OR status = 'draft';
UPDATE document_versions SET author_id = created_by WHERE author_id IS NULL;

-- 4. Create document_collaborators table
CREATE TABLE IF NOT EXISTS document_collaborators (
    document_id UUID REFERENCES documents(id) ON DELETE CASCADE,
    user_id UUID NOT NULL,
    role user_role NOT NULL DEFAULT 'viewer',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (document_id, user_id)
);

-- 5. Helper Functions for RLS (Security Definer to avoid infinite recursion loops)
CREATE OR REPLACE FUNCTION can_view_document(doc_id UUID)
RETURNS BOOLEAN AS $$
    SELECT EXISTS (
        SELECT 1 FROM documents d
        LEFT JOIN document_collaborators dc ON dc.document_id = d.id AND dc.user_id = auth.uid()
        WHERE d.id = $1 AND (
            d.is_public = true 
            OR (d.is_public_to_org = true AND can_view_org(d.organization_id))
            OR d.owner_id = auth.uid()
            OR dc.user_id IS NOT NULL
            OR get_user_org_role(d.organization_id) IN ('admin', 'super_admin')
        )
    );
$$ LANGUAGE sql SECURITY DEFINER STABLE;

CREATE OR REPLACE FUNCTION can_manage_document(doc_id UUID)
RETURNS BOOLEAN AS $$
    SELECT EXISTS (
        SELECT 1 FROM documents d
        LEFT JOIN document_collaborators dc ON dc.document_id = d.id AND dc.user_id = auth.uid()
        WHERE d.id = $1 AND (
            d.owner_id = auth.uid()
            OR dc.role = 'contributor'::user_role
            OR get_user_org_role(d.organization_id) IN ('admin', 'super_admin')
        )
    );
$$ LANGUAGE sql SECURITY DEFINER STABLE;

CREATE OR REPLACE FUNCTION can_view_org(org_id UUID)
RETURNS BOOLEAN AS $$
    SELECT EXISTS (
        SELECT 1 FROM organization_users WHERE organization_users.organization_id = $1 AND organization_users.user_id = auth.uid()
    );
$$ LANGUAGE sql SECURITY DEFINER STABLE;

-- 6. Apply RLS to documents
-- Drop existing policies first
DROP POLICY IF EXISTS "Members can view org documents" ON documents;
DROP POLICY IF EXISTS "Members can create and update their OWN documents" ON documents;
DROP POLICY IF EXISTS "Super Admins can manage ALL documents" ON documents;
DROP POLICY IF EXISTS "View documents" ON documents;
DROP POLICY IF EXISTS "Manage documents" ON documents;
DROP POLICY IF EXISTS "Manage documents inserts" ON documents;

ALTER TABLE documents ENABLE ROW LEVEL SECURITY;
CREATE POLICY "View documents" ON documents FOR SELECT USING (can_view_document(id));
CREATE POLICY "Manage documents" ON documents FOR ALL USING (can_manage_document(id));

-- 7. Apply RLS to document_collaborators
ALTER TABLE document_collaborators ENABLE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS "View collaborators" ON document_collaborators;
DROP POLICY IF EXISTS "Manage collaborators" ON document_collaborators;
CREATE POLICY "View collaborators" ON document_collaborators FOR SELECT USING (can_view_document(document_id));
CREATE POLICY "Manage collaborators" ON document_collaborators FOR ALL USING (can_manage_document(document_id));

-- 8. Apply RLS to document_versions
-- Ensure table has RLS enabled
ALTER TABLE document_versions ENABLE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS "View document versions" ON document_versions;
DROP POLICY IF EXISTS "Manage document versions" ON document_versions;

CREATE POLICY "View document versions" ON document_versions FOR SELECT USING (
    can_view_document(document_id) AND
    (
        status = 'published'
        OR author_id = auth.uid()
        OR EXISTS (SELECT 1 FROM documents d WHERE d.id = document_id AND get_user_org_role(d.organization_id) IN ('admin', 'super_admin'))
    )
);

CREATE POLICY "Manage document versions" ON document_versions FOR ALL USING (
    can_manage_document(document_id)
);

-- Note: We also need INSERT policies because FOR ALL might not cover inserts without a check expression or FOR ALL uses USING for both.
-- Actually, FOR ALL USING (expr) WITH CHECK (expr) is the normal behavior, but Supabase/Postgres might need explicitly:
DROP POLICY IF EXISTS "Manage documents inserts" ON documents;
CREATE POLICY "Manage documents inserts" ON documents FOR INSERT WITH CHECK (
    can_view_org(organization_id) -- Just ensure they insert into their own org
);

DROP POLICY IF EXISTS "Manage version inserts" ON document_versions;
CREATE POLICY "Manage version inserts" ON document_versions FOR INSERT WITH CHECK (
    can_manage_document(document_id)
);
