export interface User {
  id: string;
  email: string;
  full_name?: string;
  credits?: number;
  tier?: string;
}

export interface Route {
  id: string;
  user_id: string;
  name: string;
  slug: string;
  destination_url: string;
  method: string;
  headers: Record<string, string>;
  is_active: boolean;
  requests_count: number;
  last_used_at?: string;
  api_key_prefix?: string;
  rate_limit: number;
  max_payload_bytes: number;
  max_concurrent_deliveries: number;
  content_scan_rules: Record<string, any>[];
  signing_secret?: string | null;
  has_webhook_secret: boolean;
  has_transform: boolean;
  transform_headers: Record<string, string>;
  transform_body_template?: string;
  form_schema: Record<string, any>;
  spam_honeypot_field?: string;
  spam_blocked_ua: string[];
  spam_allowed_countries: string[];
  spam_blocked_ips: string[];
  turnstile_enabled: boolean;
  turnstile_site_key?: string;
  turnstile_secret_key?: string;
  email_notifications: Record<string, any>;
  created_at: string;
  updated_at: string;
  webhook_secret?: string;
  stats?: RouteStats;
}

export interface RouteStats {
  total_deliveries: number;
  successful_deliveries: number;
  failed_deliveries: number;
  timeout_count: number;
  avg_latency_ms?: number;
  deliveries_24h: number;
  deliveries_7d: number;
  deliveries_30d: number;
  success_rate_percent: number;
}

export interface Payment {
  id: string;
  reference: string;
  tier: string;
  amount: number;
  credits_to_add: number;
  status: string;
  created_at: string;
}

export interface LogEntry {
  id: number;
  route_id: string;
  route_name?: string;
  status_code: number;
  created_at: string;
  duration_ms?: number;
}

export interface WebhookFailure {
  id: string;
  route_id: string;
  route_name?: string;
  status_code?: number;
  error_message?: string;
  retry_count: number;
  max_retries: number;
  created_at: string;
  updated_at: string;
}

export interface ApiError {
  detail?: string;
  message?: string;
}

export type Provider = 'google' | 'github';
