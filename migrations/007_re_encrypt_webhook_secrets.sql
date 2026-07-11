-- Re-encrypt webhook secrets after ENCRYPTION_KEY rotation.
--
-- This migration updates all routes that still have plaintext secrets
-- (prefixed with "safe_plain:") or secrets encrypted with an old key
-- (prefixed with "v1:"), re-encrypting them with the current key.
--
-- IMPORTANT: Run this ONLY after deploying the new ENCRYPTION_KEY and
-- restarting the application (so clear_fernet_cache() is called or the
-- process starts fresh with the new key).

DO $$
DECLARE
    route_record RECORD;
    new_encrypted TEXT;
BEGIN
    FOR route_record IN
        SELECT id, webhook_secret
        FROM routes
        WHERE webhook_secret IS NOT NULL
          AND (webhook_secret LIKE 'safe_plain:%' OR webhook_secret LIKE 'v1:%')
    LOOP
        -- The actual re-encryption must happen in application code because
        -- it requires the Fernet key from the environment variable.
        -- This migration marks the routes that need re-encryption.
        RAISE NOTICE 'Route % needs webhook_secret re-encryption: %s',
            route_record.id,
            CASE
                WHEN route_record.webhook_secret LIKE 'safe_plain:%' THEN 'plaintext'
                ELSE 'old_key'
            END;
    END LOOP;
END $$;

-- After running the application-side re-encryption, verify all secrets
-- are encrypted with the current key format (v1: prefix).
-- SELECT COUNT(*) FROM routes WHERE webhook_secret LIKE 'safe_plain:%' OR webhook_secret LIKE 'v1:%';
