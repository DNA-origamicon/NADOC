import { expect, test } from '@playwright/test'
import { copyFile, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import path from 'node:path'

const SOURCE = path.resolve(import.meta.dirname, '../../workspace/NP_test.nadoc')
const SCRATCH_DIR = path.resolve(import.meta.dirname, '../../workspace/playwright_tests')
const FIXTURE = path.join(SCRATCH_DIR, '__e2e__NP_test_conjugation.nadoc')

test.describe('gold nanoparticle thiol conjugation manager', () => {
  test.beforeAll(async () => {
    await mkdir(SCRATCH_DIR, { recursive: true }); await copyFile(SOURCE, FIXTURE)
    const design = JSON.parse(await readFile(FIXTURE, 'utf8'))
    // NP_test is an evolving manual test ground and may already contain a
    // conjugation. Reset nanoparticle-owned topology in this disposable copy so
    // this scenario always starts from the same state.
    const ownedStrands = new Set((design.nanoparticle_conjugations ?? [])
      .flatMap(conjugation => conjugation.surface_strands ?? []).map(item => item.strand_id))
    const ownedHelices = new Set((design.nanoparticle_conjugations ?? [])
      .flatMap(conjugation => conjugation.surface_strands ?? []).map(item => item.helix_id))
    design.strands = (design.strands ?? []).filter(item => !ownedStrands.has(item.id))
    design.helices = (design.helices ?? []).filter(item => !ownedHelices.has(item.id))
    design.nanoparticle_conjugations = []
    const strand = design.strands.find(item => item.domains?.length)
    const domain = strand.domains[0]
    const length = Math.abs(domain.end_bp - domain.start_bp) + 1
    domain.overhang_id = '__e2e__np_overhang'
    strand.sequence = 'A'.repeat(length)
    design.overhangs = [{ id: '__e2e__np_overhang', helix_id: domain.helix_id, strand_id: strand.id, sequence: 'A'.repeat(length), label: 'NP test overhang' }]
    await writeFile(FIXTURE, JSON.stringify(design))
  })
  test.afterAll(async () => { await rm(FIXTURE, { force: true }) })

  test('creates first-class strands, renders linkers, moves, validates, and reloads', async ({ page }) => {
    test.setTimeout(120_000)
    await page.goto('/')
    await page.waitForFunction(() => Boolean(window.__nadocTest?.nanoparticles?.conjugation))
    const loaded = await page.evaluate(path => window.__nadocTest.nanoparticles.conjugation.loadDesign(path), FIXTURE)
    const particleId = loaded.design.nanoparticles[0].id

    await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({ position: [20, 20, 20], target: [0, 11.4, 6.7] }))
    const point = await page.evaluate(id => window.__nadocTest.nanoparticles.screenPosition(id), particleId)
    await page.evaluate(point => document.getElementById('canvas').dispatchEvent(new MouseEvent('contextmenu', {
      bubbles: true, button: 2, clientX: point.x, clientY: point.y,
    })), point)
    await expect(page.getByRole('button', { name: 'Conjugate Manager…' })).toBeVisible()
    await page.getByRole('button', { name: 'Conjugate Manager…' }).click()
    await expect(page.locator('#nanoparticle-conjugate-overlay')).toBeVisible()
    const beforeOrbit = await page.evaluate(() => window.__nadocTest.nanoparticles.conjugation.previewCamera())
    const preview = page.locator('#np-conjugate-preview canvas')
    const previewBox = await preview.boundingBox()
    await page.mouse.move(previewBox.x + previewBox.width * .5, previewBox.y + previewBox.height * .5)
    await page.mouse.down(); await page.mouse.move(previewBox.x + previewBox.width * .7, previewBox.y + previewBox.height * .4, { steps: 6 }); await page.mouse.up()
    await expect.poll(async () => page.evaluate(() => window.__nadocTest.nanoparticles.conjugation.previewCamera())).not.toEqual(beforeOrbit)
    await page.locator('#np-conj-overhangs .ohc-list-row').first().click()
    await expect(page.locator('#np-conj-sequence')).not.toHaveValue('')
    const handleLength = (await page.locator('#np-conj-sequence').inputValue()).length
    await page.click('#np-conj-create-handle')
    await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.conjugation.fullHandleCensus())).toEqual({
      beads: handleLength, slabs: handleLength, connectors: handleLength - 1,
    })
    await page.selectOption('#np-conj-scheme', 'peg_thiol')
    await page.fill('#np-conj-count', '3')
    await page.locator('#np-conj-count').dispatchEvent('input')
    await expect(page.locator('#np-conj-summary')).toContainText('3 strands')
    await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.conjugation.fullHandleCensus())).toEqual({
      beads: handleLength * 3, slabs: handleLength * 3, connectors: (handleLength - 1) * 3,
    })
    await page.click('#np-conj-apply')
    await expect(page.locator('#nanoparticle-conjugate-overlay')).toHaveCount(0)

    const state = await page.evaluate(id => window.__nadocTest.nanoparticles.conjugation.get(id), particleId)
    expect(state.conjugations[0]).toMatchObject({ scheme: 'peg_thiol', requested_count: 3 })
    expect(state.conjugations[0].surface_strands).toHaveLength(3)
    expect(await page.evaluate(() => window.__nadocTest.store.getState().currentDesign.strands.filter(s => s.name?.startsWith('NP-1:S')).length)).toBe(3)
    await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.conjugationRender().connectors)).toBe(3)

    // Exercise the same representation event emitted after atomistic DNA has
    // loaded. Linker atoms are an independent local overlay because gold itself
    // deliberately has no atomistic model.
    await page.evaluate(() => window.dispatchEvent(new CustomEvent('nadoc:representation-change', { detail: { representation: 'ballstick' } })))
    await expect.poll(() => page.evaluate(() => window.__nadocTest.nanoparticles.conjugationRender().linkerAtomsVisible)).toBe(true)
    const atoms = await page.evaluate(() => window.__nadocTest.nanoparticles.conjugationRender().linkerAtoms)
    expect(atoms.filter(a => a.element === 'S')).toHaveLength(3)
    expect(atoms.some(a => a.element === 'O')).toBeTruthy()
    expect(await page.evaluate(() => window.__nadocTest.nanoparticles.conjugationRender().surfaceBonds)).toBe(3)

    const valid = await page.evaluate(id => window.__nadocTest.nanoparticles.conjugation.validate(id), particleId)
    expect(valid).toMatchObject({ valid: true, strand_count: 3 })
    await page.evaluate(path => window.__nadocTest.nanoparticles.conjugation.saveDesign(path), FIXTURE)
    const reloaded = await page.evaluate(path => window.__nadocTest.nanoparticles.conjugation.loadDesign(path), FIXTURE)
    expect(reloaded.design.nanoparticle_conjugations[0].surface_strands).toHaveLength(3)
  })
})
