import {installAuditBrowserTrace, saveAuditBrowserTrace, importAuditDesign} from './helpers/vr_audit_design.js'
import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import fs from 'node:fs'
import path from 'node:path'
test.skip(!process.env.NADOC_PHYSICAL_VR_TEST, 'physical runtime opt-in')
const base = process.env.NADOC_E2E_API_BASE
let pid
test.afterEach(async ({ request }) => {
  const status = await (await request.get(`${base}/api/vr/status`)).json()
  if (pid && status.pid === pid) await request.post(`${base}/api/vr/stop`)
})
test('selected end arrow trigger pull commits once and desktop Undo restores it', async ({ page, request }, info) => {
  test.setTimeout(240000)
  if (process.env.NADOC_VR_FRAME_AUDIT === '1') { const cdp = await page.context().newCDPSession(page); await cdp.send('Emulation.setFocusEmulationEnabled', { enabled: false }) }
  await page.goto('/?doc=__e2e__end-resize&scrywrite=transactions')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__End Resize')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  const auditImported = await importAuditDesign(page, info)
  const before = await page.evaluate(async auditImported => {
    const api = await import('/src/api/client.js')
    const { store } = await import('/src/state/store.js')
    if (!auditImported) await api.createBundle({ cells: [[0,0], [1,0]], lengthBp: 42, plane: 'XY', name: '__e2e__Resize' })
    const state = store.getState()
    const ends = state.currentGeometry.filter(n => {
      if (!n.is_three_prime) return false
      if (!auditImported) return n.bp_index === 41
      // A routed imported part contains many ends blocked by the next staple.
      // Choose real free termini for +12/-6; never change the source topology
      // or bypass the production collision limits to make the probe pass.
      const strand = state.currentDesign.strands.find(s => s.id === n.strand_id)
      const domain = strand?.domains.at(-1)
      if (!domain || Math.abs(domain.end_bp - domain.start_bp) < 6) return false
      const sign = n.direction === 'FORWARD' ? 1 : -1
      return !state.currentDesign.strands.some(s => s.id !== n.strand_id && s.domains.some(d => {
        if (d.helix_id !== n.helix_id || d.direction !== n.direction) return false
        const lo = Math.min(d.start_bp, d.end_bp), hi = Math.max(d.start_bp, d.end_bp)
        return sign > 0 ? lo > n.bp_index && lo <= n.bp_index + 12
          : hi < n.bp_index && hi >= n.bp_index - 12
      }))
    }).slice(0, 2)
    if (ends.length !== 2) throw new Error('Resize fixture needs two terminal ends')
    const refs = ends.map(nuc => ({ kind: 'end', key: `${nuc.helix_id}:${nuc.bp_index}:${nuc.direction}` }))
    store.setState({ selection: { context: 'design', level: 'end', items: refs, primary: refs.at(-1) } })
    return { design: state.currentDesign, strandIds: ends.map(nuc => nuc.strand_id) }
  }, auditImported)
  await page.evaluate(() => document.querySelector('#menu-help-view-vr').click())
  let status
  await expect.poll(async () => {
    status = await (await request.get(`${base}/api/vr/status`)).json()
    if (status.pid) pid = status.pid
    return status.running && !!status.scrywrite_socket
  }, { timeout: 30000 }).toBe(true)
  execFileSync('uv', ['run', 'python', '-m', 'tools.vr_workflows.end_resize_probe', status.scrywrite_socket, info.outputPath('physical')], {
    cwd: path.resolve(process.cwd(), '..'), env: process.env, timeout: 160000, stdio: 'inherit',
  })
  const report = JSON.parse(fs.readFileSync(info.outputPath('physical/result.json')))
  const read = () => page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign)
  const after = await read()
  if (after.feature_log.at(-1).id === before.design.feature_log.at(-1)?.id) {
    expect(after.feature_log.at(-1).children.length).toBe(before.design.feature_log.at(-1).children.length + 1)
  } else {
    expect(after.feature_log.length).toBe(before.design.feature_log.length + 1)
  }
  const length = s => s.domains.reduce((sum, d) => sum + Math.abs(d.end_bp - d.start_bp) + 1, 0)
  for (const id of before.strandIds) {
    expect(length(after.strands.find(s => s.id === id)) - length(before.design.strands.find(s => s.id === id))).toBe(report.delta)
  }
  expect(await page.evaluate(() => window.__nadocTest.getCanonicalSelection().items.length)).toBe(2)
  await page.screenshot({ path: info.outputPath('desktop-resized.png') })
  execFileSync('uv', ['run', 'python', '-m', 'tools.vr_workflows.end_resize_probe', status.scrywrite_socket, info.outputPath('trim'), '-6', '0'], {
    cwd: path.resolve(process.cwd(), '..'), env: process.env, timeout: 160000, stdio: 'inherit',
  })
  const trimReport = JSON.parse(fs.readFileSync(info.outputPath('trim/result.json')))
  const trimmed = await read()
  expect(trimReport.delta).toBeLessThan(0)
  // Consecutive desktop resize edits share a Fine Routing parent; each
  // release adds one child and remains independently undoable.
  expect(trimmed.feature_log.length).toBe(after.feature_log.length)
  expect(trimmed.feature_log.at(-1).children.length).toBe(after.feature_log.at(-1).children.length + 1)
  for (const id of before.strandIds) {
    expect(length(trimmed.strands.find(s => s.id === id)) - length(after.strands.find(s => s.id === id))).toBe(trimReport.delta)
  }
  expect(await page.evaluate(() => window.__nadocTest.getCanonicalSelection().items.length)).toBe(2)
  await page.evaluate(async () => (await import('/src/api/client.js')).undo())
  expect((await read()).strands).toEqual(after.strands)
  await page.evaluate(async () => (await import('/src/api/client.js')).undo())
  expect((await read()).strands).toEqual(before.design.strands)
})

// Optional read-only resource-condition evidence for full-size VR audits.
test.beforeEach(async ({page}) => { await installAuditBrowserTrace(page) })
test.afterEach(async ({page}, info) => { await saveAuditBrowserTrace(page, info) })
