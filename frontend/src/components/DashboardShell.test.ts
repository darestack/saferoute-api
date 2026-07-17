import { describe, it, expect } from 'vitest';
import { formatDate, showSection, showError, showSuccess } from './DashboardShell';

describe('DashboardShell utilities', () => {
  describe('formatDate', () => {
    it('formats ISO date string correctly', () => {
      const result = formatDate('2024-01-15T10:30:00Z');
      expect(result).toMatch(/Jan 15, 2024/);
    });

    it('handles invalid date gracefully', () => {
      const result = formatDate('invalid-date');
      expect(result).toMatch(/Invalid Date|NaN/);
    });
  });

  describe('showError', () => {
    it('sets error message and shows element', () => {
      const errorEl = document.createElement('div');
      errorEl.id = 'auth-error';
      errorEl.classList.add('hidden');
      document.body.appendChild(errorEl);

      showError('Test error');

      expect(errorEl.textContent).toBe('Test error');
      expect(errorEl.classList.contains('hidden')).toBe(false);

      document.body.removeChild(errorEl);
    });
  });

  describe('showSuccess', () => {
    it('sets success message and shows element', () => {
      const errorEl = document.createElement('div');
      errorEl.id = 'auth-error';
      errorEl.classList.add('hidden');
      document.body.appendChild(errorEl);

      showSuccess('Test success');

      expect(errorEl.textContent).toBe('Test success');
      expect(errorEl.classList.contains('hidden')).toBe(false);

      document.body.removeChild(errorEl);
    });
  });
});
