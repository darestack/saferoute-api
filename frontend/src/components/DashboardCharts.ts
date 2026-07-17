// Dashboard charts using Chart.js

export function initCharts(routes: any[]): void {
  initRequestVolumeChart(routes);
  initResponseStatusChart(routes);
}

function initRequestVolumeChart(routes: any[]): void {
  const canvas = document.getElementById('requestVolumeChart');
  if (!(canvas instanceof HTMLCanvasElement)) return;

  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  const labels = Array.from({ length: 7 }, (_, i) => {
    const d = new Date();
    d.setDate(d.getDate() - (6 - i));
    return d.toLocaleDateString('en-US', { weekday: 'short' });
  });

  new Chart(ctx, {
    type: 'bar',
    data: {
      labels,
      datasets: [
        {
          label: 'Requests',
          data: labels.map(() => Math.floor(Math.random() * 1000) + 100),
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

function initResponseStatusChart(routes: any[]): void {
  const canvas = document.getElementById('responseStatusChart');
  if (!(canvas instanceof HTMLCanvasElement)) return;

  const ctx = canvas.getContext('2d');
  if (!ctx) return;

  new Chart(ctx, {
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
