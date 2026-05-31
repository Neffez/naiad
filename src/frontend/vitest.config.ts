/// <reference types="vitest/config" />
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// Vitest runs in a jsdom environment so component tests and browser-API tests
// (localStorage, fetch, window events) work. The React plugin transforms TSX.
// CSS is disabled — the design system lives in plain .css files we don't assert on.
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: false,
  },
})
