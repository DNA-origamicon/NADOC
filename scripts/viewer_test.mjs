#!/usr/bin/env node
// Local controller. No browser installation, debugger port, or editor mutations.
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve, dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { setTimeout as delay } from 'node:timers/promises'
import { bridgeCredentialsPath, BRIDGE_PATH } from '../frontend/viewer_test_server.js'
import { compareViewerMetrics } from '../frontend/src/perf/viewer_metrics.js'

const args = process.argv.slice(2)
const action = args.shift()
const flags = {}
for (let index = 0; index < args.length; index += 2) {
  if (!args[index].startsWith('--') || !args[index + 1]) throw new Error('Use --option value')
  flags[args[index].slice(2)] = args[index + 1]
}
const root = resolve(flags.root ?? join(dirname(fileURLToPath(import.meta.url)), '../frontend'))
const port = Number(flags.port ?? 5173)
const median = values => { const sorted = [...values].sort((a, b) => a - b); const n = sorted.length; return n % 2 ? sorted[(n - 1) / 2] : (sorted[n / 2 - 1] + sorted[n / 2]) / 2 }
try {
  if (action === 'compare') {
    const a = JSON.parse(await readFile(flags.a, 'utf8')), b = JSON.parse(await readFile(flags.b, 'utf8'))
    const left = a.runs.filter(run => !run.warmup).map(run => run.result.metrics)
    const right = b.runs.filter(run => !run.warmup).map(run => run.result.metrics)
    if (!left.length || !right.length) throw new Error('Both files need measured captures')
    const reasons = [...new Set([...left, ...right].flatMap(record => compareViewerMetrics(left[0], record).reasons))]
    if (left.length < 5 || right.length < 5) reasons.push('At least five measured captures per build required')
    const hashes = records => new Set(records.map(record => record.build?.frontend_sha256))
    const ah = hashes(left), bh = hashes(right)
    if (ah.size !== 1 || bh.size !== 1 || !left[0].build?.frontend_sha256 || !right[0].build?.frontend_sha256) reasons.push('Each side must have one known frontend build')
    if ([...ah].some(hash => bh.has(hash))) reasons.push('A and B report the same frontend build; this is repeatability evidence')
    const p95a = median(left.map(record => record.frame_intervals.p95_ms)), p95b = median(right.map(record => record.frame_intervals.p95_ms))
    console.log(JSON.stringify({ comparable: reasons.length === 0, reasons, measured_runs: [left.length, right.length], median_p95_ms: [p95a, p95b], p95_delta_percent: reasons.length ? null : 100 * (p95b / p95a - 1),
      scope: 'Frame-interval comparison only; visual and simulation-content acceptance remain separate' }, null, 2))
    process.exitCode = reasons.length ? 2 : 0
  } else {
    if (!['sessions', 'inspect', 'snapshot', 'capture', 'open', 'visit'].includes(action)) throw new Error('Usage: node scripts/viewer_test.mjs sessions|inspect|snapshot|capture|open|visit|compare [--url URL] [--port 5173] [--session ID] [--file WORKSPACE_PATH] [--output NEW_DIRECTORY] [--runs 5] [--warmups 1] [--seconds 20]; compare uses --a FILE --b FILE')
    const credentials = JSON.parse(await readFile(bridgeCredentialsPath(root, port), 'utf8'))
    async function request(path, value) {
      const response = await fetch(`http://127.0.0.1:${port}${BRIDGE_PATH}${path}`, { method: value ? 'POST' : 'GET',
        headers: { Authorization: `Bearer ${credentials.token}`, ...(value ? { 'Content-Type': 'application/json' } : {}) }, body: value ? JSON.stringify(value) : undefined })
      const result = await response.json()
      if (!response.ok) throw new Error(result.error ?? response.statusText)
      return result
    }
    const sessions = await request('/sessions')
    if (action === 'sessions') console.log(JSON.stringify(sessions, null, 2))
    else {
      const session = flags.session ?? (sessions.length === 1 ? sessions[0].id : null)
      if (!session) throw new Error('Select one connected viewer with --session ID (see sessions)')
      async function command(kind, options = {}) {
        const { id } = await request('/commands', { session, action: kind, options })
        const deadline = Date.now() + (kind === 'open' ? 245000 : (options.durationMs ?? 0) + 20000)
        while (Date.now() < deadline) {
          const job = await request(`/jobs/${id}`)
          if (job.status === 'error') throw new Error(job.error)
          if (job.status === 'completed') return job
          await delay(500)
        }
        throw new Error('Controller timed out waiting for browser')
      }
      if (['inspect', 'open', 'visit'].includes(action)) console.log(JSON.stringify((await command(action, action === 'open' ? { path: flags.file } : action === 'visit' ? { url: flags.url } : {})).result, null, 2))
      else {
        if (!flags.output) throw new Error('Use --output NEW_DIRECTORY to retain review evidence')
        const output = resolve(flags.output)
        await mkdir(output, { recursive: false }) // refuse overwriting earlier evidence
        const evidence = { schema: 1, session, created_at: new Date().toISOString(), runs: [] }
        const save = () => writeFile(join(output, 'captures.json'), JSON.stringify(evidence, null, 2) + '\n')
        try {
          if (flags.file) { evidence.loaded = (await command('open', { path: flags.file })).result; await delay(3000) }
          evidence.before = (await command('inspect')).result
          const saveSnapshot = async name => {
            const job = await command('snapshot')
            const { png, ...metadata } = job.result
            await writeFile(join(output, `${name}.png`), Buffer.from(png.split(',')[1], 'base64'))
            return { ...metadata, file: `${name}.png` }
          }
          evidence.snapshot_before = await saveSnapshot('before')
          if (action === 'capture') {
            const runs = Number(flags.runs ?? 5), warmups = Number(flags.warmups ?? 1), seconds = Number(flags.seconds ?? 20)
            if (!Number.isInteger(runs) || runs < 1 || runs > 20 || !Number.isInteger(warmups) || warmups < 0 || warmups > 3 || !Number.isFinite(seconds) || seconds < 1 || seconds > 60) throw new Error('Use 1–20 measured runs, 0–3 warmups, and 1–60 seconds')
            for (let index = 0; index < runs + warmups; index++) {
              const job = await command('capture', { durationMs: seconds * 1000, variant: evidence.before.default_variant })
              evidence.runs.push({ ...job, warmup: index < warmups })
              await save()
              const metrics = job.result.metrics
              console.log(JSON.stringify({ run: index + 1, warmup: index < warmups, valid: metrics.valid, fps: metrics.frame_intervals.mean_fps, p95_ms: metrics.frame_intervals.p95_ms, gpu: metrics.environment.gpu }))
              if (!metrics.valid) throw new Error(metrics.invalid_reason)
              if (job.result.after.controls_enabled !== evidence.before.controls_enabled) throw new Error('Camera controls were not restored')
              await delay(1500)
            }
          }
          evidence.snapshot_after = await saveSnapshot('after')
          evidence.after = (await command('inspect')).result
          console.log(`Evidence: ${output}`)
        } catch (error) { evidence.error = error.message; throw error }
        finally { await save() }
      }
    }
  }
} catch (error) { console.error(error.message); process.exitCode = 1 }
