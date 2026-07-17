// Dashboard tables: routes, logs, and payment history rendering

import { Route, Payment, LogEntry } from '../types';
import { formatDate } from './DashboardShell';

/**
 * Create a table cell element with safe text content.
 * Uses textContent to prevent XSS — never uses innerHTML with user data.
 */
function createCell(text: string, tag: string = 'td', className?: string): HTMLTableCellElement {
  const cell = document.createElement(tag);
  cell.className = className || '';
  cell.textContent = text;
  return cell as HTMLTableCellElement;
}

export function updateRoutesUI(routes: Route[]): void {
  const tbody = document.getElementById('routes-list');
  if (!tbody) return;

  // Clear existing content safely
  while (tbody.firstChild) {
    tbody.removeChild(tbody.firstChild);
  }

  if (routes.length === 0) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 5;
    td.className = 'px-6 py-12 text-center text-safe-muted';
    td.innerHTML = `
      <div class="flex flex-col items-center gap-3">
        <svg class="w-12 h-12 text-safe-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101"/>
        </svg>
        <p>No routes yet. Create your first route to get started.</p>
      </div>
    `;
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  routes.forEach((route) => {
    const tr = document.createElement('tr');
    tr.className = 'hover:bg-safe-surface/50';

    // Route name + slug
    const nameCell = createCell('');
    const nameDiv = document.createElement('div');
    const nameEl = document.createElement('div');
    nameEl.className = 'font-medium';
    nameEl.textContent = route.name;
    const slugEl = document.createElement('div');
    slugEl.className = 'text-sm text-safe-muted font-mono';
    slugEl.textContent = route.slug;
    nameDiv.appendChild(nameEl);
    nameDiv.appendChild(slugEl);
    nameCell.appendChild(nameDiv);
    tr.appendChild(nameCell);

    // Status badge
    const statusCell = createCell('');
    const badge = document.createElement('span');
    badge.className = `px-2 py-1 text-xs rounded-full ${route.is_active ? 'bg-safe-accent/20 text-safe-accent' : 'bg-safe-muted/20 text-safe-muted'}`;
    badge.textContent = route.is_active ? 'Active' : 'Inactive';
    statusCell.appendChild(badge);
    tr.appendChild(statusCell);

    // Request count
    const countCell = createCell(route.requests_count.toLocaleString(), 'td', 'px-6 py-4 text-sm');
    tr.appendChild(countCell);

    // Updated date
    const dateCell = createCell(formatDate(route.updated_at), 'td', 'px-6 py-4 text-sm text-safe-muted');
    tr.appendChild(dateCell);

    // Actions
    const actionCell = document.createElement('td');
    actionCell.className = 'px-6 py-4 text-right';
    const editBtn = document.createElement('button');
    editBtn.className = 'text-safe-muted hover:text-safe-text text-sm';
    editBtn.textContent = 'Edit';
    editBtn.setAttribute('data-route-id', route.id);
    editBtn.addEventListener('click', () => {
      (window as any).SafeRoute.editRoute(route.id);
    });
    actionCell.appendChild(editBtn);
    tr.appendChild(actionCell);

    tbody.appendChild(tr);
  });
}

export function updateLogsUI(logs: LogEntry[]): void {
  const tbody = document.getElementById('logs-list');
  if (!tbody) return;

  // Clear existing content safely
  while (tbody.firstChild) {
    tbody.removeChild(tbody.firstChild);
  }

  if (logs.length === 0) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 5;
    td.className = 'px-6 py-12 text-center text-safe-muted';
    td.textContent = 'No logs yet';
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  logs.forEach((log) => {
    const tr = document.createElement('tr');
    tr.className = 'hover:bg-safe-surface/50';

    const statusColor = getStatusColor(log.status_code);

    const routeCell = createCell(log.route_name || log.route_id, 'td', 'px-6 py-4 text-sm');
    tr.appendChild(routeCell);

    const statusCell = document.createElement('td');
    statusCell.className = 'px-6 py-4';
    const badge = document.createElement('span');
    badge.className = `px-2 py-1 text-xs rounded-full ${statusColor}`;
    badge.textContent = String(log.status_code || '—');
    statusCell.appendChild(badge);
    tr.appendChild(statusCell);

    const timeCell = createCell(formatDate(log.created_at), 'td', 'px-6 py-4 text-sm text-safe-muted');
    tr.appendChild(timeCell);

    const durationCell = createCell(`${log.duration_ms || '—'}ms`, 'td', 'px-6 py-4 text-sm');
    tr.appendChild(durationCell);

    const actionCell = document.createElement('td');
    actionCell.className = 'px-6 py-4 text-right';
    const replayBtn = document.createElement('button');
    replayBtn.className = 'text-safe-muted hover:text-safe-text text-sm';
    replayBtn.textContent = 'Replay';
    replayBtn.setAttribute('data-route-id', log.route_id);
    replayBtn.setAttribute('data-log-id', String(log.id));
    replayBtn.addEventListener('click', () => {
      (window as any).SafeRoute.replayLog(log.route_id, log.id);
    });
    actionCell.appendChild(replayBtn);
    tr.appendChild(actionCell);

    tbody.appendChild(tr);
  });
}

export function renderPaymentHistory(payments: Payment[]): void {
  const tbody = document.getElementById('payment-history-body');
  if (!tbody) return;

  // Clear existing content safely
  while (tbody.firstChild) {
    tbody.removeChild(tbody.firstChild);
  }

  if (payments.length === 0) {
    const tr = document.createElement('tr');
    const td = document.createElement('td');
    td.colSpan = 6;
    td.className = 'px-6 py-8 text-center text-safe-muted';
    td.textContent = 'No payment history yet.';
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }

  payments.forEach((payment) => {
    const tr = document.createElement('tr');
    tr.className = 'hover:bg-safe-surface/50';

    const refCell = createCell(payment.reference, 'td', 'px-6 py-4 text-sm font-mono');
    tr.appendChild(refCell);

    const tierCell = createCell(payment.tier, 'td', 'px-6 py-4 text-sm capitalize');
    tr.appendChild(tierCell);

    const amountCell = createCell(`${(payment.amount / 100).toLocaleString()} NGN`, 'td', 'px-6 py-4 text-sm');
    tr.appendChild(amountCell);

    const creditsCell = createCell(payment.credits_to_add.toLocaleString(), 'td', 'px-6 py-4 text-sm');
    tr.appendChild(creditsCell);

    const statusCell = document.createElement('td');
    statusCell.className = 'px-6 py-4';
    const badge = document.createElement('span');
    const statusClass = payment.status === 'success'
      ? 'bg-safe-accent/20 text-safe-accent'
      : payment.status === 'failed'
        ? 'bg-safe-danger/20 text-safe-danger'
        : 'bg-safe-warning/20 text-safe-warning';
    badge.className = `px-2 py-1 text-xs rounded-full ${statusClass}`;
    badge.textContent = payment.status;
    statusCell.appendChild(badge);
    tr.appendChild(statusCell);

    const dateCell = createCell(formatDate(payment.created_at), 'td', 'px-6 py-4 text-sm text-safe-muted');
    tr.appendChild(dateCell);

    tbody.appendChild(tr);
  });
}

function getStatusColor(statusCode: number): string {
  if (statusCode >= 200 && statusCode < 300) return 'bg-safe-accent/20 text-safe-accent';
  if (statusCode >= 400 && statusCode < 500) return 'bg-safe-warning/20 text-safe-warning';
  return 'bg-safe-danger/20 text-safe-danger';
}
