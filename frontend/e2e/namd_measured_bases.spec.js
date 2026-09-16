/** Read-only real-job regression. No saves/new jobs. Session cache is disabled by
 * config; screenshots/traces use testInfo.outputPath + cleanup reporter. */
import { test, expect } from '@playwright/test'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
const JOB = '594917c0d119'
test('P5 measured bases survive Full / ballstick switching', async ({ page }, info) => {
  test.skip(!existsSync(fileURLToPath(new URL(`../../workspace/md_jobs/${JOB}/job.json`, import.meta.url))),
    'preserved 24hb P5 job is not available in this checkout')
  test.setTimeout(240_000)
  const errors = []
  page.on('pageerror', e => errors.push(e.message))
  page.on('dialog', d => d.accept())
  await page.goto('/?doc=__e2e__namd_measured_bases')
  await page.waitForFunction(() => !!window.__nadocTest)
  const welcome = page.locator('#welcome-screen')
  await welcome.locator('.lib-row-name', { hasText: /^24hb_0xT$/ }).first().click()
  await expect(welcome).toHaveClass(/hidden/, { timeout: 60_000 })
  await page.waitForFunction(() => window.__nadocTest.viewerDiagnostic().slabEntries > 6000)
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click()
  await page.locator('.engine-selector-btn[data-engine="namd"]').click()
  const row = page.locator(`#md-jobs-list [data-job-id="${JOB}"]`)
  await row.waitFor({ state:'attached', timeout:30_000 })
  await row.evaluate(el => el.click())
  await expect(page.locator('#md-jobs-traj-toggle')).toBeEnabled({ timeout:30_000 })
  await page.locator('#md-jobs-traj-interval').evaluate(el => {
    el.value='6031'; el.dispatchEvent(new Event('change', {bubbles:true}))
  })
  const pending = page.waitForResponse(r => r.url().includes(`/md/jobs/${JOB}/trajectory-bin`), {timeout:90_000})
  await page.locator('#md-jobs-traj-toggle').check({force:true})
  const response = await pending
  expect(response.ok()).toBeTruthy()
  const payload = await response.body()
  expect(payload.readUInt32LE(4)).toBe(2)
  const header = JSON.parse(payload.subarray(20,20+payload.readUInt32LE(16)))
  expect(header.frame_format).toBe('namd-measured-bases')
  await expect.poll(() => page.locator('#md-jobs-traj-slider').getAttribute('max'), {timeout:90_000}).toBe('1')
  await page.locator('#menu-view-coloring-base').evaluate(el => el.click())
  await page.locator('#md-jobs-traj-slider').evaluate(el => {
    el.value='1'; el.dispatchEvent(new Event('input', {bubbles:true}))
  })
  const offset = (20 + payload.readUInt32LE(16) + 3) & ~3
  const floats = Array.from({length:header.keys.length * 12}, (_, i) =>
    payload.readFloatLE(offset + (header.keys.length * 12 + i) * 4))
  await page.evaluate(({keys, floats}) => {
    window.__p5Expected = keys.map((k,i) => [k.join(':'), floats.slice(i*12+9,i*12+12)])
  }, {keys:header.keys, floats})
  const slabError = () => page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const expected = new Map(window.__p5Expected)
    const matrix = new THREE.Matrix4(), position = new THREE.Vector3()
    let max = 0, count = 0
    for (const slab of window.__nadocTest.getDesignRenderer().getSlabEntries()) {
      const n = slab.nuc, center = expected.get(`${n.helix_id}:${n.bp_index}:${n.direction}`)
      if (!center) continue
      slab.instMesh.getMatrixAt(slab.id, matrix); position.setFromMatrixPosition(matrix)
      max = Math.max(max, position.distanceTo(new THREE.Vector3(...center))); count++
    }
    return count === 6720 ? max : Infinity
  })
  await expect.poll(slabError, {timeout:30_000}).toBeLessThan(0.0001)
  await page.screenshot({path:info.outputPath('full.png')})
  await page.evaluate(() => window.__nadocTest.setRepresentation('ballstick'))
  await expect.poll(() => page.evaluate(() => {
    let n=0; window.__nadocTest.getAtomisticRenderer().visitAtoms(() => n++); return n
  }), {timeout:120_000}).toBeGreaterThan(100_000)
  await expect.poll(() => page.evaluate(() => window.__nadocTest.isCGVisible()), {timeout:30_000}).toBe(false)
  const atomCheck = await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const {store} = await import('/src/state/store.js')
    const {buildNucLetterMap, BASE_COLORS} = await import('/src/scene/helix_renderer/palette.js')
    const geometry = window.__nadocTest.getDesignRenderer().getBackboneEntries().map(e => e.nuc)
    const letters = new Map([...buildNucLetterMap(store.getState().currentDesign, geometry)].map(([n,ch]) =>
      [`${n.helix_id}:${n.bp_index}:${n.direction}`, ch]))
    const meshes = new Map()
    window.__nadocTest.scene.traverse(o => {
      if (o.name === 'atomSpheres') meshes.set(o.userData.element, o)
    })
    const rows = new Map(), sums = new Map(), color = new THREE.Color()
    const rings = new Set(['N1','C2','N3','C4','C5','C6','N7','C8','N9'])
    let checked=0, wrong=0
    window.__nadocTest.getAtomisticRenderer().visitAtoms((atom, pos) => {
      const row = rows.get(atom.element) ?? 0; rows.set(atom.element, row+1)
      const key = `${atom.helix_id}:${atom.bp_index}:${atom.direction}`
      const ch = letters.get(key)
      if (ch) {
        checked++; meshes.get(atom.element).getColorAt(row, color)
        if (color.getHex() !== BASE_COLORS[ch]) wrong++
      }
      if (rings.has(atom.name)) {
        let sum = sums.get(key)
        if (!sum) sums.set(key, sum={p:new THREE.Vector3(), n:0})
        sum.p.add(pos); sum.n++
      }
    })
    let max=0, bases=0
    for (const [key, center] of window.__p5Expected) {
      const sum=sums.get(key); if (!sum) continue
      max=Math.max(max, sum.p.divideScalar(sum.n).distanceTo(new THREE.Vector3(...center))); bases++
    }
    return {checked,wrong,bases,max}
  })
  console.log('P5 rendered agreement:', atomCheck)
  expect(atomCheck.checked).toBeGreaterThan(100_000)
  expect(atomCheck.wrong).toBe(0)
  expect(atomCheck.bases).toBe(6720)
  expect(atomCheck.max).toBeLessThan(0.0001)
  await page.screenshot({path:info.outputPath('ballstick.png')})
  await page.evaluate(() => window.__nadocTest.setRepresentation('full'))
  await expect.poll(() => page.evaluate(() => window.__nadocTest.isCGVisible())).toBe(true)
  await expect(page.locator('#md-jobs-traj-slider')).toHaveValue('1')
  await expect.poll(slabError).toBeLessThan(0.0001)
  expect(errors).toEqual([])
})
