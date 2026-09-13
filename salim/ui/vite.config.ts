import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

const API_TARGET = process.env.API_TARGET ?? 'http://localhost:8000'

// In dev the API is proxied under /api so the browser sees a single origin and
// CORS never comes up. A deployed build talks to the API directly and relies on
// the CORS middleware in api/main.py instead (see VITE_API_BASE_URL).
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ''),
      },
    },
  },
})
