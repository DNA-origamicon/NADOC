import { defineConfig } from 'vitest/config'
import { fileURLToPath } from 'node:url'

export default defineConfig({
  server: { fs: { allow: [fileURLToPath(new URL('..', import.meta.url))] } },
  test: {
    reporters: ['default', './native_placement_reporter.js'],
    environment: 'jsdom',
    // Each jsdom worker has its own V8 heap; CPU count is not a memory budget.
    maxWorkers: 2,
    include: ['src/**/*.test.js'],
  },
})
