// Dashboard tables: routes, logs, and payment history rendering

import { Route, Payment, LogEntry } from '../types';
import { formatDate, escapeHtml } from './DashboardShell';

export function updateRoutesUI(routes: Route[]): void {
  const tbody = document.getElementById('routes-list');
  if (!tbody) return;

  if (routes.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="5" class="px-6 py-12 text-center text-safe-muted">
          <div class="flex flex-col items-center gap-3">
            <svg class="w-12 h-12 text-safe-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101"/>
            </svg>
            <p>No routes yet. Create your first route to get started.</p>
          </div>
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = routes
    .map(
      (route) => `
        <tr class="hover:bg-safe-surface/50">
          <td class="px-6 py-4">
            <div class="flex items-center gap-3">
              <div>
                <div class="font-medium">${escapeHtml(route.name)}</div>
                <div class="text-sm text-safe-muted font-mono">${escapeHtml(route.slug)}</div>
              </div>
            </div>
          </td>
          <td class="px-6 py-4">
            <span class="px-2 py-1 text-xs rounded-full ${
              route.is_active
                ? 'bg-safe-accent/20 text-safe-accent'
                : 'bg-safe-muted/20 text-safe-muted'
            }">${route.is_active ? 'Active' : 'Inactive'}</span>
          </td>
          <td class="px-6 py-4 text-sm">${route.requests_count.toLocaleString()}</td>
          <td class="px-6 py-4 text-sm text-safe-muted">${formatDate(route.updated_at)}</td>
          <td class="px-6 py-4 text-right">
            <button data-route-id="${escapeHtml(route.id)}" class="edit-route-btn text-safe-muted hover:text-safe-text text-sm">Edit</button>
          </td>
        </tr>
      `
    )
    .join('');

  tbody.querySelectorAll('.edit-route-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const routeId = btn.getAttribute('data-route-id');
      if (routeId) {
        (window as any).SafeRoute.editRoute(routeId);
      }
    });
  });
}

export function updateLogsUI(logs: LogEntry[]): void {
  const tbody = document.getElementById('logs-list');
  if (!tbody) return;

  if (logs.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="5" class="px-6 py-12 text-center text-safe-muted">
          No logs yet
        </td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = logs
    .map((log) => {
      const statusColor = getStatusColor(log.status_code);
      return `
        <tr class="hover:bg-safe-surface/50">
          <td class="px-6 py-4 text-sm">${escapeHtml(log.route_name || log.route_id)}</td>
          <td class="px-6 py-4">
            <span class="px-2 py-1 text-xs rounded-full ${statusColor}">${log.status_code || '—'}</span>
          </td>
          <td class="px-6 py-4 text-sm text-safe-muted">${formatDate(log.created_at)}</td>
          <td class="px-6 py-4 text-sm">${log.duration_ms || '—'}ms</td>
          <td class="px-6 py-4 text-right">
            <button data-route-id="${escapeHtml(log.route_id)}" data-log-id="${log.id}" class="replay-log-btn text-safe-muted hover:text-safe-text text-sm">Replay</button>
          </td>
        </tr>
      `;
    })
    .join('');

  tbody.querySelectorAll('.replay-log-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const routeId = btn.getAttribute('data-route-id');
      const logId = btn.getAttribute('data-log-id');
      if (routeId && logId) {
        (window as any).SafeRoute.replayLog(routeId, parseInt(logId, 10));
      }
    });
  });
}

export function renderPaymentHistory(payments: Payment[]): void {
  const tbody = document.getElementById('payment-history-body');
  if (!tbody) return;

  if (payments.length === 0) {
    tbody.innerHTML = `
      <tr>
        <td colspan="6" class="px-6 py-8 text-center text-safe-muted">No payment history yet.</td>
      </tr>
    `;
    return;
  }

  tbody.innerHTML = payments
    .map((payment) => `
      <tr class="hover:bg-safe-surface/50">
        <td class="px-6 py-4 text-sm font-mono">${escapeHtml(payment.reference)}</td>
        <td class="px-6 py-4 text-sm capitalize">${escapeHtml(payment.tier)}</td>
        <td class="px-6 py-4 text-sm">${(payment.amount / 100).toLocaleString()} NGN</td>
        <td class="px-6 py-4 text-sm">${payment.credits_to_add.toLocaleString()}</td>
        <td class="px-6 py-4">
          <span class="px-2 py-1 text-xs rounded-full ${
            payment.status === 'success'
              ? 'bg-safe-accent/20 text-safe-accent'
              : payment.status === 'failed'
                ? 'bg-safe-danger/20 text-safe-danger'
                : 'bg-safe-warning/20 text-safe-warning'
          }">${payment.status}</span>
        </td>
        <td class="px-6 py-4 text-sm text-safe-muted">${formatDate(payment.created_at)}</td>
      </tr>
    `)
    .join('');
}

function getStatusColor(statusCode: number): string {
  if (statusCode >= 200 && statusCode < 300) return 'bg-safe-accent/20 text-safe-accent';
  if (statusCode >= 400 && statusCode < 500) return 'bg-safe-warning/20 text-safe-warning';
  return 'bg-safe-danger/20 text-safe-danger';
}
