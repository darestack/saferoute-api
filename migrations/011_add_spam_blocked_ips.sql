-- Add spam_blocked_ips column to routes table.
--
-- spam_blocked_ips: Array of blocked IP addresses (supports CIDR notation).

ALTER TABLE public.routes
    ADD COLUMN IF NOT EXISTS spam_blocked_ips text[] DEFAULT '{}';
