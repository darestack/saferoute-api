-- SafeRoute API Migration 003 — Encrypt webhook secrets at rest
-- Run this against an EXISTING Supabase deployment.
--
-- Changes:
--   1. Enable pgcrypto extension
--   2. Add SQL functions for encrypt/decrypt webhook_secret using pgcrypto
--   3. Provide migration SQL for existing plaintext secrets
--
-- NOTE: After running this migration, set app.encryption_key in your
-- Supabase database settings. The same key must be used for both encryption
-- and decryption.
--
--   ALTER DATABASE your_db_name SET app.encryption_key = 'your-secret-key-here';
--
-- Or run:
--   SELECT set_config('app.encryption_key', 'your-secret-key-here', false);
--
-- Once set, restart your application with the same ENCRYPTION_KEY env var.
--
-- To encrypt existing rows (run only after setting app.encryption_key):
-- UPDATE public.routes
-- SET webhook_secret = public.encrypt_webhook_secret(webhook_secret)
-- WHERE webhook_secret IS NOT NULL
--   AND webhook_secret != ''
--   AND webhook_secret NOT LIKE 'safe_plain:%'
--   AND webhook_secret NOT LIKE 'enc:%';

-- ========================================
-- 1. Enable pgcrypto extension
-- ========================================
create extension if not exists "pgcrypto";

-- ========================================
-- 2. Encryption helper functions
-- ========================================
create or replace function public.encrypt_webhook_secret(p_plain text)
returns text as $$
declare
    v_key text;
begin
    if p_plain is null or length(p_plain) = 0 then
        return null;
    end if;

    v_key := encode(digest(current_setting('app.encryption_key', true), 'sha256'), 'base64');

    if v_key is null or length(v_key) = 0 then
        return 'safe_plain:' || p_plain;
    end if;

    return pgp_sym_encrypt(p_plain, v_key, 'aes256');
exception when others then
    return 'safe_plain:' || p_plain;
end;
$$ language plpgsql;

create or replace function public.decrypt_webhook_secret(p_cipher text)
returns text as $$
declare
    v_key text;
    v_decrypted text;
begin
    if p_cipher is null then
        return null;
    end if;

    -- Handle plaintext fallback prefix.
    if p_cipher like 'safe_plain:%' then
        return substring(p_cipher from 12);
    end if;

    v_key := encode(digest(current_setting('app.encryption_key', true), 'sha256'), 'base64');

    if v_key is null or length(v_key) = 0 then
        return p_cipher;
    end if;

    begin
        v_decrypted := pgp_sym_decrypt(p_cipher, v_key);
        return v_decrypted;
    exception when others then
        return p_cipher;
    end;
end;
$$ language plpgsql;
