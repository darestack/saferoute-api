// SafeRoute Dashboard - main entry point

import { User, Route, Payment, LogEntry, WebhookFailure } from './types';
import { apiRequest, API_BASE } from './lib/api';
import { getToken, isAuthenticated, logout } from './lib/auth';
import { API_ENDPOINTS } from './lib/constants';
import { showSection, updateLoadingState, showError, showSuccess, formatDate, toggleSidebar, showCreateRouteModal, hideCreateRouteModal, showRouteDetailModal, hideRouteDetailModal, showSigningSecretModal, hideSigningSecretModal } from './components/DashboardShell';
import { updateRoutesUI, updateLogsUI, renderPaymentHistory, renderWebhookFailures } from './components/DashboardTables';
import { initCharts } from './components/DashboardCharts';

interface SafeRouteApi {
  createRoute: (routeData: { name: string; destination_url: string; rate_limit?: number; max_payload_bytes?: number; max_concurrent_deliveries?: number; content_scan_rules?: Record<string, any>[]; webhook_secret?: string; turnstile_site_key?: string }) => Promise<void>;
  openRouteDetail: (routeId: string) => Promise<void>;
  saveRouteDetail: () => Promise<void>;
  closeRouteDetail: () => void;
  revealSigningSecret: (routeId: string) => Promise<void>;
  copySigningSecret: () => Promise<void>;
  dismissSigningSecret: () => void;
  loadAdminData: () => Promise<void>;
  saveAdminIps: (ips: string) => Promise<void>;
  deleteRoute: (routeId: string) => Promise<void>;
  replayLog: (routeId: string, logId: number) => Promise<void>;
  retryWebhook: (failureId: string) => Promise<void>;
  loadWebhookFailures: () => Promise<void>;
  formatDate: (dateString: string) => string;
  loadDashboardData: () => Promise<void>;
  loadPaymentHistory: () => Promise<void>;
  refreshData: () => Promise<void>;
  state: {
    user: User | null;
    routes: Route[];
    logs: LogEntry[];
    payments: Payment[];
    webhookFailures: WebhookFailure[];
    isLoading: boolean;
    currentRouteId: string | null;
  };
}

const state = {
  user: null as User | null,
  routes: [] as Route[],
  logs: [] as LogEntry[],
  payments: [] as Payment[],
  webhookFailures: [] as WebhookFailure[],
  isLoading: false,
  currentRouteId: null as string | null,
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

      if (sectionId === 'admin-section') {
        loadAdminData();
      }

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
      const rateLimit = parseInt((formData.get('rate_limit') as string) || '30', 10);
      const webhookSecret = (formData.get('webhook_secret') as string) || undefined;
      const turnstileSiteKey = (formData.get('turnstile_site_key') as string) || undefined;

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

      const routeData: Partial<Route> = {
        name,
        destination_url: destinationUrl,
        rate_limit: isNaN(rateLimit) ? 30 : Math.max(1, Math.min(1000, rateLimit)),
        max_payload_bytes: 1048576,
        max_concurrent_deliveries: 10,
        content_scan_rules: [],
        has_webhook_secret: !!webhookSecret,
        webhook_secret: webhookSecret,
        turnstile_enabled: !!turnstileSiteKey,
        turnstile_site_key: turnstileSiteKey,
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

  const routeDetailBackdrop = document.getElementById('route-detail-backdrop');
  if (routeDetailBackdrop) {
    routeDetailBackdrop.addEventListener('click', () => {
      hideRouteDetailModal();
    });
  }

  const closeRouteDetailBtn = document.getElementById('close-route-detail');
  if (closeRouteDetailBtn) {
    closeRouteDetailBtn.addEventListener('click', () => {
      hideRouteDetailModal();
    });
  }

  const cancelRouteDetailBtn = document.getElementById('cancel-route-detail');
  if (cancelRouteDetailBtn) {
    cancelRouteDetailBtn.addEventListener('click', () => {
      hideRouteDetailModal();
    });
  }

  const revealSigningSecretBtn = document.getElementById('reveal-signing-secret-btn');
  if (revealSigningSecretBtn) {
    revealSigningSecretBtn.addEventListener('click', async () => {
      const routeId = (document.getElementById('detail-route-id') as HTMLInputElement)?.value;
      if (routeId) {
        await revealSigningSecret(routeId);
      }
    });
  }

  const copySigningSecretBtn = document.getElementById('copy-signing-secret');
  if (copySigningSecretBtn) {
    copySigningSecretBtn.addEventListener('click', async () => {
      await copySigningSecret();
    });
  }

  const dismissSigningSecretBtn = document.getElementById('dismiss-signing-secret');
  if (dismissSigningSecretBtn) {
    dismissSigningSecretBtn.addEventListener('click', () => {
      dismissSigningSecret();
    });
  }

  const routeDetailForm = document.getElementById('route-detail-form');
  if (routeDetailForm) {
    routeDetailForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      await saveRouteDetail();
    });
  }

  const adminIpsForm = document.getElementById('admin-ips-form');
  if (adminIpsForm) {
    adminIpsForm.addEventListener('submit', async (e) => {
      e.preventDefault();
      const ipsTextarea = document.getElementById('admin-allowed-ips') as HTMLTextAreaElement;
      if (ipsTextarea) {
        await saveAdminIps(ipsTextarea.value);
      }
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

  const webhooksRefreshBtn = document.getElementById('webhooks-refresh-btn');
  if (webhooksRefreshBtn) {
    webhooksRefreshBtn.addEventListener('click', async () => {
      await loadWebhookFailures();
    });
  }

  const currencySelect = document.getElementById('currency-select');
  if (currencySelect) {
    currencySelect.addEventListener('change', () => {
      updatePrices();
    });
  }

  document.querySelectorAll('[data-retry-failure-id]').forEach((btn) => {
    btn.addEventListener('click', () => {
      const failureId = btn.getAttribute('data-retry-failure-id');
      if (failureId) {
        retryWebhook(failureId);
      }
    });
  });

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
    }

    if (user) {
      state.user = user;
      updateUserUI();
    }

    await Promise.all([
      loadLogs(),
      loadStats(),
      loadPaymentHistory(),
      loadWebhookFailures(),
    ]);
  } catch (error) {
    console.error('Failed to load dashboard data:', error);
    showError(error instanceof Error ? error.message : 'Failed to load dashboard data');
  } finally {
    state.isLoading = false;
    updateLoadingState(false);
  }
}

async function loadLogs(): Promise<void> {
  const token = getToken();
  if (!token || state.routes.length === 0) return;

  try {
    const allLogs: LogEntry[] = [];
    const logPromises = state.routes.slice(0, 5).map(async (route) => {
      const response = await fetch(`${API_ENDPOINTS.ROUTES}/${route.id}/logs?limit=10`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (response.ok) {
        const logs = await response.json();
        return logs.map((log: LogEntry) => ({ ...log, route_name: route.name }));
      }
      return [];
    });

    const results = await Promise.all(logPromises);
    results.forEach((logs) => allLogs.push(...logs));
    allLogs.sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime());

    state.logs = allLogs.slice(0, 20);
    updateLogsUI(state.logs);
  } catch (error) {
    console.error('Failed to load logs:', error);
  }
}

async function loadStats(): Promise<void> {
  const token = getToken();
  if (!token || state.routes.length === 0) return;

  try {
    const statsPromises = state.routes.slice(0, 10).map(async (route) => {
      const response = await fetch(`${API_ENDPOINTS.ROUTES}/${route.id}/stats`, {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (response.ok) {
        return await response.json();
      }
      return null;
    });

    const statsResults = await Promise.all(statsPromises);
    state.routes.forEach((route, i) => {
      route.stats = statsResults[i] || null;
    });
    initCharts(state.routes);
  } catch (error) {
    console.error('Failed to load stats:', error);
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

async function loadWebhookFailures(): Promise<void> {
  const token = getToken();
  if (!token) return;

  try {
    const response = await fetch(API_ENDPOINTS.WEBHOOKS_FAILURES, {
      headers: { Authorization: `Bearer ${token}` },
    });

    if (response.ok) {
      const data = await response.json();
      state.webhookFailures = data.failures || [];
      renderWebhookFailures(state.webhookFailures);
    }
  } catch (error) {
    console.error('Failed to load webhook failures:', error);
  }
}

async function retryWebhook(failureId: string): Promise<void> {
  try {
    await apiRequest(API_ENDPOINTS.WEBHOOKS_RETRY(failureId), { method: 'POST' });
    showSuccess('Retry queued');
    await loadWebhookFailures();
  } catch (error) {
    showError(error instanceof Error ? error.message : 'Failed to retry webhook');
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

async function createRoute(routeData: Partial<Route>): Promise<void> {
  try {
    const route = await apiRequest<Route>(API_ENDPOINTS.CREATE_ROUTE, {
      method: 'POST',
      body: JSON.stringify(routeData),
    });
    state.routes.push(route);
    updateRoutesUI(state.routes);
    showSuccess('Route created successfully');
  } catch (error) {
    showError(error instanceof Error ? error.message : 'Failed to create route');
  }
}

async function openRouteDetail(routeId: string): Promise<void> {
  const route = state.routes.find((r) => r.id === routeId);
  if (!route) return;

  state.currentRouteId = routeId;

  (document.getElementById('detail-route-id') as HTMLInputElement).value = route.id;
  (document.getElementById('detail-name') as HTMLInputElement).value = route.name;
  (document.getElementById('detail-destination-url') as HTMLInputElement).value = route.destination_url;
  (document.getElementById('detail-method') as HTMLSelectElement).value = route.method;
  (document.getElementById('detail-rate-limit') as HTMLInputElement).value = String(route.rate_limit);
  (document.getElementById('detail-max-payload-bytes') as HTMLInputElement).value = String(route.max_payload_bytes);
  (document.getElementById('detail-max-concurrent-deliveries') as HTMLInputElement).value = String(route.max_concurrent_deliveries);
  (document.getElementById('detail-content-scan-rules') as HTMLInputElement).value = JSON.stringify(route.content_scan_rules || []);

  showRouteDetailModal();
}

async function saveRouteDetail(): Promise<void> {
  const routeId = state.currentRouteId;
  if (!routeId) return;

  const route = state.routes.find((r) => r.id === routeId);
  if (!route) return;

  const name = (document.getElementById('detail-name') as HTMLInputElement).value.trim();
  const destinationUrl = (document.getElementById('detail-destination-url') as HTMLInputElement).value.trim();
  const method = (document.getElementById('detail-method') as HTMLSelectElement).value;
  const rateLimit = parseInt((document.getElementById('detail-rate-limit') as HTMLInputElement).value, 10);
  const maxPayloadBytes = parseInt((document.getElementById('detail-max-payload-bytes') as HTMLInputElement).value, 10);
  const maxConcurrentDeliveries = parseInt((document.getElementById('detail-max-concurrent-deliveries') as HTMLInputElement).value, 10);
  const contentScanRulesRaw = (document.getElementById('detail-content-scan-rules') as HTMLInputElement).value.trim();

  let contentScanRules: Record<string, any>[] = [];
  if (contentScanRulesRaw) {
    try {
      contentScanRules = JSON.parse(contentScanRulesRaw);
    } catch {
      showError('Invalid JSON for content scan rules');
      return;
    }
  }

  const updates: Partial<Route> = {
    name: name || route.name,
    destination_url: destinationUrl || route.destination_url,
    method: method || route.method,
    rate_limit: isNaN(rateLimit) ? route.rate_limit : Math.max(1, Math.min(1000, rateLimit)),
    max_payload_bytes: isNaN(maxPayloadBytes) ? route.max_payload_bytes : Math.max(1, Math.min(10485760, maxPayloadBytes)),
    max_concurrent_deliveries: isNaN(maxConcurrentDeliveries) ? route.max_concurrent_deliveries : Math.max(1, Math.min(1000, maxConcurrentDeliveries)),
    content_scan_rules: contentScanRules,
  };

  try {
    const updated = await apiRequest<Route>(API_ENDPOINTS.UPDATE_ROUTE(routeId), {
      method: 'PUT',
      body: JSON.stringify(updates),
    });
    Object.assign(route, updated);
    updateRoutesUI(state.routes);
    hideRouteDetailModal();
    showSuccess('Route updated successfully');
  } catch (error) {
    showError(error instanceof Error ? error.message : 'Failed to update route');
  }
}

async function revealSigningSecret(routeId: string): Promise<void> {
  try {
    const result = await apiRequest<{ id: string; signing_secret: string }>(API_ENDPOINTS.SIGNING_SECRET(routeId));
    if (result.signing_secret) {
      showSigningSecretModal(result.signing_secret);
    } else {
      showError('No signing secret available');
    }
  } catch (error) {
    showError(error instanceof Error ? error.message : 'Failed to reveal signing secret');
  }
}

async function copySigningSecret(): Promise<void> {
  const input = document.getElementById('revealed-signing-secret');
  if (!input) return;

  try {
    await navigator.clipboard.writeText((input as HTMLInputElement).value);
    showSuccess('Signing secret copied to clipboard');
    dismissSigningSecret();
  } catch {
    showError('Failed to copy to clipboard');
  }
}

function dismissSigningSecret(): void {
  const input = document.getElementById('revealed-signing-secret');
  if (input) {
    (input as HTMLInputElement).value = '';
    hideSigningSecretModal();
  }
}

function closeRouteDetail(): void {
  hideRouteDetailModal();
  state.currentRouteId = null;
}

async function loadAdminData(): Promise<void> {
  try {
    const result = await apiRequest<{ admin_allowed_ips: string }>(API_ENDPOINTS.ADMIN_IPS);
    const ipsTextarea = document.getElementById('admin-allowed-ips') as HTMLTextAreaElement;
    if (ipsTextarea && result.admin_allowed_ips) {
      ipsTextarea.value = result.admin_allowed_ips;
    }
  } catch {
    // Admin section may not be accessible without proper permissions
  }
}

async function saveAdminIps(ips: string): Promise<void> {
  const statusEl = document.getElementById('admin-ips-status');
  if (statusEl) {
    statusEl.textContent = 'Saving...';
  }

  try {
    await apiRequest(API_ENDPOINTS.ADMIN_IPS, {
      method: 'PUT',
      body: JSON.stringify({ admin_allowed_ips: ips }),
    });
    if (statusEl) {
      statusEl.textContent = 'Saved successfully';
      statusEl.classList.add('text-safe-accent');
      setTimeout(() => {
        statusEl.textContent = '';
        statusEl.classList.remove('text-safe-accent');
      }, 3000);
    }
  } catch (error) {
    if (statusEl) {
      statusEl.textContent = error instanceof Error ? error.message : 'Failed to save';
      statusEl.classList.add('text-safe-danger');
      setTimeout(() => {
        statusEl.textContent = '';
        statusEl.classList.remove('text-safe-danger');
      }, 3000);
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
    const response = await fetch(API_BASE + '/v1/rates?base=USD&symbols=NGN,EUR,GBP,ZAR,KES,GHS,CAD,AUD');
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
      errorEl.textContent = error instanceof Error ? (error.message.includes('Failed to fetch') ? 'Payment failed' : error.message) : 'Payment failed';
      errorEl.classList.remove('hidden');
    }
  }
}


async function refreshData(): Promise<void> {
  await loadDashboardData();
}

const SafeRouteApi = {
  createRoute,
  openRouteDetail,
  saveRouteDetail,
  closeRouteDetail,
  revealSigningSecret,
  copySigningSecret,
  dismissSigningSecret,
  loadAdminData,
  saveAdminIps,
  deleteRoute,
  replayLog,
  retryWebhook,
  formatDate,
  loadDashboardData,
  loadPaymentHistory,
  loadWebhookFailures,
  refreshData,
  get state() {
    return state;
  },
};

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', initApp);
} else {
  initApp();
}

declare global {
  interface Window {
    SafeRoute: SafeRouteApi;
  }
}

window.SafeRoute = SafeRouteApi;
