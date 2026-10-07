// Use the same durable incident journal as pytest and runtime integrity failures.
import { spawn } from 'node:child_process'
import { fileURLToPath } from 'node:url'
import path from 'node:path'

const root = fileURLToPath(new URL('..', import.meta.url))
const guardedNames = new Set(['helix_renderer.slab_coordinates.test.js', 'new_positioning.test.js',
  'native_placement.failure_ui.test.js'])
const guarded = (filename = '', name = '') => filename.includes('.native_placement.test.')
  || guardedNames.has(path.basename(filename)) || name.includes('[native-placement]')
const shellQuote = value => "'" + String(value).replaceAll("'", "'\\''") + "'"

async function journal(command, input = null) {
  const {stdout, stderr, code} = await new Promise((resolve, reject) => {
    const child = spawn('python3', ['-m', 'tools.native_placement_audit', command], {
      cwd: root, env: process.env, stdio: ['pipe', 'pipe', 'pipe'],
    })
    let stdout = '', stderr = ''
    child.stdout.on('data', data => { stdout += data })
    child.stderr.on('data', data => { stderr += data })
    child.on('error', reject)
    child.on('close', code => resolve({stdout, stderr, code}))
    child.stdin.end(input == null ? undefined : JSON.stringify(input))
  })
  if (code !== 0) throw new Error(stderr || stdout || 'Placement review gate failed closed')
  if (input) console.error(stdout.trim())
}

export default class NativePlacementReporter {
  selected = false
  failedModules = new Set()

  async onTestCaseResult(test) {
    const filename = test.module.moduleId
    if (!guarded(filename, test.fullName)) return
    this.selected = true
    const result = test.result()
    if (result.state !== 'failed') return
    this.failedModules.add(filename)
    const errors = result.errors ?? []
    await journal('record', {
      test_id: `${path.relative(root, filename)}::${test.fullName}`, phase: 'test', runner: 'vitest',
      exception: errors.map(error => error.stack || error.message || String(error)).join('\n\n') || 'Placement test failed',
      evidence: errors.map(error => ({ expected: error.expected, actual: error.actual,
        details: error.details, diff: error.diff })),
      reproduce_command: `cd frontend && npx vitest run ${shellQuote(path.relative(path.join(root, 'frontend'), filename))}`,
      source_files: [filename],
    })
  }

  async onTestRunEnd(modules) {
    for (const module of modules) {
      if (!guarded(module.moduleId)) continue
      this.selected = true
      const errors = module.errors()
      if (errors.length && !this.failedModules.has(module.moduleId)) {
        await journal('record', {test_id: path.relative(root, module.moduleId), phase: 'module', runner: 'vitest',
          exception: errors.map(e => e.stack || e.message || String(e)).join('\n\n'),
          reproduce_command: `cd frontend && npx vitest run ${shellQuote(module.moduleId)}`,
          source_files: [module.moduleId]})
      }
    }
    if (this.selected) await journal('check')
  }
}
