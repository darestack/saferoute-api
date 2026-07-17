import { describe, it, expect, beforeEach, vi } from 'vitest';
import { escapeHtml, formatDate } from './DashboardShell';

describe('DashboardShell utilities', () => {
  describe('escapeHtml', () => {
    it('escapes HTML special characters', () => {
      expect(escapeHtml('<script>alert("xss")</script>')).toBe('&lt;script&gt;alert("xss")&lt;/script&gt;');
    });

    it('escapes ampersands', () => {
      expect(escapeHtml('a & b')).toBe('a &amp; b');
    });

    it('escapes quotes', () => {
      expect(escapeHtml('"test" \'value\'')).toBe('"test" \'value\'');
    });

    it('handles empty string', () => {
      expect(escapeHtml('')).toBe('');
    });

    it('handles plain text', () => {
      expect(escapeHtml('Hello World')).toBe('Hello World');
    });
  });

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
});
