// @vitest-environment node
import { afterEach, expect, it, vi } from 'vitest'
import path from 'node:path'
import { tmpdir } from 'node:os'
import ordinary from '../../vite.config.js'
import configure from '../../e2e/smoke_vite.js'

afterEach(() => vi.unstubAllEnvs())
it('keeps production plugins and gates while isolating the Vite cache', () => {
  const root = path.join(tmpdir(), '__e2e__smoke-config')
  vi.stubEnv('NADOC_SMOKE_E2E_ROOT', root)
  const config = configure()
  expect(config.plugins).toBe(ordinary.plugins)
  expect(config.server).toBe(ordinary.server)
  expect(config.define).toBe(ordinary.define)
  expect(config.cacheDir).toBe(path.join(root, 'vite-cache'))
  expect(ordinary.cacheDir).toBeUndefined()
})
it.each([undefined, 'relative'])('refuses unqualified scratch %s', root => {
  vi.stubEnv('NADOC_SMOKE_E2E_ROOT', root)
  expect(configure).toThrow('isolated --smoke launcher')
})
