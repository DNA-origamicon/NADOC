// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { readFile } from 'node:fs/promises'

describe('Playwright workspace cleanup policy', () => {
  it('documents the mandatory prefix and failure-safe global teardown', async () => {
    const source = await readFile(new URL('../../e2e/global-teardown.js', import.meta.url), 'utf8')
    expect(source).toContain("const E2E_PREFIX = '__e2e__'")
    expect(source).toContain("f.endsWith('.nadoc') || f.endsWith('.nass')")
    expect(source).toContain('Promise.all')
    expect(source).toContain("path.join(WORKSPACE, 'playwright_tests')")
    expect(source).toContain('scratchVictims')
  })

  it('keeps the nanoparticle test inside the cleanup namespace', async () => {
    const source = await readFile(new URL('../../e2e/nanoparticle.spec.js', import.meta.url), 'utf8')
    expect(source).toContain("'__e2e__nanoparticle'")
    expect(source).not.toContain("'nanoparticle-e2e'")
  })

  it('removes Playwright screenshots, traces, and run metadata after every run', async () => {
    const config = await readFile(new URL('../../playwright.config.js', import.meta.url), 'utf8')
    const reporter = await readFile(new URL('../../e2e/artifact-cleanup-reporter.js', import.meta.url), 'utf8')
    expect(config).toContain("./e2e/artifact-cleanup-reporter.js")
    expect(config).not.toContain("['html'")
    expect(reporter).toContain("path.join(FRONTEND, 'test-results')")
    expect(reporter).toContain("path.join(FRONTEND, 'playwright-report')")
    expect(reporter).toContain("process.once('exit'")
    expect(reporter).toContain('rmSync(output')
  })
})
