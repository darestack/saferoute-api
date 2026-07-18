// Dashboard shell: sidebar, modals, UI state, notifications

export function showSection(sectionId: string): void {
  document.querySelectorAll('[id$="-section"]').forEach((section) => {
    section.classList.add('hidden');
  });
  const section = document.getElementById(sectionId);
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
  const modal = document.getElementById('create-route-modal');
  if (modal) {
    modal.classList.remove('hidden');
    const firstInput = modal.querySelector('input');
    if (firstInput instanceof HTMLElement) {
      setTimeout(() => firstInput.focus(), 100);
    }

    const focusableElements = modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    const firstElement = focusableElements[0] as HTMLElement;
    const lastElement = focusableElements[focusableElements.length - 1] as HTMLElement;

    function trapFocus(e: KeyboardEvent) {
      if (e.key !== 'Tab') return;

      if (e.shiftKey) {
        if (document.activeElement === firstElement) {
          e.preventDefault();
          lastElement.focus();
        }
      } else {
        if (document.activeElement === lastElement) {
          e.preventDefault();
          firstElement.focus();
        }
      }
    }

    modal.addEventListener('keydown', trapFocus);
  }
}

export function hideCreateRouteModal(): void {
  const modal = document.getElementById('create-route-modal');
  if (modal) {
    modal.classList.add('hidden');
    const focusableElements = modal.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])');
    const firstElement = focusableElements[0] as HTMLElement;
    if (firstElement) {
      firstElement.focus();
    }
  }
}
