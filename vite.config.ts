import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Finora Mobile — phone-only build (port 4321). In dev, /api is proxied to the
// deployed Flask backend so requests stay same-origin (no CORS needed).
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    host: '0.0.0.0',
    port: 4321,
    allowedHosts: ['.e2b.app', '.e2b.dev', 'localhost', '127.0.0.1'],
    proxy: {
      '/api': { target: 'https://finora-api-dio1.onrender.com', changeOrigin: true },
      '/test': { target: 'https://finora-api-dio1.onrender.com', changeOrigin: true },
    },
  },
})
