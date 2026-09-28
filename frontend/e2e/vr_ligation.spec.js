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
test('radial Ligate stretches and saves a compatible forced bond from either polarity', async ({ page, request }, info) => {
  test.setTimeout(240000)
  await page.goto('/?doc=__e2e__ligation&scrywrite=transactions')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__VR Ligation')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await page.evaluate(async () => (await import('/src/api/client.js')).createBundle({
    cells: [[0,0]], lengthBp: 42, plane: 'XY', name: '__e2e__Ligation',
  }))
  const read = () => page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign)
  const before = await read()
  await page.evaluate(() => document.querySelector('#menu-help-view-vr').click())
  let status
  await expect.poll(async () => {
    status = await (await request.get(`${base}/api/vr/status`)).json()
    if (status.pid) pid = status.pid
    return status.running && !!status.scrywrite_socket
  }, { timeout: 30000 }).toBe(true)
  for (const role of [3, 5]) {
    execFileSync('uv', ['run', 'python', '-m', 'tools.vr_workflows.ligation_probe', status.scrywrite_socket,
      info.outputPath(`from-${role}`), String(role)], {
      cwd: path.resolve(process.cwd(), '..'), env: process.env, timeout: 160000, stdio: 'inherit',
    })
    const result = JSON.parse(fs.readFileSync(info.outputPath(`from-${role}/result.json`)))
    const after = await read()
    expect(after.forced_ligations.length).toBe((before.forced_ligations?.length ?? 0) + 1)
    expect(after.strands.length).toBe(before.strands.length - 1)
    const bond = after.forced_ligations.at(-1)
    expect(bond.is_periodic_seam).toBe(false)
    const original = before.strands.find(s => s.id === result.three_strand)
    const recipient = before.strands.find(s => s.id === result.five_strand)
    expect(bond.three_prime_bp).toBe(original.domains.at(-1).end_bp)
    expect(bond.five_prime_bp).toBe(recipient.domains[0].start_bp)
    expect(after.feature_log.at(-1).children.filter(c => c.op_subtype === 'forced-ligation-create')).toHaveLength(1)
    await page.screenshot({ path: info.outputPath(`desktop-from-${role}.png`) })
    await page.evaluate(async () => {
      const api = await import('/src/api/client.js')
      await api.undo()
      const { store } = await import('/src/state/store.js')
      await api.refreshNativeVRScene({ expected_design_id: store.getState().currentDesign.id,
        expected_revision: api.currentRevisionWatermark() })
    })
    const undone = await read()
    expect(undone.strands).toEqual(before.strands)
    expect(undone.forced_ligations).toEqual(before.forced_ligations)
  }
})
