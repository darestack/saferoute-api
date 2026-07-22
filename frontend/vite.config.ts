import { defineConfig } from 'vite';
import { resolve } from 'path';
// Vite proxy uses http-proxy-middleware under the hood; import here is only
// needed if we want typed access to its options. For our bypass needs the
// object shape below is sufficient without adding this dependency.
// import { createProxyMiddleware } from 'http-proxy-middleware';

export default defineConfig({
  root: '.',
  publicDir: 'public',
  build: {
    outDir: '../frontend-dist',
    emptyOutDir: true,
    rollupOptions: {
      input: {
        main: resolve(__dirname, 'index.html'),
        dashboard: resolve(__dirname, 'dashboard.html'),
        login: resolve(__dirname, 'login.html'),
        callback: resolve(__dirname, 'auth/callback.html'),
        changelog: resolve(__dirname, 'changelog.html'),
        terms: resolve(__dirname, 'terms.html'),
        privacy: resolve(__dirname, 'privacy.html'),
      },
    },
  },
  server: {
    port: 3000,
    open: '/index.html',
    proxy: {
      '/auth/oauth': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/auth/callback': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
        bypass(req, res, proxyOptions) {
          // Do NOT proxy the static callback HTML page.
          if (req.url && req.url.endsWith('.html')) {
            return req.url;
          }
        },
      },
      '/v1': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/internal': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/health': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/rates': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
});
