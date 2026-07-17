const TOKEN_KEY = 'saferoute_token';

let verifyTokenPromise: Promise<boolean> | null = null;

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export function clearToken(): void {
  localStorage.removeItem(TOKEN_KEY);
}

export function isAuthenticated(): boolean {
  return !!getToken();
}

export async function verifyToken(): Promise<boolean> {
  const token = getToken();
  if (!token) return false;

  if (verifyTokenPromise) {
    return verifyTokenPromise;
  }

  verifyTokenPromise = fetch('/v1/me', {
    headers: { Authorization: `Bearer ${token}` },
  })
    .then((response) => response.ok)
    .catch(() => false)
    .finally(() => {
      verifyTokenPromise = null;
    });

  return verifyTokenPromise;
}

export async function logout(): Promise<void> {
  clearToken();
  window.location.href = '/login.html';
}
