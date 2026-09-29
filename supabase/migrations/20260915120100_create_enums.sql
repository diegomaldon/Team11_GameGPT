-- =============================================================================
-- GameGPT :: 20260915120100 :: Enumerated types
-- Source: CIS453 structure diagram sections 3.1, 3.5, 3.7, 3.12
-- AC: enums for PlatformType, AuthProvider, ImportMethod, FeedbackType
-- =============================================================================

-- 3.12 PlatformType4
create type public.platform_type as enum ('STEAM', 'XBOX', 'EPIC');

-- 3.1 AuthProvider4
create type public.auth_provider as enum ('EMAIL', 'GOOGLE');

-- 3.7 ImportMethod4
create type public.import_method as enum ('OAUTH', 'MANUAL');

-- 3.5 FeedbackType4
create type public.feedback_type as enum ('NOT_INTERESTED', 'ALREADY_PLAYED', 'WISHLISTED');
