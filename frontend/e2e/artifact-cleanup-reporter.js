/** Failure-safe final Playwright reporter: test artifacts must not survive a run. */
import { rm } from 'node:fs/promises'
import { rmSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const FRONTEND = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const OUTPUTS = [path.join(FRONTEND, 'test-results'), path.join(FRONTEND, 'playwright-report')]

// Playwright writes test-results/.last-run.json after reporter.onEnd. The exit
// hook is therefore the final enforcement point, after Playwright's own write.
process.once('exit', () => {
  for (const output of OUTPUTS) rmSync(output, { recursive: true, force: true })
})

export default class ArtifactCleanupReporter {
  async onEnd() {
    await Promise.all(OUTPUTS.map(output => rm(output, { recursive: true, force: true })))
  }
}
