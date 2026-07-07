-- SafeRoute API Migration 002 — Enhancements
-- Run this against an EXISTING Supabase deployment.
-- For fresh deployments, use schema.sql directly.
--
-- Changes:
--   1. Add webhook_secret, rate_limit, transform columns to routes
--   2. Add retry columns to webhook_logs
--   3. Create idempotency_cache table
--   4. Add RLS policies for idempotency_cache
--   5. Add cleanup functions
--   6. Add retry index

-- ========================================
-- 1. New columns on routes
-- ========================================
ALTER TABLE public.routes ADD COLUMN IF NOT EXISTS webhook_secret text;
ALTER TABLE public.routes ADD COLUMN IF NOT EXISTS rate_limit integer DEFAULT 30;
ALTER TABLE public.routes ADD COLUMN IF NOT EXISTS transform_headers jsonb DEFAULT '{}'::jsonb;
ALTER TABLE public.routes ADD COLUMN IF NOT EXISTS transform_body_template text;

-- ========================================
-- 2. Retry columns on webhook_logs
-- ========================================
ALTER TABLE public.webhook_logs ADD COLUMN IF NOT EXISTS retry_count integer DEFAULT 0;
ALTER TABLE public.webhook_logs ADD COLUMN IF NOT EXISTS max_retries integer DEFAULT 3;
ALTER TABLE public.webhook_logs ADD COLUMN IF NOT EXISTS next_retry_at timestamp with time zone;
ALTER TABLE public.webhook_logs ADD COLUMN IF NOT EXISTS retry_status text DEFAULT 'none';
ALTER TABLE public.webhook_logs ADD COLUMN IF NOT EXISTS idempotency_key text;
ALTER TABLE public.webhook_logs ADD COLUMN IF NOT EXISTS content_type text;

-- Add check constraint for retry_status
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'webhook_logs_retry_status_check'
    ) THEN
        ALTER TABLE public.webhook_logs ADD CONSTRAINT webhook_logs_retry_status_check
            CHECK (retry_status IN ('none', 'pending', 'retrying', 'exhausted', 'succeeded'));
    END IF;
END $$;

-- Index for retry processing
CREATE INDEX IF NOT EXISTS idx_webhook_logs_retry
    ON public.webhook_logs(retry_status, next_retry_at)
    WHERE retry_status = 'pending';

-- ========================================
-- 3. Idempotency cache table
-- ========================================
CREATE TABLE IF NOT EXISTS public.idempotency_cache (
    id uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
    route_id uuid NOT NULL REFERENCES public.routes(id) ON DELETE CASCADE,
    idempotency_key text NOT NULL,
    response_status integer NOT NULL,
    response_body text,
    response_headers jsonb,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL,
    UNIQUE(route_id, idempotency_key)
);

CREATE INDEX IF NOT EXISTS idx_idempotency_cache_lookup
    ON public.idempotency_cache(route_id, idempotency_key);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'pkce_verifiers_code_challenge_key'
    ) THEN
        ALTER TABLE public.pkce_verifiers
            ADD CONSTRAINT pkce_verifiers_code_challenge_key
            UNIQUE (code_challenge);
    END IF;
END $$;

-- ========================================
-- 4. RLS for idempotency_cache
-- ========================================
ALTER TABLE public.idempotency_cache ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'idempotency_cache'
        AND policyname = 'Service role full access idempotency_cache'
    ) THEN
        EXECUTE 'CREATE POLICY "Service role full access idempotency_cache"
            ON public.idempotency_cache FOR ALL
            TO service_role
            USING (true)';
    END IF;
END $$;

-- ========================================
-- 5. Cleanup function for idempotency cache
-- ========================================
CREATE OR REPLACE FUNCTION public.cleanup_idempotency_cache()
RETURNS void AS $$
BEGIN
    DELETE FROM public.idempotency_cache
    WHERE created_at < timezone('utc'::text, now()) - interval '24 hours';
END;
$$ LANGUAGE plpgsql;

-- ========================================
-- 5b. Atomic helper function repairs
-- ========================================
CREATE OR REPLACE FUNCTION public.increment_rate_limit(
    p_route_id uuid,
    p_ip inet,
    p_window_start timestamp with time zone,
    p_max_requests integer
)
RETURNS TABLE (
    success boolean,
    new_count integer
) AS $$
BEGIN
    INSERT INTO public.rate_limits (route_id, ip_address, request_count, window_start)
    VALUES (p_route_id, p_ip, 1, p_window_start)
    ON CONFLICT (route_id, ip_address, window_start)
    DO UPDATE
        SET request_count = public.rate_limits.request_count + 1
        WHERE public.rate_limits.request_count < p_max_requests
    RETURNING request_count INTO new_count;

    IF FOUND THEN
        success := true;
        RETURN NEXT;
        RETURN;
    END IF;

    SELECT request_count INTO new_count
    FROM public.rate_limits
    WHERE route_id = p_route_id
      AND ip_address = p_ip
      AND window_start = p_window_start
    LIMIT 1;

    success := false;
    RETURN NEXT;
    RETURN;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION public.consume_pkce_verifier(p_code_challenge text)
RETURNS TABLE (code_verifier text) AS $$
BEGIN
    RETURN QUERY
    DELETE FROM public.pkce_verifiers verifier
    WHERE verifier.code_challenge = p_code_challenge
    RETURNING verifier.code_verifier;
END;
$$ LANGUAGE plpgsql;

-- ========================================
-- 6. Webhook failures dead-letter queue
-- ========================================
CREATE TABLE IF NOT EXISTS public.webhook_failures (
    id uuid DEFAULT uuid_generate_v4() PRIMARY KEY,
    route_id uuid NOT NULL REFERENCES public.routes(id) ON DELETE CASCADE,
    webhook_log_id bigint,
    status_code integer,
    error_message text,
    request_body jsonb,
    response_body text,
    ip_address inet,
    user_agent text,
    retry_count integer DEFAULT 0,
    max_retries integer DEFAULT 3,
    created_at timestamp with time zone DEFAULT timezone('utc'::text, now()) NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_webhook_failures_route_id
    ON public.webhook_failures(route_id);
CREATE INDEX IF NOT EXISTS idx_webhook_failures_created_at
    ON public.webhook_failures(created_at);

ALTER TABLE public.webhook_failures ENABLE ROW LEVEL SECURITY;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_policies
        WHERE tablename = 'webhook_failures'
        AND policyname = 'Service role full access webhook_failures'
    ) THEN
        EXECUTE 'CREATE POLICY "Service role full access webhook_failures"
            ON public.webhook_failures FOR ALL
            TO service_role
            USING (true)';
    END IF;
END $$;
