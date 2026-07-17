// Dashboard shell: sidebar, modals, UI state, notifications

export function showSection(sectionId: string): void {
  document.querySelectorAll('[id$="-section"]').forEach((section) => {
    section.classList.add('hidden');
  });
  const section = document.getElementById(`${sectionId}-section`);
  if (section) {
    section.classList.remove('hidden');
    section.classList.add('animate-fade-in');
  }
}

export function updateLoadingState(isLoading: boolean): void {
  const loadingEl = document.querySelector('[data-loading]');
  if (loadingEl) {
    loadingEl.classList.toggle('hidden', !isLoading);
  }
}

export function showError(message: string): void {
  const errorEl = document.getElementById('auth-error');
  if (errorEl) {
    errorEl.textContent = message;
    errorEl.classList.remove('hidden');
    setTimeout(() => errorEl.classList.add('hidden'), 5000);
  }
}

export function showSuccess(message: string): void {
  // Reuse error element for simplicity, or extend with toast system
  const errorEl = document.getElementById('auth-error');
  if (errorEl) {
    errorEl.textContent = message;
    errorEl.classList.remove('hidden');
    errorEl.classList.remove('bg-safe-danger/10', 'border-safe-danger/20', 'text-safe-danger');
    errorEl.classList.add('bg-safe-accent/10', 'border-safe-accent/20', 'text-safe-accent');
    setTimeout(() => errorEl.classList.add('hidden'), 5000);
  }
}

export function escapeHtml(text: string): string {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

export function formatDate(dateString: string): string {
  return new Date(dateString).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  });
}

export function toggleSidebar(): void {
  document.querySelector('.sidebar')?.classList.toggle('-translate-x-full');
}

export function showCreateRouteModal(): void {
  document.getElementById('create-route-modal')?.classList.remove('hidden');
}

export function hideCreateRouteModal(): void {
  document.getElementById('create-route-modal')?.classList.add('hidden');
}
