-- =============================================================================
-- GameGPT :: 20260915120000 :: Extensions
-- Ticket: Core database schema migration from the CIS453 structure diagram
-- =============================================================================
-- These three are the only statements in the whole set that keep an
-- IF NOT EXISTS guard, because Supabase may already have enabled some of them
-- on the project and re-enabling is harmless.
--
-- Do NOT add a VERSION clause. Supabase deprecated explicit extension versions
-- on 2026-08-05; the clause is ignored and emits a warning.
-- =============================================================================

-- gen_random_uuid() for primary keys
create extension if not exists pgcrypto with schema extensions;

-- pgvector :: Game4.embedding and Query4.embeddingVector (structure diagram 3.6, 3.13)
create extension if not exists vector with schema extensions;

-- trigram matching on game titles; used by the metadata importer to fuzzy-match
-- incoming rows against existing ones before inserting a duplicate
create extension if not exists pg_trgm with schema extensions;
