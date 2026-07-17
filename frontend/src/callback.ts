// SafeRoute OAuth Callback Handler

// CSS is loaded via global import in main.ts / dashboard.ts

import { API_BASE } from './lib/api';
import { API_ENDPOINTS } from './lib/constants';

async function handleCallback(): Promise<void> {
  const params = new URLSearchParams(window.location.search);
  const code = params.get('code');
  const error = params.get('error');

  if (error) {
    window.location.href = `/login.html?error=${encodeURIComponent(error)}`;
    return;
  }

  if (!code) {
    window.location.href = '/login.html?error=no_code';
    return;
  }

  try {
    const response = await fetch(`${API_BASE}${API_ENDPOINTS.CALLBACK}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ code }),
    });

    if (!response.ok) {
      let errorMessage = 'Authentication failed';
      const contentType = response.headers.get('content-type');
      if (contentType && contentType.includes('application/json')) {
        try {
          const err = (await response.json()) as { detail?: string };
          errorMessage = err.detail || errorMessage;
        } catch {
          errorMessage = `Server error (${response.status})`;
        }
      } else {
        errorMessage = `Server error (${response.status})`;
      }
      throw new Error(errorMessage);
    }

    const data = (await response.json()) as { access_token: string };
    localStorage.setItem('saferoute_token', data.access_token);

    if (window.opener && !window.opener.closed) {
      window.opener.location.href = '/dashboard.html';
    }
    window.close();
    window.location.href = '/dashboard.html';
  } catch (err) {
    window.location.href = `/login.html?error=${encodeURIComponent(err instanceof Error ? err.message : 'Unknown error')}`;
  }
}

handleCallback();
