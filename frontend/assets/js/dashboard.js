// SafeRoute Dashboard JavaScript

const API_BASE = '';

const state = {
    user: null,
    routes: [],
    logs: [],
    stats: {},
    isLoading: false
};

document.addEventListener('DOMContentLoaded', () => {
    initApp();
});

async function initApp() {
    await checkAuth();
    setupEventListeners();
    await checkPaymentResult();
    await loadDashboardData();
}

async function checkPaymentResult() {
    const urlParams = new URLSearchParams(window.location.search);
    const status = urlParams.get('status');
    const reference = urlParams.get('reference');
    const trxref = urlParams.get('trxref');

    if (status && (reference || trxref)) {
        const ref = reference || trxref;
        const token = localStorage.getItem('saferoute_token');

        try {
            const response = await fetch(`${API_BASE}/v1/payments/verify/${encodeURIComponent(ref)}`, {
                headers: { 'Authorization': `Bearer ${token}` }
            });

            const data = await response.json();

            if (response.ok && data.status === 'success') {
                showSuccess(`Payment successful! ${data.credits_added.toLocaleString()} credits added to your account.`);
            } else {
                showError(data.detail || 'Payment verification failed');
            }
        } catch (error) {
            console.error('Payment verification error:', error);
        }

        // Clean URL
        window.history.replaceState({}, document.title, window.location.pathname);
    }
}

async function checkAuth() {
    const token = localStorage.getItem('saferoute_token');
    if (!token) {
        window.location.href = 'login.html';
        return;
    }
    
    try {
        const response = await fetch(`${API_BASE}/v1/me`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });
        
        if (!response.ok) {
            localStorage.removeItem('saferoute_token');
            window.location.href = 'login.html';
            return;
        }
        
        state.user = await response.json();
        updateUserUI();
    } catch (error) {
        console.error('Auth check failed:', error);
        window.location.href = 'login.html';
    }
}

function setupEventListeners() {
    document.querySelectorAll('.nav-link').forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            const section = link.getAttribute('href').substring(1);
            showSection(section);
            
            document.querySelectorAll('.nav-link').forEach(l => {
                l.classList.remove('bg-safe-accent/10', 'text-safe-accent');
                l.classList.add('text-safe-muted');
            });
            link.classList.remove('text-safe-muted');
            link.classList.add('bg-safe-accent/10', 'text-safe-accent');
        });
    });
}

function showSection(sectionId) {
    window.location.hash = sectionId;
    document.querySelectorAll('[id$="-section"]').forEach(section => {
        section.classList.add('hidden');
    });
    
    const section = document.getElementById(`${sectionId}-section`);
    if (section) {
        section.classList.remove('hidden');
        section.classList.add('animate-fade-in');
    }
}

async function loadDashboardData() {
    state.isLoading = true;
    updateLoadingState();
    
    try {
        const token = localStorage.getItem('saferoute_token');
        const headers = { 'Authorization': `Bearer ${token}` };
        
        const [routesRes, userRes] = await Promise.all([
            fetch(`${API_BASE}/v1/routes?limit=100`, { headers }),
            fetch(`${API_BASE}/v1/me`, { headers })
        ]);
        
        if (routesRes.ok) {
            state.routes = await routesRes.json();
            await loadRoutesData();
            updateRoutesUI();
            initCharts();
        }
        
        if (userRes.ok) {
            state.user = await userRes.json();
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

async function loadRoutesData() {
    const token = localStorage.getItem('saferoute_token');
    const headers = { 'Authorization': `Bearer ${token}` };
    
    const statsPromises = state.routes.slice(0, 10).map(route =>
        fetch(`${API_BASE}/v1/routes/${route.id}/stats`, { headers })
            .then(res => res.ok ? res.json() : null)
            .catch((err) => { console.error('Failed to load route stats:', err); return null; })
    );
    
    const logsPromises = state.routes.slice(0, 5).map(route =>
        fetch(`${API_BASE}/v1/routes/${route.id}/logs?limit=5`, { headers })
            .then(res => res.ok ? res.json() : [])
            .catch((err) => { console.error('Failed to load route logs:', err); return []; })
    );
    
    const [statsResults, logsResults] = await Promise.all([
        Promise.all(statsPromises),
        Promise.all(logsPromises)
    ]);
    
    state.routes.forEach((route, i) => {
        route.stats = statsResults[i] || null;
    });

    const allLogs = logsResults.flat();
    allLogs.sort((a, b) => new Date(b.created_at) - new Date(a.created_at));
    state.logs = allLogs.slice(0, 20);

    updateStatsUI();
    updateLogsUI();
    await loadPaymentHistory();
}

function updateStatsUI() {
    let totalRequests = 0;
    let totalSuccessRate = 0;
    let totalLatency = 0;
    let latencyCount = 0;
    let routesWithStats = 0;
    
    state.routes.forEach(route => {
        totalRequests += route.requests_count || 0;
        
        if (route.stats) {
            routesWithStats++;
            totalSuccessRate += route.stats.success_rate_percent || 0;
            if (route.stats.avg_latency_ms != null) {
                totalLatency += route.stats.avg_latency_ms;
                latencyCount++;
            }
        }
    });
    
    const avgSuccessRate = routesWithStats > 0 ? totalSuccessRate / routesWithStats : 0;
    const avgLatency = latencyCount > 0 ? Math.round(totalLatency / latencyCount) : 0;
    
    animateCounter('total-requests', totalRequests);
    animateCounter('success-rate', Math.round(avgSuccessRate), '%');
    animateCounter('avg-response', avgLatency, 'ms');
    animateCounter('spam-blocked', 0);

    // Update credit balance from user profile
    const creditBalance = document.getElementById('credit-balance');
    const creditTier = document.getElementById('credit-tier');
    if (creditBalance && state.user) {
        creditBalance.textContent = state.user.credits.toLocaleString();
    }
    if (creditTier && state.user) {
        const tier = state.user.tier || 'free';
        creditTier.textContent = tier.charAt(0).toUpperCase() + tier.slice(1) + ' tier';
    }
}

function animateCounter(elementId, target, suffix = '') {
    const element = document.getElementById(elementId);
    if (!element) return;
    
    const duration = 1000;
    const start = 0;
    const startTime = performance.now();
    
    function update(currentTime) {
        const elapsed = currentTime - startTime;
        const progress = Math.min(elapsed / duration, 1);
        const easeOut = 1 - Math.pow(1 - progress, 3);
        const current = Math.floor(start + (target - start) * easeOut);
        
        element.textContent = current.toLocaleString() + suffix;
        
        if (progress < 1) {
            requestAnimationFrame(update);
        }
    }
    
    requestAnimationFrame(update);
}

function updateRoutesUI() {
    const container = document.getElementById('routes-list');
    if (!container) return;
    
    if (state.routes.length === 0) {
        container.innerHTML = `
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
    
    container.innerHTML = state.routes.map(route => `
        <tr class="hover:bg-safe-surface/30 transition-colors">
            <td class="px-6 py-4 whitespace-nowrap">
                <div class="flex items-center gap-3">
                    <div class="w-8 h-8 rounded-lg bg-safe-accent/10 flex items-center justify-center">
                        <svg class="w-4 h-4 text-safe-accent" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M13.828 10.172a4 4 0 00-5.656 0l-4 4a4 4 0 105.656 5.656l1.102-1.101"/>
                        </svg>
                    </div>
                    <div>
                        <div class="font-medium">${escapeHtml(route.name || 'Unnamed Route')}</div>
                        <div class="text-sm text-safe-muted">/${escapeHtml(route.slug)}</div>
                    </div>
                </div>
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
                <span class="px-2 py-1 text-xs font-medium rounded-full ${route.is_active ? 'bg-safe-accent/10 text-safe-accent' : 'bg-safe-muted/10 text-safe-muted'}">
                    ${route.is_active ? 'Active' : 'Inactive'}
                </span>
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-safe-muted">
                ${route.requests_count || 0} requests
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-safe-muted">
                ${formatDate(route.updated_at)}
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
                <div class="flex items-center gap-2">
                    <button onclick="editRoute('${escapeHtml(route.id)}')" class="p-1 text-safe-muted hover:text-safe-text transition-colors">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z"/>
                        </svg>
                    </button>
                    <button onclick="deleteRoute('${escapeHtml(route.id)}')" class="p-1 text-safe-muted hover:text-safe-danger transition-colors">
                        <svg class="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2" d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16"/>
                        </svg>
                    </button>
                </div>
            </td>
        </tr>
    `).join('');
}

function updateLogsUI() {
    const container = document.getElementById('logs-list');
    if (!container) return;
    
    if (state.logs.length === 0) {
        container.innerHTML = `
            <tr>
                <td colspan="5" class="px-6 py-12 text-center text-safe-muted">
                    No logs yet
                </td>
            </tr>
        `;
        return;
    }
    
    container.innerHTML = state.logs.map(log => `
        <tr class="hover:bg-safe-surface/30 transition-colors">
            <td class="px-6 py-4 whitespace-nowrap">
                <div class="flex items-center gap-3">
                    <div class="w-8 h-8 rounded-lg ${getStatusColor(log.status_code).bg} flex items-center justify-center">
                        ${getStatusIcon(log.status_code)}
                    </div>
                        <div>
                            <div class="font-medium">${escapeHtml('Route ' + log.route_id.slice(0, 8))}</div>
                            <div class="text-sm text-safe-muted">${escapeHtml('ID: ' + log.route_id.slice(0, 8))}</div>
                        </div>
                </div>
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
                <span class="px-2 py-1 text-xs font-medium rounded-full ${getStatusColor(log.status_code).text}">
                    ${log.status_code || 'N/A'}
                </span>
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-safe-muted">
                ${formatDate(log.created_at)}
            </td>
            <td class="px-6 py-4 whitespace-nowrap text-sm text-safe-muted">
                ${log.duration_ms || 0}ms
            </td>
            <td class="px-6 py-4 whitespace-nowrap">
                ${log.status_code && log.status_code >= 400 ? `
                    <button onclick="replayLog('${log.route_id}', '${escapeHtml(log.id)}')" class="text-safe-accent hover:text-safe-accent/80 text-sm font-medium transition-colors">
                        Replay
                    </button>
                ` : '<span class="text-safe-muted">-</span>'}
            </td>
        </tr>
    `).join('');
}

function getStatusColor(statusCode) {
    if (statusCode >= 200 && statusCode < 300) {
        return { bg: 'bg-safe-accent/10', text: 'text-safe-accent' };
    } else if (statusCode >= 400 && statusCode < 500) {
        return { bg: 'bg-safe-warning/10', text: 'text-safe-warning' };
    } else {
        return { bg: 'bg-safe-danger/10', text: 'text-safe-danger' };
    }
}

function getStatusIcon(statusCode) {
    if (statusCode >= 200 && statusCode < 300) {
        return '<svg class="w-4 h-4 text-safe-accent" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clip-rule="evenodd"/></svg>';
    } else if (statusCode >= 400 && statusCode < 500) {
        return '<svg class="w-4 h-4 text-safe-warning" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clip-rule="evenodd"/></svg>';
    } else {
        return '<svg class="w-4 h-4 text-safe-danger" fill="currentColor" viewBox="0 0 20 20"><path fill-rule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z" clip-rule="evenodd"/></svg>';
    }
}

function formatDate(dateString) {
    if (!dateString) return 'N/A';
    const date = new Date(dateString);
    const now = new Date();
    const diff = now - date;
    
    if (diff < 60000) return 'Just now';
    if (diff < 3600000) return `${Math.floor(diff / 60000)} min ago`;
    if (diff < 86400000) { const hours = Math.floor(diff / 3600000); return `${hours} hour${hours !== 1 ? 's' : ''} ago`; }
    
    return date.toLocaleDateString('en-US', {
        month: 'short',
        day: 'numeric',
        year: 'numeric'
    });
}

function updateLoadingState() {
    const elements = document.querySelectorAll('[data-loading]');
    elements.forEach(el => {
        if (state.isLoading) {
            el.classList.add('opacity-50', 'pointer-events-none');
        } else {
            el.classList.remove('opacity-50', 'pointer-events-none');
        }
    });
}

function updateUserUI() {
    if (!state.user) return;
    
    const userInitials = document.getElementById('user-initials');
    const userName = document.getElementById('user-name');
    const userEmail = document.getElementById('user-email');
    
    if (userInitials && state.user.full_name) {
        userInitials.textContent = state.user.full_name.split(' ').map(n => n[0]).join('').toUpperCase();
    } else if (userInitials && state.user.email) {
        userInitials.textContent = state.user.email.substring(0, 2).toUpperCase();
    }
    
    if (userName && state.user.full_name) {
        userName.textContent = state.user.full_name;
    } else if (userName && state.user.email) {
        userName.textContent = state.user.email;
    }
    
    if (userEmail && state.user.email) {
        userEmail.textContent = state.user.email;
    }
}

function showError(message) {
    const toast = document.createElement('div');
    toast.className = 'fixed bottom-4 right-4 bg-safe-danger text-white px-6 py-3 rounded-lg shadow-lg z-50 animate-slide-in';
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 5000);
}

function showSuccess(message) {
    const toast = document.createElement('div');
    toast.className = 'fixed bottom-4 right-4 bg-safe-accent text-white px-6 py-3 rounded-lg shadow-lg z-50 animate-slide-in';
    toast.textContent = message;
    document.body.appendChild(toast);
    setTimeout(() => toast.remove(), 3000);
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

async function apiCall(endpoint, options = {}) {
    const token = localStorage.getItem('saferoute_token');
    
    if (!token) {
        throw new Error('Authentication required');
    }
    
    try {
        const response = await fetch(endpoint, {
            ...options,
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${token}`,
                ...options.headers
            }
        });
        
        if (!response.ok) {
            if (response.status === 401 || response.status === 403) {
                localStorage.removeItem('saferoute_token');
                window.location.href = '/login.html';
                return;
            }
            const error = await response.json().catch(() => ({ message: 'Request failed' }));
            throw new Error(error.detail || error.message || `HTTP ${response.status}`);
        }
        
        if (response.status === 204) {
            return null;
        }
        
        return response.json();
    } catch (error) {
        if (error.name === 'TypeError' && error.message === 'Failed to fetch') {
            throw new Error('Network error. Please check your connection.');
        }
        throw error;
    }
}

async function createRoute(routeData) {
    try {
        const route = await apiCall(`${API_BASE}/v1/routes`, {
            method: 'POST',
            body: JSON.stringify(routeData)
        });
        state.routes.push(route);
        updateRoutesUI();
        showSuccess('Route created successfully');
        return route;
    } catch (error) {
        showError(error.message);
        throw error;
    }
}

async function editRoute(routeId) {
    const route = state.routes.find(r => r.id === routeId);
    if (!route) return;
    
    const newName = prompt('Route name:', route.name);
    if (newName && newName !== route.name) {
        try {
            const updated = await apiCall(`${API_BASE}/v1/routes/${routeId}`, {
                method: 'PUT',
                body: JSON.stringify({ name: newName })
            });
            Object.assign(route, updated);
            updateRoutesUI();
            showSuccess('Route updated successfully');
        } catch (error) {
            showError(error.message);
        }
    }
}

async function deleteRoute(routeId) {
    if (!confirm('Are you sure you want to delete this route?')) return;
    
    try {
        await apiCall(`${API_BASE}/v1/routes/${routeId}`, { method: 'DELETE' });
        state.routes = state.routes.filter(r => r.id !== routeId);
        updateRoutesUI();
        showSuccess('Route deleted successfully');
    } catch (error) {
        showError(error.message);
    }
}

let requestVolumeChart = null;
let responseStatusChart = null;

function initCharts() {
    const volumeCtx = document.getElementById('requestVolumeChart');
    const statusCtx = document.getElementById('responseStatusChart');
    
    if (!volumeCtx || !statusCtx) return;
    
    if (requestVolumeChart) requestVolumeChart.destroy();
    if (responseStatusChart) responseStatusChart.destroy();
    
    const days = Array.from({ length: 7 }, (_, i) => {
        const d = new Date();
        d.setDate(d.getDate() - (6 - i));
        return d.toLocaleDateString('en-US', { weekday: 'short' });
    });
    
    const volumes = Array.from({ length: 7 }, () => Math.floor(Math.random() * 100));
    const statuses = [65, 25, 10];
    
    requestVolumeChart = new Chart(volumeCtx, {
        type: 'bar',
        data: {
            labels: days,
            datasets: [{
                label: 'Deliveries',
                data: volumes,
                backgroundColor: 'rgba(16, 185, 129, 0.2)',
                borderColor: '#10b981',
                borderWidth: 1,
                borderRadius: 6
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: { legend: { display: false } },
            scales: {
                y: {
                    beginAtZero: true,
                    grid: { color: 'rgba(51, 65, 85, 0.3)' },
                    ticks: { color: '#94a3b8' }
                },
                x: {
                    grid: { display: false },
                    ticks: { color: '#94a3b8' }
                }
            }
        }
    });
    
    responseStatusChart = new Chart(statusCtx, {
        type: 'doughnut',
        data: {
            labels: ['Success', 'Failed', 'Timeout'],
            datasets: [{
                data: statuses,
                backgroundColor: [
                    'rgba(16, 185, 129, 0.8)',
                    'rgba(245, 158, 11, 0.8)',
                    'rgba(244, 63, 94, 0.8)'
                ],
                borderWidth: 0
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: {
                    position: 'bottom',
                    labels: { color: '#94a3b8', padding: 16 }
                }
            }
        }
    });
}

async function replayLog(routeId, logId) {
    try {
        await apiCall(`${API_BASE}/v1/routes/${routeId}/logs/${logId}/replay`, { method: 'POST' });
        showSuccess('Log replayed successfully');
        await loadDashboardData();
    } catch (error) {
        showError(error.message);
    }
}

async function purchaseCredits(tier) {
    const statusEl = document.getElementById('payment-status');
    const loadingEl = document.getElementById('payment-loading');
    const errorEl = document.getElementById('payment-error');

    statusEl.classList.remove('hidden');
    loadingEl.classList.remove('hidden');
    errorEl.classList.add('hidden');

    try {
        const response = await fetch(`${API_BASE}/v1/payments/initialize`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
                'Authorization': `Bearer ${localStorage.getItem('saferoute_token')}`
            },
            body: JSON.stringify({
                tier: tier,
                email: state.user.email
            })
        });

        const data = await response.json();
        if (!response.ok) {
            throw new Error(data.detail || 'Payment initialization failed');
        }

        // Redirect to Paystack
        window.location.href = data.authorization_url;
    } catch (error) {
        loadingEl.classList.add('hidden');
        errorEl.textContent = error.message;
        errorEl.classList.remove('hidden');
    }
}

async function loadPaymentHistory() {
    const token = localStorage.getItem('saferoute_token');
    if (!token) return;

    try {
        const response = await fetch(`${API_BASE}/v1/payments/history`, {
            headers: { 'Authorization': `Bearer ${token}` }
        });

        if (response.ok) {
            const payments = await response.json();
            renderPaymentHistory(payments);
        }
    } catch (error) {
        console.error('Failed to load payment history:', error);
    }
}

function renderPaymentHistory(payments) {
    const tbody = document.getElementById('payment-history-body');
    if (!tbody) return;

    if (payments.length === 0) {
        tbody.innerHTML = '<tr><td colspan="6" class="px-6 py-8 text-center text-safe-muted">No payment history yet.</td></tr>';
        return;
    }

    tbody.innerHTML = payments.map(payment => `
        <tr class="hover:bg-safe-surface/50">
            <td class="px-6 py-4 text-sm font-mono">${payment.reference}</td>
            <td class="px-6 py-4 text-sm capitalize">${payment.tier}</td>
            <td class="px-6 py-4 text-sm">${(payment.amount / 100).toLocaleString()} NGN</td>
            <td class="px-6 py-4 text-sm">${payment.credits_to_add.toLocaleString()}</td>
            <td class="px-6 py-4">
                <span class="px-2 py-1 text-xs rounded-full ${
                    payment.status === 'success' ? 'bg-safe-accent/20 text-safe-accent' :
                    payment.status === 'failed' ? 'bg-safe-danger/20 text-safe-danger' :
                    'bg-safe-warning/20 text-safe-warning'
                }">${payment.status}</span>
            </td>
            <td class="px-6 py-4 text-sm text-safe-muted">${formatDate(payment.created_at)}</td>
        </tr>
    `).join('');
}

window.SafeRoute = {
    state,
    createRoute,
    editRoute,
    deleteRoute,
    replayLog,
    formatDate,
    loadDashboardData,
    loadPaymentHistory,
    initCharts
};
