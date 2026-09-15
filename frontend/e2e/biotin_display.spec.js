import { expect, test } from '@playwright/test'

test('bound biotin survives Full/VDW/Ball & Stick/Stick switching, movement and undo', async ({ page }) => {
  test.setTimeout(180000)
  await page.goto('/')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', '__e2e__biotin_display')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await page.waitForFunction(() => window.__nadocTest?.store.getState().currentDesign?.metadata?.name === '__e2e__biotin_display')
  const created = await page.evaluate(async () => {
    await window.__nadocTest.nanoparticles.create(10)
    const s = window.__nadocTest.store.getState()
    return { count: s.currentDesign?.nanoparticles?.length, error: s.lastError }
  })
  expect(created, JSON.stringify(created)).toMatchObject({ count: 1 })
  const open = () => page.evaluate(async () => {
    const t = window.__nadocTest
    await t.nanoparticles.conjugation.open(t.store.getState().currentDesign.nanoparticles[0].id)
  })
  await open()
  await page.selectOption('#np-conj-scheme', 'streptavidin')
  await page.fill('#strep-count', '1')
  await page.click('#strep-apply')
  await expect(page.locator('#nanoparticle-conjugate-overlay')).toHaveCount(0, { timeout: 60000 })
  await open()
  await page.fill('#strep-dna-count', '1')
  await page.click('#strep-dna-create')
  await expect(page.locator('#strep-dna-create')).toBeDisabled()
  await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.rendered()[0]?.biotin.length)).toBe(1)
  await page.click('#strep-apply')
  await expect(page.locator('#nanoparticle-conjugate-overlay')).toHaveCount(0)
  const marker = () => page.evaluate(() => window.__nadocTest.nanoparticles.rendered()[0].biotin[0])
  const checkConnection = async () => {
    const biotin = await marker()
    const dnaEnd = await page.evaluate(() => {
      const s = window.__nadocTest.store.getState()
      const record = s.currentDesign.nanoparticles[0].biotin_dna[0]
      return s.currentGeometry.filter(n => n.helix_id === record.helix_id && n.direction === 'FORWARD')
        .sort((a, b) => a.bp_index - b.bp_index)[0].backbone_position
    })
    expect(biotin.linker.segments).toHaveLength(2)
    const near = (a, b) => a.forEach((v, i) => expect(v).toBeCloseTo(b[i], 5))
    near(biotin.linker.segments[0].start, biotin.position)
    near(biotin.linker.segments[0].end, biotin.linker.bead)
    near(biotin.linker.segments[1].start, biotin.linker.bead)
    near(biotin.linker.segments[1].end, dnaEnd)
  }
  expect((await marker()).visible).toBe(true)
  await checkConnection()
  const atomResponse = page.waitForResponse(r => r.url().includes('/design/atomistic') && r.request().method() === 'GET')
  await page.evaluate(() => window.__nadocTest.setRepresentation('ballstick'))
  const data = await (await atomResponse).json()
  expect(data.warnings).toEqual([])
  expect(data.atoms.filter(a => a.residue === 'BTE')).toHaveLength(28)
  for (const repr of ['vdw', 'stick', 'ballstick']) {
    await page.evaluate(repr => window.__nadocTest.setRepresentation(repr), repr)
    expect((await marker()).visible).toBe(false)
    const rendered = await page.evaluate(() => {
      const r = window.__nadocTest.getAtomisticRenderer()
      return { mode: r.getMode(), biotin: r.centroidOf(a => a.residue === 'BTE') }
    })
    expect(rendered.mode).toBe(repr)
    expect(rendered.biotin).not.toBeNull()
    const coating = await page.evaluate(() => {
      const t = window.__nadocTest, p = t.store.getState().currentDesign.nanoparticles[0]
      const rendered = t.nanoparticles.rendered()[0]
      const first = p.coating.protein.atoms.find(a => a.element === rendered.coatingAtoms.firstElement)
      return { rendered: rendered.coatingAtoms, traceVisible: rendered.coating.visible,
        expectedAtoms: p.coating.protein.atoms.length * p.coating.poses.length,
        expectedBonds: p.coating.protein.bonds.length * p.coating.poses.length,
        first, pose: p.coating.poses[0].values, particlePose: p.pose.values }
    })
    expect(coating.rendered.visible).toBe(true)
    expect(coating.traceVisible).toBe(false)
    expect(coating.rendered.atomCount).toBe(coating.expectedAtoms)
    expect(coating.rendered.sphereInstances).toBe(repr === 'stick' ? 0 : coating.expectedAtoms)
    expect(coating.rendered.bondInstances).toBe(repr === 'vdw' ? 0 : coating.expectedBonds)
    if (repr !== 'stick') {
      const transform = (m, p) => [0,1,2].map(i => m[4*i]*p[0]+m[4*i+1]*p[1]+m[4*i+2]*p[2]+m[4*i+3])
      const expected = transform(coating.particlePose, transform(coating.pose, [coating.first.x,coating.first.y,coating.first.z]))
      coating.rendered.firstPosition.forEach((x,i) => expect(x).toBeCloseTo(expected[i], 5))
    }
  }
  await page.evaluate(() => window.__nadocTest.setRepresentation('full'))
  expect((await marker()).visible).toBe(true)
  const before = (await marker()).position
  await page.evaluate(async () => {
    const t = window.__nadocTest
    await t.nanoparticles.move(t.store.getState().currentDesign.nanoparticles[0].id, { pivot: [0,0,0], translation: [5,0,0], rotation: [0,0,0,1] })
  })
  const after = (await marker()).position
  expect(after[0] - before[0]).toBeCloseTo(5, 5)
  await checkConnection()
  await page.evaluate(() => document.getElementById('menu-edit-undo').click())
  await expect.poll(async () => (await marker()).position[0]).toBeCloseTo(before[0], 5)
  await checkConnection()
  await page.evaluate(() => document.getElementById('menu-edit-undo').click())
  await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.rendered()[0].biotin.length)).toBe(0)
  await page.evaluate(() => document.getElementById('menu-edit-redo').click())
  await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.rendered()[0].biotin.length)).toBe(1)
})
