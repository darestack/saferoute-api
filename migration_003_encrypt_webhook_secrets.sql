-- SafeRoute API Migration 003 — Encrypt webhook secrets at rest
-- Run this against an EXISTING Supabase deployment.
--
-- Changes:
--   1. Enable pgcrypto extension
--   2. Add SQL functions for encrypt/decrypt webhook_secret
--   3. Migrate existing plaintext secrets to encrypted format
--
-- NOTE: After running this migration, set ENCRYPTION_KEY in your
-- environment variables. The same key must be used for both encryption
-- and decryption.

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
    v_key bytea := decode(convert_from(encrypt(''::bytea, current_setting('app.encryption_key', true), 'aes-gcm'), 'utf8'), 'base64');
    v_nonce bytea := gen_random_bytes(12);
    v_cipher bytea;
begin
    if p_plain is null or length(p_plain) = 0 then
        return null;
    end if;

    v_cipher := encrypt(p_plain::bytea, v_key, 'aes-gcm');
    return encode(v_nonce || v_cipher, 'base64');
end;
$$ language plpgsql;

create or replace function public.decrypt_webhook_secret(p_cipher text)
returns text as $$
declare
    v_key bytea := decode(convert_from(encrypt(''::bytea, current_setting('app.encryption_key', true), 'aes-gcm'), 'utf8'), 'base64');
    v_data bytea;
    v_nonce bytea;
    v_cipher bytea;
    v_plain text;
begin
    if p_cipher is null then
        return null;
    end if;

    v_data := decode(p_cipher, 'base64');
    v_nonce := substring(v_data from 1 for 12);
    v_cipher := substring(v_data from 13);

    v_plain := convert_from(decrypt(v_cipher, v_key, 'aes-gcm'), 'utf8');
    return v_plain;
exception when others then
    return p_cipher;
end;
$$ language plpgsql;

-- ========================================
-- 3. Migrate existing plaintext secrets
-- ========================================
-- WARNING: This will encrypt any existing plaintext webhook_secret values.
-- After migration, you MUST set app.encryption_key in your Supabase
-- database settings (Settings -> Database -> Configuration):
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
