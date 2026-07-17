import { describe, it, expect, beforeEach, vi } from 'vitest';
import { apiRequest } from './api';

describe('apiRequest', () => {
  beforeEach(() => {
    localStorage.clear();
    vi.resetAllMocks();
  });

  it('makes a GET request and returns JSON', async () => {
    const mockData = { id: '1', name: 'Test' };
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'Content-Type': 'application/json' }),
      json: () => Promise.resolve(mockData),
    });

    const result = await apiRequest('/test');
    expect(result).toEqual(mockData);
    expect(fetch).toHaveBeenCalledWith('/test', expect.objectContaining({
      headers: expect.objectContaining({
        'Content-Type': 'application/json',
      }),
    }));
  });

  it('handles 401 by clearing token and redirecting', async () => {
    localStorage.setItem('saferoute_token', 'test-token');
    const mockLocation = { href: '' };
    Object.defineProperty(window, 'location', { value: mockLocation, writable: true });

    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 401,
      headers: new Headers(),
    });

    await expect(apiRequest('/test')).rejects.toThrow('Unauthorized');
    expect(localStorage.getItem('saferoute_token')).toBeNull();
    expect(mockLocation.href).toBe('/login.html');
  });

  it('handles 404 with JSON error detail', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 404,
      headers: new Headers({ 'Content-Type': 'application/json' }),
      json: () => Promise.resolve({ detail: 'Not found' }),
    });

    await expect(apiRequest('/test')).rejects.toThrow('Not found');
  });

  it('handles 500 with non-JSON response', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      headers: new Headers({ 'Content-Type': 'text/plain' }),
    });

    await expect(apiRequest('/test')).rejects.toThrow('HTTP 500');
  });

  it('includes auth header when token exists', async () => {
    localStorage.setItem('saferoute_token', 'valid-token');

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'Content-Type': 'application/json' }),
      json: () => Promise.resolve({}),
    });

    await apiRequest('/test');
    expect(fetch).toHaveBeenCalledWith('/test', expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: 'Bearer valid-token',
      }),
    }));
  });

  it('merges custom headers with auth headers', async () => {
    localStorage.setItem('saferoute_token', 'valid-token');

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 200,
      headers: new Headers({ 'Content-Type': 'application/json' }),
      json: () => Promise.resolve({}),
    });

    await apiRequest('/test', {
      headers: { 'X-Custom': 'value' },
    });

    expect(fetch).toHaveBeenCalledWith('/test', expect.objectContaining({
      headers: expect.objectContaining({
        Authorization: 'Bearer valid-token',
        'X-Custom': 'value',
      }),
    }));
  });

  it('handles 204 No Content', async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      status: 204,
      headers: new Headers(),
    });

    const result = await apiRequest('/test');
    expect(result).toBeNull();
  });

  it('handles network errors', async () => {
    global.fetch = vi.fn().mockRejectedValue(new Error('Network error'));

    await expect(apiRequest('/test')).rejects.toThrow('Network error');
  });
});
