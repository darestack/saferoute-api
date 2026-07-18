const API_BASE = import.meta.env.VITE_API_BASE || '';

function getAuthHeader(): Record<string, string> {
  const token = localStorage.getItem('saferoute_token');
  return token ? { Authorization: `Bearer ${token}` } : {};
}

async function parseJsonSafe(response: Response): Promise<any> {
  if (response.status === 204) {
    return null;
  }

  const contentType = response.headers.get('content-type');
  if (contentType && contentType.includes('application/json')) {
    return response.json();
  }

  throw new Error(`Server error (${response.status})`);
}

export async function apiRequest<T>(
  endpoint: string,
  options: RequestInit = {}
): Promise<T> {
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...getAuthHeader(),
      ...options.headers,
    },
  });

  if (response.status === 401) {
    localStorage.removeItem('saferoute_token');
    window.location.href = '/login.html';
    return Promise.reject(new Error('Unauthorized'));
  }

  if (response.status === 403) {
    return Promise.reject(new Error('Forbidden'));
  }

  if (!response.ok) {
    const error = await parseJsonSafe(response).catch(() => ({
      message: `HTTP ${response.status}`,
    }));
    throw new Error(error.detail || error.message || `HTTP ${response.status}`);
  }

  return parseJsonSafe(response);
}

export { API_BASE };
