// SafeRoute Dashboard - main entry point

import { User, Route, Payment, LogEntry } from './types';
import { apiRequest } from './lib/api';
import { getToken, isAuthenticated } from './lib/auth';
import { router } from './lib/router';
import { showSection, updateLoadingState, showError, showSuccess, escapeHtml, formatDate } from './components/DashboardShell';
import { updateRoutesUI, updateLogsUI, renderPaymentHistory } from './components/DashboardTables';
import { initCharts } from './components/DashboardCharts';

const state = {
  user: null as User | null,
  routes: [] as Route[],
  logs: [] as LogEntry[],
  stats: {} as Record<string, number>,
  isLoading: false,
};

async function initApp(): Promise<void> {
  await checkAuth();
  setupEventListeners();
  await checkPaymentResult();
  await loadDashboardData();
}

async function checkAuth(): Promise<void> {
  if (!isAuthenticated()) {
    window.location.href = '/login.html';
    return;
  }

  try {
    const user = await apiRequest<User>('/v1/me');
    state.user = user;
    updateUserUI();
  } catch {
    localStorage.removeItem('saferoute_token');
    window.location.href = '/login.html';
  }
}

function setupEventListeners(): void {
  document.querySelectorAll('.nav-link').forEach((link) => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const sectionId = link.getAttribute('href')?.slice(1) || 'dashboard';
      showSection(sectionId);

      document.querySelectorAll('.nav-link').forEach((l) => {
        l.classList.remove('bg-safe-accent/10', 'text-safe-accent');
        l.classList.add('text-safe-muted');
      });
      link.classList.remove('text-safe-muted');
      link.classList.add('bg-safe-accent/10', 'text-safe-accent');
    });
  });
}

async function loadDashboardData(): Promise<void> {
  state.isLoading = true;
  updateLoadingState();

  try {
    const token = getToken();
    const headers = { Authorization: `Bearer ${token}` };

    const [routes, user] = await Promise.all([
      apiRequest<Route[]>('/v1/routes?limit=100', { headers }),
      apiRequest<User>('/v1/me', { headers }),
    ]);

    if (routes) {
      state.routes = routes;
      await loadRoutesData();
      updateRoutesUI(state.routes);
      initCharts(state.routes);
    }

    if (user) {
      state.user = user;
      updateUserUI();
    }
  } catch (error) {
    console.error('Failed to load dashboard data:', error);
    showError('Failed to load dashboard data');
  } finally {
    state.isLoading = false;
    updateLoadingState();
  }
}

async function loadRoutesData(): Promise<void> {
  // Load additional route data if needed
}

function updateStatsUI(): void {
  const totalRequests = state.routes.reduce((sum, r) => sum + r.requests_count, 0);
  const el = document.getElementById('total-requests');
  if (el) el.textContent = totalRequests.toLocaleString();

  const successRate = state.stats.success_rate ?? 0;
  const rateEl = document.getElementById('success-rate');
  if (rateEl) rateEl.textContent = `${successRate.toFixed(1)}%`;
}

function updateUserUI(): void {
  if (!state.user) return;

  const nameEl = document.getElementById('user-name');
  const emailEl = document.getElementById('user-email');
  const initialsEl = document.getElementById('user-initials');

  if (nameEl) nameEl.textContent = state.user.full_name || 'User';
  if (emailEl) emailEl.textContent = state.user.email || '';
  if (initialsEl && state.user.full_name) {
    initialsEl.textContent = state.user.full_name
      .split(' ')
      .map((n) => n[0])
      .join('')
      .toUpperCase()
      .slice(0, 2);
  }
}

async function checkPaymentResult(): Promise<void> {
  const urlParams = new URLSearchParams(window.location.search);
  const status = urlParams.get('status');
  const reference = urlParams.get('reference');
  const trxref = urlParams.get('trxref');

  if (status && (reference || trxref)) {
    const ref = reference || trxref;
    if (!ref) return;
    const token = getToken();
    if (!token) return;

    try {
      const authHeader = `Bearer ${token}`;
      const response = await fetch(`/v1/payments/verify/${encodeURIComponent(ref)}`, {
        headers: { Authorization: authHeader },
      });

      let data;
      const contentType = response.headers.get('content-type');
      if (contentType && contentType.includes('application/json')) {
        data = await response.json();
      } else {
        throw new Error(`Server error (${response.status})`);
      }

      if (response.ok && data.status === 'success') {
        showSuccess(`Payment successful! ${data.credits_added.toLocaleString()} credits added to your account.`);
      } else {
        showError(data.detail || 'Payment verification failed');
      }
    } catch (error) {
      console.error('Payment verification error:', error);
    }

    window.history.replaceState({}, document.title, window.location.pathname);
  }
}

async function createRoute(routeData: { name: string; destination_url: string }): Promise<void> {
  const route = await apiRequest<Route>('/v1/routes', {
    method: 'POST',
    body: JSON.stringify(routeData),
  });
  state.routes.push(route);
  updateRoutesUI(state.routes);
  showSuccess('Route created successfully');
}

async function editRoute(routeId: string): Promise<void> {
  const route = state.routes.find((r) => r.id === routeId);
  if (!route) return;

  const newName = prompt('Route name:', route.name);
  if (newName && newName !== route.name) {
    try {
      const updated = await apiRequest<Route>(`/v1/routes/${routeId}`, {
        method: 'PUT',
        body: JSON.stringify({ name: newName }),
      });
      Object.assign(route, updated);
      updateRoutesUI(state.routes);
      showSuccess('Route updated successfully');
    } catch (error) {
      showError(error instanceof Error ? error.message : 'Failed to update route');
    }
  }
}

async function deleteRoute(routeId: string): Promise<void> {
  if (!confirm('Are you sure you want to delete this route?')) return;

  try {
    await apiRequest(`/v1/routes/${routeId}`, { method: 'DELETE' });
    state.routes = state.routes.filter((r) => r.id !== routeId);
    updateRoutesUI(state.routes);
    showSuccess('Route deleted successfully');
  } catch (error) {
    showError(error instanceof Error ? error.message : 'Failed to delete route');
  }
}

async function replayLog(routeId: string, logId: number): Promise<void> {
  try {
    await apiRequest(`/v1/routes/${routeId}/logs/${logId}/replay`, { method: 'POST' });
    showSuccess('Replay queued');
  } catch (error) {
    showError(error instanceof Error ? error.message : 'Failed to replay log');
  }
}

async function purchaseCredits(tier: string): Promise<void> {
  const loadingEl = document.getElementById('payment-loading');
  const errorEl = document.getElementById('payment-error');

  if (loadingEl) loadingEl.classList.remove('hidden');
  if (errorEl) errorEl.classList.add('hidden');

  try {
    const response = await fetch(`/v1/payments/initialize`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${getToken()}`,
      },
      body: JSON.stringify({ tier, email: state.user?.email }),
    });

    if (!response.ok) {
      let errorMessage = 'Payment initialization failed';
      const contentType = response.headers.get('content-type');
      if (contentType && contentType.includes('application/json')) {
        try {
          const err = await response.json();
          errorMessage = err.detail || errorMessage;
        } catch {
          errorMessage = `Server error (${response.status})`;
        }
      } else {
        errorMessage = `Server error (${response.status})`;
      }
      throw new Error(errorMessage);
    }

    const data = await response.json();
    window.location.href = data.authorization_url;
  } catch (error) {
    if (loadingEl) loadingEl.classList.add('hidden');
    if (errorEl) {
      errorEl.textContent = error instanceof Error ? error.message : 'Payment failed';
      errorEl.classList.remove('hidden');
    }
  }
}

async function loadPaymentHistory(): Promise<void> {
  const token = getToken();
  if (!token) return;

  try {
    const response = await fetch('/v1/payments/history', {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (response.ok) {
      const payments = await response.json();
      renderPaymentHistory(payments);
    }
  } catch (error) {
    console.error('Failed to load payment history:', error);
  }
}

async function refreshData(): Promise<void> {
  await loadDashboardData();
  initCharts(state.routes);
}

document.addEventListener('DOMContentLoaded', initApp);

(window as any).SafeRoute = {
  state,
  createRoute,
  editRoute,
  deleteRoute,
  replayLog,
  formatDate,
  loadDashboardData,
  loadPaymentHistory,
  initCharts,
  refreshData,
};
