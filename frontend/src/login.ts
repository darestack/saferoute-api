// SafeRoute Login Page

// CSS is loaded via global import in main.ts / dashboard.ts

function showAuthError(message: string): void {
  const errorEl = document.getElementById('auth-error');
  if (errorEl) {
    errorEl.textContent = message;
    errorEl.classList.remove('hidden');
    setTimeout(() => errorEl.classList.add('hidden'), 5000);
  }
}

async function signInWith(provider: 'google' | 'github'): Promise<void> {
  try {
    const response = await fetch(`/auth/oauth/${provider}`);
    if (!response.ok) {
      let errorMessage = 'Failed to initiate OAuth';
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

    const data = (await response.json()) as { auth_url: string };

    const width = 500;
    const height = 600;
    const left = window.screenX + (window.outerWidth - width) / 2;
    const top = window.screenY + (window.outerHeight - height) / 2;

    const popup = window.open(
      data.auth_url,
      'OAuth',
      `width=${width},height=${height},left=${left},top=${top}`
    );

    if (!popup) {
      throw new Error('Popup blocked. Please allow popups for this site.');
    }

    const pollTimer = setInterval(() => {
      if (popup.closed) {
        clearInterval(pollTimer);
        const token = localStorage.getItem('saferoute_token');
        if (token) {
          window.location.href = '/dashboard.html';
        }
      }
    }, 500);
  } catch (error) {
    showAuthError(error instanceof Error ? error.message : 'Unknown error');
  }
}

async function checkExistingSession(): Promise<void> {
  const token = localStorage.getItem('saferoute_token');
  if (!token) return;

  try {
    const response = await fetch('/v1/me', {
      headers: { Authorization: `Bearer ${token}` },
    });
    if (response.ok) {
      window.location.href = '/dashboard.html';
    }
  } catch {
    // Token invalid, stay on login page
  }
}

function initErrorFromQuery(): void {
  const params = new URLSearchParams(window.location.search);
  const error = params.get('error');
  if (error) {
    showAuthError(decodeURIComponent(error));
  }
}

document.addEventListener('DOMContentLoaded', () => {
  checkExistingSession();
  initErrorFromQuery();
});

(window as any).signInWith = signInWith;
(window as any).showAuthError = showAuthError;
