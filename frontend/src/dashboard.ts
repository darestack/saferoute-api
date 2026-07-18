// SafeRoute Dashboard - main entry point

import { User, Route, Payment, LogEntry } from './types';
import { apiRequest } from './lib/api';
import { getToken, isAuthenticated, logout } from './lib/auth';
import { API_ENDPOINTS } from './lib/constants';
import { showSection, updateLoadingState, showError, showSuccess, formatDate, toggleSidebar, showCreateRouteModal, hideCreateRouteModal } from './components/DashboardShell';
import { updateRoutesUI, updateLogsUI, renderPaymentHistory } from './components/DashboardTables';
import { initCharts } from './components/DashboardCharts';

interface SafeRouteApi {
  createRoute: (routeData: { name: string; destination_url: string }) => Promise<void>;
  editRoute: (routeId: string) => Promise<void>;
  deleteRoute: (routeId: string) => Promise<void>;
  replayLog: (routeId: string, logId: number) => Promise<void>;
  formatDate: (dateString: string) => string;
  loadDashboardData: () => Promise<void>;
  loadPaymentHistory: () => Promise<void>;
  refreshData: () => Promise<void>;
  state: {
    user: User | null;
    routes: Route[];
    logs: LogEntry[];
    payments: Payment[];
    isLoading: boolean;
  };
}

const state = {
  user: null as User | null,
  routes: [] as Route[],
  logs: [] as LogEntry[],
  payments: [] as Payment[],
  isLoading: false,
};

async function initApp(): Promise<void> {
  await checkAuth();
  setupEventListeners();
  await checkPaymentResult();
  await loadExchangeRates();
  await loadDashboardData();
}

async function checkAuth(): Promise<void> {
  if (!isAuthenticated()) {
    window.location.href = '/login.html';
    return;
  }

  try {
    const user = await apiRequest<User>(API_ENDPOINTS.ME);
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

  const createRouteForm = document.getElementById('create-route-form');
  if (createRouteForm) {
    createRouteForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const form = createRouteForm as HTMLFormElement;
      const formData = new FormData(form);
      const name = (formData.get('name') as string).trim();
      const destinationUrl = (formData.get('destination_url') as string).trim();

      if (name.length < 2) {
        showError('Route name must be at least 2 characters');
        return;
      }

      if (name.length > 100) {
        showError('Route name must be less than 100 characters');
        return;
      }

      try {
        new URL(destinationUrl);
      } catch {
        showError('Please enter a valid URL (e.g., https://example.com/webhook)');
        return;
      }

      const routeData = {
        name,
        destination_url: destinationUrl,
      };

      try {
        await createRoute(routeData);
        hideCreateRouteModal();
        form.reset();
      } catch (error) {
        console.error('Failed to create route:', error);
      }
    });
  }

  const cancelCreateRouteBtn = document.getElementById('cancel-create-route-btn');
  if (cancelCreateRouteBtn) {
    cancelCreateRouteBtn.addEventListener('click', () => {
      hideCreateRouteModal();
    });
  }

  const modalBackdrop = document.getElementById('modal-backdrop');
  if (modalBackdrop) {
    modalBackdrop.addEventListener('click', () => {
      hideCreateRouteModal();
    });
  }

  const quickCreateRouteBtn = document.getElementById('quick-create-route-btn');
  if (quickCreateRouteBtn) {
    quickCreateRouteBtn.addEventListener('click', () => {
      showCreateRouteModal();
    });
  }

  const routesCreateBtn = document.getElementById('routes-create-btn');
  if (routesCreateBtn) {
    routesCreateBtn.addEventListener('click', () => {
      showCreateRouteModal();
    });
  }

  const logoutBtn = document.getElementById('logout-btn');
  if (logoutBtn) {
    logoutBtn.addEventListener('click', async () => {
      try {
        await logout();
      } catch (error) {
        console.error('Logout failed:', error);
      }
    });
  }

  const refreshBtn = document.getElementById('refresh-btn');
  if (refreshBtn) {
    refreshBtn.addEventListener('click', async () => {
      await refreshData();
    });
  }

  const quickRefreshBtn = document.getElementById('quick-refresh-btn');
  if (quickRefreshBtn) {
    quickRefreshBtn.addEventListener('click', async () => {
      await refreshData();
    });
  }

  const logsRefreshBtn = document.getElementById('logs-refresh-btn');
  if (logsRefreshBtn) {
    logsRefreshBtn.addEventListener('click', async () => {
      await refreshData();
    });
  }

  const toggleSidebarBtn = document.getElementById('toggle-sidebar-btn');
  if (toggleSidebarBtn) {
    toggleSidebarBtn.addEventListener('click', () => {
      toggleSidebar();
    });
  }

  document.querySelectorAll('[data-purchase-tier]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const tier = btn.getAttribute('data-purchase-tier');
      if (tier) {
        purchaseCredits(tier);
      }
    });
  });
}

async function loadDashboardData(): Promise<void> {
  state.isLoading = true;
  updateLoadingState(true);

  try {
    const token = getToken();
    const headers = { Authorization: `Bearer ${token}` };

    const [routes, user] = await Promise.all([
      apiRequest<Route[]>(API_ENDPOINTS.ROUTES_LIMIT, { headers }),
      apiRequest<User>(API_ENDPOINTS.ME, { headers }),
    ]);

    if (routes) {
      state.routes = routes;
      updateRoutesUI(state.routes);
      initCharts(state.routes);
    }

    if (user) {
      state.user = user;
      updateUserUI();
    }

    await loadPaymentHistory();
  } catch (error) {
    console.error('Failed to load dashboard data:', error);
    showError('Failed to load dashboard data');
  } finally {
    state.isLoading = false;
    updateLoadingState(false);
  }
}

async function loadPaymentHistory(): Promise<void> {
  const token = getToken();
  if (!token) return;

  try {
    const response = await fetch(API_ENDPOINTS.PAYMENTS_HISTORY, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (response.ok) {
      const payments = await response.json();
      state.payments = payments;
      renderPaymentHistory(payments);
    }
  } catch (error) {
    console.error('Failed to load payment history:', error);
  }
}

function updateUserUI(): void {
  if (!state.user) return;

  const nameEl = document.getElementById('user-name');
  const emailEl = document.getElementById('user-email');
  const initialsEl = document.getElementById('user-initials');

  if (nameEl) nameEl.textContent = state.user.full_name || 'User';
  if (emailEl) emailEl.textContent = state.user.email || '';
  if (initialsEl && state.user.full_name) {
    const nameParts = state.user.full_name.trim().split(/\s+/);
    initialsEl.textContent = nameParts.map((n) => n[0]).join('').toUpperCase().slice(0, 2);
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
      const response = await fetch(API_ENDPOINTS.PAYMENTS_VERIFY(ref), {
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
        const creditsAdded = data.credits_added ?? 0;
        showSuccess(`Payment successful! ${creditsAdded.toLocaleString()} credits added to your account.`);
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
  const route = await apiRequest<Route>(API_ENDPOINTS.CREATE_ROUTE, {
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
      const updated = await apiRequest<Route>(API_ENDPOINTS.UPDATE_ROUTE(routeId), {
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
    await apiRequest(API_ENDPOINTS.DELETE_ROUTE(routeId), { method: 'DELETE' });
    state.routes = state.routes.filter((r) => r.id !== routeId);
    updateRoutesUI(state.routes);
    showSuccess('Route deleted successfully');
  } catch (error) {
    showError(error instanceof Error ? error.message : 'Failed to delete route');
  }
}

async function replayLog(routeId: string, logId: number): Promise<void> {
  try {
    await apiRequest(API_ENDPOINTS.REPLAY_LOG(routeId, logId), { method: 'POST' });
    showSuccess('Replay queued');
  } catch (error) {
    showError(error instanceof Error ? error.message : 'Failed to replay log');
  }
}

let exchangeRates: Record<string, number> = {};

async function loadExchangeRates(): Promise<void> {
  try {
    const response = await fetch('/v1/rates?base=USD&symbols=NGN,EUR,GBP,ZAR,KES,GHS,CAD,AUD');
    if (response.ok) {
      const data = await response.json();
      exchangeRates = data.rates || {};
      updatePrices();
    }
  } catch (error) {
    console.error('Failed to load exchange rates:', error);
  }
}

function updatePrices(): void {
  const currency = (document.getElementById('currency-select') as HTMLSelectElement)?.value || 'USD';
  const priceDisplays = document.querySelectorAll('.price-display');

  priceDisplays.forEach((el) => {
    const usd = parseFloat(el.getAttribute('data-usd') || '0');
    const ngn = parseFloat(el.getAttribute('data-ngn') || '0');

    if (currency === 'NGN') {
      el.textContent = `₦${ngn.toLocaleString()}`;
    } else if (currency === 'USD') {
      el.textContent = `$${usd.toFixed(2)}`;
    } else {
      const rate = exchangeRates[currency] || 1;
      const converted = usd * rate;
      const symbols: Record<string, string> = { EUR: '€', GBP: '£', ZAR: 'R', KES: 'KSh', GHS: 'GH₵', CAD: 'C$', AUD: 'A$' };
      const symbol = symbols[currency] || currency + ' ';
      el.textContent = `${symbol}${converted.toFixed(2)}`;
    }
  });
}

async function purchaseCredits(tier: string): Promise<void> {
  const loadingEl = document.getElementById('payment-loading');
  const errorEl = document.getElementById('payment-error');

  if (loadingEl) loadingEl.classList.remove('hidden');
  if (errorEl) errorEl.classList.add('hidden');

  try {
    const response = await fetch(API_ENDPOINTS.PAYMENTS_INITIALIZE, {
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


async function refreshData(): Promise<void> {
  await loadDashboardData();
}

const SafeRouteApi = {
  createRoute,
  editRoute,
  deleteRoute,
  replayLog,
  formatDate,
  loadDashboardData,
  loadPaymentHistory,
  refreshData,
  get state() {
    return state;
  },
};

document.addEventListener('DOMContentLoaded', initApp);

declare global {
  interface Window {
    SafeRoute: SafeRouteApi;
  }
}

window.SafeRoute = SafeRouteApi;
