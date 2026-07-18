// Dashboard charts using Chart.js (loaded via CDN in dashboard.html)

import { Route } from '../types';

declare const Chart: any;

let requestVolumeChartInstance: any = null;
let responseStatusChartInstance: any = null;

export function initCharts(routes: Route[]): void {
  initRequestVolumeChart(routes);
  initResponseStatusChart(routes);
}

function destroyChart(instance: any): void {
  if (instance) {
    instance.destroy();
  }
}

function initRequestVolumeChart(routes: Route[]): void {
  destroyChart(requestVolumeChartInstance);

  const canvas = document.getElementById('requestVolumeChart');
  if (!(canvas instanceof HTMLCanvasElement)) return;

  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const labels = Array.from({ length: 7 }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - (6 - i));
    return d.toLocaleDateString('en-US', { weekday: 'short' });
  });

  // Use real route request counts if available, otherwise show zeros.
  // In production, fetch per-day stats from /v1/routes/{id}/stats.
  const requestCounts = routes.length > 0
    ? routes.map((r) => Math.max(0, r.requests_count || 0))
    : labels.map(() => 0);

  requestVolumeChartInstance = new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label: 'Requests',
          data: requestCounts.length > 0 ? requestCounts : labels.map(() => 0),
          backgroundColor: 'rgba(16, 185, 129, 0.2)',
          borderColor: '#10b981',
          borderWidth: 1,
          borderRadius: 8,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: { legend: { display: false } },
      scales: {
        y: {
          beginAtZero: true,
          grid: { color: 'rgba(51, 65, 85, 0.3)' },
          ticks: { color: '#94a3b8' },
        },
        x: {
          grid: { display: false },
          ticks: { color: '#94a3b8' },
        },
      },
    },
  });
}

function initResponseStatusChart(_routes: Route[]): void {
  destroyChart(responseStatusChartInstance);

  const canvas = document.getElementById('responseStatusChart');
  if (!(canvas instanceof HTMLCanvasElement)) return;

  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  // Placeholder data; replace with real stats from backend when available.
  responseStatusChartInstance = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['2xx Success', '4xx Client Error', '5xx Server Error'],
      datasets: [
        {
          data: [85, 10, 5],
          backgroundColor: ['#10b981', '#f59e0b', '#f43f5e'],
          borderWidth: 0,
          hoverOffset: 4,
        },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          position: 'bottom',
          labels: { color: '#94a3b8', padding: 20 },
        },
      },
    },
  });
}
