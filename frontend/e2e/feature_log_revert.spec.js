/**
 * Playwright test: snapshot-bearing feature log entries for auto-operations.
 *
 * Covers the new POST /design/features/{index}/revert endpoint and the
 * persistence of SnapshotLogEntry through the .nadoc save/load round-trip
 * (which simulates a browser refresh).
 */

import { test, expect } from '@playwright/test'
import * as path from 'path'
import * as os from 'os'

const API = 'http://localhost:8000/api'

/** Compact strand topology summary, ordering-invariant. */
function strandSig(design) {
  return design.strands
    .map(s => `${s.id}|${s.strand_type}|` +
      s.domains.map(d => `${d.helix_id}:${d.start_bp}-${d.end_bp}:${d.direction}`).join(','))
    .sort()
    .join('\n')
}

test.describe('Feature log: snapshot entries + revert', () => {

  test('autobreak writes a snapshot entry, revert restores pre-state', async ({ page }) => {
    const nadocPath = path.resolve(
      import.meta.dirname ?? __dirname,
      '../../Examples/hingeV4.nadoc',
    )
    const loadRes = await page.request.post(`${API}/design/load`, { data: { path: nadocPath } })
    expect(loadRes.ok()).toBeTruthy()
    const designBefore = (await loadRes.json()).design
    const sigBefore = strandSig(designBefore)
    const logLenBefore = designBefore.feature_log.length

    const breakRes = await page.request.post(`${API}/design/auto-break`)
    expect(breakRes.ok()).toBeTruthy()
    const designAfter = (await breakRes.json()).design

    expect(strandSig(designAfter)).not.toBe(sigBefore)
    expect(designAfter.feature_log.length).toBe(logLenBefore + 1)
    const snap = designAfter.feature_log[designAfter.feature_log.length - 1]
    expect(snap.feature_type).toBe('snapshot')
    expect(snap.op_kind).toBe('auto-break')
    expect(snap.snapshot_size_bytes).toBeGreaterThan(0)
    expect(snap.evicted).toBe(false)

    const snapIdx = designAfter.feature_log.length - 1
    const revertRes = await page.request.post(`${API}/design/features/${snapIdx}/revert`)
    expect(revertRes.ok()).toBeTruthy()
    const designReverted = (await revertRes.json()).design

    expect(strandSig(designReverted)).toBe(sigBefore)
    expect(designReverted.feature_log.length).toBe(logLenBefore)
  })

  test('snapshot survives save/load round-trip (simulated browser refresh)', async ({ page }) => {
    const nadocPath = path.resolve(
      import.meta.dirname ?? __dirname,
      '../../Examples/hingeV4.nadoc',
    )
    await page.request.post(`${API}/design/load`, { data: { path: nadocPath } })
    const designBefore = (await (await page.request.get(`${API}/design`)).json()).design
    const sigBefore = strandSig(designBefore)

    await page.request.post(`${API}/design/auto-break`)

    // Simulate browser refresh: save to a temp file, load it back.
    const tmpPath = path.join(os.tmpdir(), `feature-log-revert-${Date.now()}.nadoc`)
    const saveRes = await page.request.post(`${API}/design/save`, { data: { path: tmpPath } })
    expect(saveRes.ok()).toBeTruthy()

    const reloadRes = await page.request.post(`${API}/design/load`, { data: { path: tmpPath } })
    expect(reloadRes.ok()).toBeTruthy()
    const designReloaded = (await reloadRes.json()).design

    const snapIdx = designReloaded.feature_log.findIndex(e => e.feature_type === 'snapshot')
    expect(snapIdx).toBeGreaterThanOrEqual(0)
    const snap = designReloaded.feature_log[snapIdx]
    expect(snap.op_kind).toBe('auto-break')
    expect(snap.design_snapshot_gz_b64).not.toBe('')

    const revertRes = await page.request.post(`${API}/design/features/${snapIdx}/revert`)
    expect(revertRes.ok()).toBeTruthy()
    const designReverted = (await revertRes.json()).design
    expect(strandSig(designReverted)).toBe(sigBefore)
  })
})
