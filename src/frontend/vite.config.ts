import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

export default defineConfig({
  // Relative asset URLs so the built app loads under any path prefix — the
  // server root (standalone) or a Home Assistant ingress prefix.
  base: './',
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      '/api': { target: 'http://localhost:8080', changeOrigin: true, ws: true },
    },
    hmr: { clientPort: 5173 },
  },
  build: {
    outDir: '../../static',
    emptyOutDir: true,
  },
})
