-- ============================================
-- PANDORA: Full Database Reset Script
-- ============================================
-- WARNING: This will PERMANENTLY delete all data!
-- Paste this into the Supabase SQL Editor and run.

-- 1. Drop all custom tables (in dependency order)
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

-- 2. Drop all custom ENUM types
DROP TYPE IF EXISTS org_role CASCADE;
DROP TYPE IF EXISTS user_role CASCADE;
DROP TYPE IF EXISTS document_status CASCADE;
DROP TYPE IF EXISTS crd_status CASCADE;

-- 3. Drop custom helper functions
DROP FUNCTION IF EXISTS get_user_org_role(UUID) CASCADE;
DROP FUNCTION IF EXISTS get_user_domain_ids(UUID) CASCADE;

-- Done! Now re-run schema.sql to rebuild from scratch.
