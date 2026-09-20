#!/usr/bin/env node
/** Paired production benchmark in one real browser. Servers are started separately;
 * never edits source, switches git branches, or launches simulation work. */
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import { resolve, join } from 'node:path'
import { setTimeout as delay } from 'node:timers/promises'
import { bridgeCredentialsPath, BRIDGE_PATH } from '../frontend/viewer_test_server.js'
import { compareViewerMetrics } from '../frontend/src/perf/viewer_metrics.js'

const flags = Object.fromEntries(process.argv.slice(2).reduce((rows, value, index, args) => index % 2 ? rows : [...rows, [value.replace(/^--/, ''), args[index + 1]]], []))
const output = resolve(flags.output ?? 'docs/audits/viewer_ab_production_20260920')
const fixture = flags.file ?? 'VoltronCoreArmV2.nadoc'
const configs = {
  editor: { root: resolve('frontend'), port: 5173 },
  A: { root: resolve('/home/joshua/NADOC-viewer-baseline-bridge/frontend'), port: 5180 },
  B: { root: resolve('frontend'), port: 5181 },
}
async function connect(config) {
  const { token } = JSON.parse(await readFile(bridgeCredentialsPath(config.root, config.port), 'utf8'))
  const request = async (path, data) => {
    const response = await fetch(`http://127.0.0.1:${config.port}${BRIDGE_PATH}${path}`, { method: data ? 'POST' : 'GET',
      headers: { Authorization: `Bearer ${token}`, ...(data ? { 'Content-Type': 'application/json' } : {}) }, body: data ? JSON.stringify(data) : undefined })
    const body = await response.json()
    if (!response.ok) throw new Error(body.error ?? response.statusText)
    return body
  }
  async function session() {
    for (let attempt = 0; attempt < 120; attempt++) {
      const sessions = await request('/sessions')
      if (sessions.length === 1) return sessions[0].id
      if (sessions.length > 1) throw new Error(`Multiple benchmark windows on ${config.port}; use one browser`)
      await delay(500)
    }
    throw new Error(`No connected browser on ${config.port}`)
  }
  async function command(action, options = {}) {
    const { id } = await request('/commands', { session: await session(), action, options })
    for (let attempt = 0; attempt < (action === 'open' ? 500 : 150); attempt++) {
      const job = await request(`/jobs/${id}`)
      if (job.status === 'completed') return job
      if (job.status === 'error') throw new Error(`${action}: ${job.error}`)
      await delay(500)
    }
    throw new Error(`${action} timed out`)
  }
  return { session, command }
}
await mkdir(output, { recursive: false })
const evidence = { schema: 1, started_at: new Date().toISOString(), fixture, scope: 'One real browser; production builds; scheduled order recorded in visits; fresh page and warmup per visit; file-open times are workflow completion, not cold filesystem or full startup', visits: [] }
const save = () => writeFile(join(output, 'comparison.json'), JSON.stringify(evidence, null, 2) + '\n')
const clients = Object.fromEntries(await Promise.all(Object.entries(configs).map(async ([name, config]) => [name, await connect(config)])))
let current = clients.editor
const original = (await current.command('inspect')).result
evidence.original = original
try {
  // Balanced transitions, five measured runs each. Every visit is a new page,
  // including adjacent equal variants; only one viewer renders at any time.
  const order = (flags.order ?? 'ABB AAB BAAB').replaceAll(' ', '').split('')
  for (let index = 0; index < order.length; index++) {
    const variant = order[index]
    if (!['A', 'B'].includes(variant)) throw new Error('Order must contain only A/B')
    const destination = `http://127.0.0.1:${configs[variant].port}/?viewer-test=1&doc=viewer_ab_${variant.toLowerCase()}`
    const visit = { index, variant, started_at: new Date().toISOString(), runs: [] }
    evidence.visits.push(visit); await save()
    await current.command('visit', { url: destination })
    current = clients[variant]
    await delay(3000); await current.session()
    visit.load = (await current.command('open', { path: fixture })).result
    await delay(5000)
    visit.before = (await current.command('inspect')).result
    if (visit.before.default_variant !== variant) throw new Error('Actual build variant does not match scheduled variant')
    const snapshot = async stage => {
      const result = (await current.command('snapshot')).result
      const { png, ...metadata } = result
      const file = `${String(index + 1).padStart(2, '0')}-${variant}-${stage}.png`
      await writeFile(join(output, file), Buffer.from(png.split(',')[1], 'base64'))
      return { ...metadata, file }
    }
    visit.snapshot_before = await snapshot('before')
    for (const warmup of [true, false]) {
      const job = await current.command('capture', { variant, durationMs: 20000 })
      visit.runs.push({ ...job, warmup }); await save()
      const record = job.result.metrics
      console.log(JSON.stringify({ visit: index + 1, variant, warmup, valid: record.valid, fps: record.frame_intervals.mean_fps, p95: record.frame_intervals.p95_ms, heap: record.sampled_js_heap_peak_bytes, fixture: record.fixture_sha256 }))
      if (!record.valid) throw new Error(record.invalid_reason)
      if (record.build_mode !== 'production') throw new Error('Expected production build')
      const previous = evidence.visits.flatMap(v => v.runs).find(run => !run.warmup)?.result.metrics
      if (previous) {
        const check = compareViewerMetrics(previous, record)
        if (!check.comparable) throw new Error(`Workloads differ: ${check.reasons.join('; ')}`)
      }
      if (job.result.after.controls_enabled !== visit.before.controls_enabled) throw new Error('Controls did not restore')
      await delay(1500)
    }
    visit.snapshot_after = await snapshot('after')
    visit.after = (await current.command('inspect')).result
    await save()
  }
} catch (error) { evidence.error = error.message; console.error(error.message); process.exitCode = 1 }
finally {
  try {
    await current.command('visit', { url: original.url })
    await delay(3000)
    await clients.editor.session()
    await clients.editor.command('open', { path: fixture })
    evidence.editor_restored = true
  } catch (error) { evidence.restore_error = error.message }
  evidence.finished_at = new Date().toISOString(); await save()
}
for (const variant of ['A', 'B']) await writeFile(join(output, `${variant}.json`), JSON.stringify({ runs: evidence.visits.filter(visit => visit.variant === variant).flatMap(visit => visit.runs) }, null, 2) + '\n')
console.log(`Evidence: ${output}`)
