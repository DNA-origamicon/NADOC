import { test, expect } from '@playwright/test'
import { readFile } from 'node:fs/promises'
import { randomUUID } from 'node:crypto'
import { loadScaffoldedPart } from './helpers/scene_harness.js'

test('Run 10 recovery displays saved coordinates without changing cluster membership', async ({ page }) => {
  test.skip(!process.env.NADOC_RECOVERY_FIXTURE, 'Local saved simulation fixture')
  test.setTimeout(240_000)
  const doc = 'e2e-voltron-recovery'
  await loadScaffoldedPart(page, { doc, name: 'VoltronCoreArmV2-recovery' })
  const design = JSON.parse(await readFile(process.env.NADOC_RECOVERY_FIXTURE, 'utf8'))
  design.id = randomUUID()
  design.metadata = { ...design.metadata, name: '__e2e__VoltronCoreArmV2-recovery', identity_last_known_path: null }
  await page.evaluate(async content => {
    await window.__nadocTest.setRepresentation('beads')
    await (await import('/src/api/client.js')).importDesign(content)
  }, JSON.stringify(design))
  await page.evaluate(async () => (await import('/src/api/client.js')).saveDesignToWorkspace('__e2e__VoltronCoreArmV2-recovery.nadoc'))
  await page.goto('/recover-voltron.html?doc=' + doc + '&open=__e2e__VoltronCoreArmV2-recovery.nadoc')
  await expect(page.locator('body')).toHaveAttribute('data-restored', 'true', { timeout: 180_000 })
  const result = await page.evaluate(async () => {
    const w = document.querySelector('iframe').contentWindow, t = w.__nadocTest
    const response = await w.fetch('/api/oxdna/jobs/b53b610666ff/display?align=false')
    const payload = await response.json()
    const key = n => `${n.helix_id}:${n.bp_index}:${n.direction}:${n.copy ?? 0}`
    const saved = new Map(payload.positions.map(n => [key(n), n.backbone_position]))
    let count = 0, maxError = 0
    for (const e of t.getDesignRenderer().getBackboneEntries()) {
      const p = saved.get(key({ ...e.nuc, copy: e._copy ?? 0 }))
      if (!p) continue
      count++
      maxError = Math.max(maxError, Math.hypot(...p.map((v,i) => v - e.pos.getComponent(i))))
    }
    return { count, maxError, clusters: t.store.getState().currentDesign.cluster_transforms }
  })
  expect(result.count).toBeGreaterThan(10000)
  expect(result.maxError).toBeLessThan(.001)
  expect(result.clusters.map(c => c.domain_ids)).toEqual(design.cluster_transforms.map(c => c.domain_ids))
  await page.screenshot({ path: '/tmp/voltron-run10-restored.png' })
})
