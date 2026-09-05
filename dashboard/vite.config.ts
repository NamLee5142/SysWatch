import react from '@vitejs/plugin-react'
import { defineConfig } from 'vitest/config'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      // Same-origin in development, so the dev server needs no CORS grant of
      // its own. There is deliberately no rewrite: the backend serves the
      // API under /api too, so development and production address it
      // identically and a path that works in one works in the other.
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: true,
      },
    },
  },
  test: {
    // Component tests need a DOM; node has none.
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
  },
})
