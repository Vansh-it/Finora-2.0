import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Finora Mobile — phone-only build (port 4321). In dev, /api is proxied to a
// Flask backend so requests stay same-origin (no CORS needed). Defaults to the
// local backend (run: cd backend && python app.py). To target a deployed API
// instead: VITE_PROXY_TARGET=https://finora-api-dio1.onrender.com npm run dev
const proxyTarget = (process.env.VITE_PROXY_TARGET ?? 'http://localhost:8000').replace(/\/+$/, '')

export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 4321,
    allowedHosts: ['.e2b.app', '.e2b.dev', 'localhost', '127.0.0.1'],
    proxy: {
      '/api': { target: proxyTarget, changeOrigin: true },
      '/test': { target: proxyTarget, changeOrigin: true },
    },
  },
})
