import { test as base, expect } from '@playwright/test'
import { spawn } from 'node:child_process'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontendDir = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
export const repositoryRoot = path.resolve(frontendDir, '..')
const defaultBinary = path.join(
  repositoryRoot,
  'native',
  'vr_viewer',
  'build',
  'nadoc-vr-scrywrite',
)

function execute(binary, script) {
  return new Promise((resolve, reject) => {
    const child = spawn(binary, ['-', '--trace', '-'], {
      cwd: repositoryRoot,
      stdio: ['pipe', 'pipe', 'pipe'],
    })
    let stdout = ''
    let stderr = ''
    child.stdout.setEncoding('utf8')
    child.stderr.setEncoding('utf8')
    child.stdout.on('data', (chunk) => { stdout += chunk })
    child.stderr.on('data', (chunk) => { stderr += chunk })
    child.on('error', reject)
    child.on('close', (code) => {
      let trace
      try {
        trace = JSON.parse(stdout)
      } catch (error) {
        reject(new Error(`ScryWrite emitted an invalid trace: ${error.message}\n${stderr}`))
        return
      }
      resolve({ code, stderr, trace })
    })
    child.stdin.end(script)
  })
}

export const test = base.extend({
  scrywrite: async ({}, use, testInfo) => {
    let runNumber = 0
    await use({
      run: async (script) => {
        runNumber += 1
        const binary = process.env.SCRYWRITE_BIN || defaultBinary
        const result = await execute(binary, script)
        await testInfo.attach(`scrywrite-trace-${runNumber}.json`, {
          body: Buffer.from(`${JSON.stringify(result.trace, null, 2)}\n`),
          contentType: 'application/json',
        })
        if (result.code !== 0) {
          throw new Error(result.stderr.trim() || result.trace.error || 'ScryWrite failed')
        }
        return result.trace
      },
    })
  },
})

export { expect }
