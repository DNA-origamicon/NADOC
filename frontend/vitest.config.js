import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  server: { fs: { allow: [fileURLToPath(new URL('..', import.meta.url))] } },
  test: {
    environment: 'jsdom',
    include: ['src/**/*.test.js'],
  },
})
