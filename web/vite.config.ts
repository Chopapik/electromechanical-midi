import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// W trybie dev Vite podaje frontend, a /api i /ws przekazuje do FastAPI
// (python -m host.web.server na porcie 8000).
export default defineConfig({
  plugins: [react()],
  server: {
    // Jawnie IPv4: domyslne "localhost" na macOS potrafi sluchac tylko ::1,
    // przez co http://127.0.0.1:5173 nie odpowiada.
    host: '127.0.0.1',
    port: 5173,
    strictPort: false,
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
      '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['src/test-setup.ts'],
    include: ['src/**/*.test.tsx', 'src/**/*.test.ts'],
    css: false,
  },
})
