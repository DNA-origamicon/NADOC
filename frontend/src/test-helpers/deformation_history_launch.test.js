// @vitest-environment node
import { describe, expect, it } from 'vitest'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { mkdtemp, readdir, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import path from 'node:path'
import http from 'node:http'
import configuration, { historyGatePlugin } from '../../e2e/deformation_history_vite.js'

const editor = fileURLToPath(new URL('../app/feature_editor.js', import.meta.url))
describe('test-only history gate transform', () => {
  it('enables transforms only for an explicit isolated acceptance run', () => {
    const file = fileURLToPath(new URL('../app/transform_history_editor.js', import.meta.url))
    const source = readFileSync(file, 'utf8')
    expect(historyGatePlugin({ transforms: false }).transform(source, file)).toBeNull()
    expect(historyGatePlugin({ transforms: true }).transform(source, file).code)
      .toContain('export const TRANSFORM_HISTORY_EDITOR_ENABLED = true')
    expect(() => historyGatePlugin({ transforms: true }).transform('', file)).toThrow('Missing unique transform test gate')
    expect(readFileSync(file, 'utf8')).toBe(source)
  })
  it('verifies the production-enabled Bend/Twist gates without transforming them', () => {
    const source = readFileSync(editor, 'utf8')
    const plugin = historyGatePlugin()
    expect(plugin.transform(source, `${editor}.other`)).toBeNull()
    expect(plugin.transform(source, editor)).toBeNull()
    for (const name of ['HISTORY', 'CREATION']) {
      expect(source).toContain(`ISOLATED_DEFORMATION_${name}_ENABLED = true`)
    }
    expect(readFileSync(editor, 'utf8')).toBe(source)
    expect(readFileSync(new URL('../../vite.config.js', import.meta.url), 'utf8')).not.toContain('deformation_history_vite')
  })
  it('refuses drift instead of silently testing the legacy editor', () => {
    expect(() => historyGatePlugin().transform('', editor)).toThrow('Missing unique')
    const disabled = readFileSync(editor, 'utf8').replace('ISOLATED_DEFORMATION_HISTORY_ENABLED = true', 'ISOLATED_DEFORMATION_HISTORY_ENABLED = false')
    expect(() => historyGatePlugin().transform(disabled, editor)).toThrow('Missing unique enabled gate')
  })
  it('requires the production Sweep editor gate and refuses declaration drift', () => {
    const file = fileURLToPath(new URL('../app/sweep_history_editor.js', import.meta.url))
    const source = readFileSync(file, 'utf8'), plugin = historyGatePlugin()
    expect(plugin.transform(source, file + '.other')).toBeNull()
    expect(plugin.transform(source, file)).toBeNull()
    expect(readFileSync(file, 'utf8')).toBe(source)
    expect(source).toContain('SWEEP_HISTORY_EDITOR_ENABLED = true')
    expect(() => plugin.transform(source.replace('SWEEP_HISTORY_EDITOR_ENABLED = true', 'SWEEP_HISTORY_EDITOR_ENABLED = false'), file)).toThrow('Missing unique enabled gate')
    expect(() => plugin.transform('', file)).toThrow('Missing unique')
  })
  it('requires an explicit isolated launch', () => {
    const previous = process.env.NADOC_HISTORY_E2E_ROOT
    delete process.env.NADOC_HISTORY_E2E_ROOT
    try { expect(configuration).toThrow('Use scripts/') }
    finally {
      if (previous !== undefined) process.env.NADOC_HISTORY_E2E_ROOT = previous
    }
  })
  it('uses real no-host responses and refuses explicit hosting without artifacts', async () => {
    const root = await mkdtemp(path.join(tmpdir(), '__e2e__history-share-'))
    const previous = process.env.NADOC_HISTORY_E2E_ROOT
    let server
    try {
      process.env.NADOC_HISTORY_E2E_ROOT = root
      const config = configuration()
      expect(config.plugins.map(plugin => plugin.name)).toEqual(['s03-history-test-gates', 'nadoc-local-prepared-share'])
      let handler
      server = http.createServer((req, res) => handler(req, res, () => { res.writeHead(404); res.end() }))
      config.plugins[1].configureServer({ config: { root }, httpServer: server,
        middlewares: { use: fn => { handler = fn } } })
      await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
      const base = `http://127.0.0.1:${server.address().port}`
      const post = (route, body) => fetch(`${base}/__nadoc_share/${route}`, {
        method: 'POST', headers: { 'X-NADOC-Share': '1', Origin: base }, body: JSON.stringify(body),
      })
      const background = await post('links', { key: 'part:fixture', background: true })
      expect(background.status).toBe(202)
      expect(await background.json()).toEqual({ pending: true })
      const status = await fetch(`${base}/__nadoc_share/status`)
      expect(status.status).toBe(200)
      expect(await status.json()).toMatchObject({ running: false, shares: [] })
      for (const route of ['start', 'links']) {
        const response = await post(route, { key: 'part:fixture' })
        expect(response.status).toBe(503)
        expect(await response.json()).toEqual({ error: 'Sharing host launch disabled in history harness' })
      }
      const unknown = await post('unknown', {})
      expect(unknown.status).toBe(404)
      expect(await readdir(root)).toEqual([])
    } finally {
      if (previous === undefined) delete process.env.NADOC_HISTORY_E2E_ROOT
      else process.env.NADOC_HISTORY_E2E_ROOT = previous
      if (server?.listening) {
        server.closeAllConnections()
        await new Promise(resolve => server.close(resolve))
      }
      await rm(root, { recursive: true, force: true })
    }
  })
})
