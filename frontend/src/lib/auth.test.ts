import { describe, it, expect, beforeEach, vi } from 'vitest';
import { getToken, setToken, clearToken, isAuthenticated, verifyToken, logout } from './auth';

describe('auth', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetAllMocks();
  });

  describe('getToken', () => {
    it('returns null when no token exists', () => {
      expect(getToken()).toBeNull();
    });

    it('returns token when it exists', () => {
      localStorage.setItem('saferoute_token', 'test-token');
      expect(getToken()).toBe('test-token');
    });
  });

  describe('setToken', () => {
    it('stores token in localStorage', () => {
      setToken('new-token');
      expect(localStorage.getItem('saferoute_token')).toBe('new-token');
    });
  });

  describe('clearToken', () => {
    it('removes token from localStorage', () => {
      localStorage.setItem('saferoute_token', 'test-token');
      clearToken();
      expect(localStorage.getItem('saferoute_token')).toBeNull();
    });
  });

  describe('isAuthenticated', () => {
    it('returns false when no token exists', () => {
      expect(isAuthenticated()).toBe(false);
    });

    it('returns true when token exists', () => {
      localStorage.setItem('saferoute_token', 'test-token');
      expect(isAuthenticated()).toBe(true);
    });
  });

  describe('verifyToken', () => {
    it('returns false when no token exists', async () => {
      const result = await verifyToken();
      expect(result).toBe(false);
    });

    it('returns true when API confirms token is valid', async () => {
      localStorage.setItem('saferoute_token', 'valid-token');
      global.fetch = vi.fn().mockResolvedValue({ ok: true });

      const result = await verifyToken();
      expect(result).toBe(true);
    });

    it('returns false when API returns 401', async () => {
      localStorage.setItem('saferoute_token', 'invalid-token');
      global.fetch = vi.fn().mockResolvedValue({ ok: false });

      const result = await verifyToken();
      expect(result).toBe(false);
    });

    it('returns false on network error', async () => {
      localStorage.setItem('saferoute_token', 'test-token');
      global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

      const result = await verifyToken();
      expect(result).toBe(false);
    });
  });

  describe('logout', () => {
    it('clears token and redirects to login', async () => {
      localStorage.setItem('saferoute_token', 'test-token');
      const mockLocation = { href: '' };
      Object.defineProperty(window, 'location', { value: mockLocation, writable: true });

      await logout();

      expect(localStorage.getItem('saferoute_token')).toBeNull();
      expect(mockLocation.href).toBe('/login.html');
    });
  });
});
