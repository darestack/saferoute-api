export interface User {
  id: string;
  email: string;
  full_name?: string;
  credits?: number;
  tier?: string;
}

export interface Route {
  id: string;
  name: string;
  slug: string;
  destination_url: string;
  method: string;
  is_active: boolean;
  requests_count: number;
  created_at: string;
  updated_at: string;
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

export interface ApiError {
  detail?: string;
  message?: string;
}

export type Provider = 'google' | 'github';
