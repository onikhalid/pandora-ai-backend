-- Migration: Add is_public_to_org for three-tier visibility

-- 1. Add is_public_to_org column to documents
ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_public_to_org BOOLEAN DEFAULT false;

-- Ensure consistency: if is_public_to_org is true, is_public must also be true
UPDATE documents SET is_public = true WHERE is_public_to_org = true;

-- 2. Update can_view_document to respect the three tiers:
--    Private      : is_public=false, is_public_to_org=false → only owner & explicit collaborators & admins
--    Restricted   : is_public=true, is_public_to_org=false → owner + explicit collaborators + admins
--    Public to Org: is_public=true, is_public_to_org=true  → all org members can view
CREATE OR REPLACE FUNCTION can_view_document(doc_id UUID)
RETURNS BOOLEAN AS $$
    SELECT EXISTS (
        SELECT 1 FROM documents d
        LEFT JOIN document_collaborators dc ON dc.document_id = d.id AND dc.user_id = auth.uid()
        WHERE d.id = $1 AND (
            d.owner_id = auth.uid()
            OR dc.user_id IS NOT NULL
            OR (d.is_public_to_org = true AND can_view_org(d.organization_id))
            OR get_user_org_role(d.organization_id) IN ('admin', 'super_admin')
        )
    );
$$ LANGUAGE sql SECURITY DEFINER STABLE;

-- 3. Also allow private sandbox inserts (organization_id IS NULL for sandbox docs)
DROP POLICY IF EXISTS "Manage documents inserts" ON documents;
CREATE POLICY "Manage documents inserts" ON documents FOR INSERT WITH CHECK (
    organization_id IS NULL  -- private sandbox: anyone can create their own
    OR can_view_org(organization_id)
);
