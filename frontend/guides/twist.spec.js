import { test, expect } from '@playwright/test'
import { createGuide } from './capture.js'
import { createSquarePart, preparation, openExtrude, selectFootprint, designState, addSeparateCluster, verifySavedExample } from './workflow.js'

const LENGTH = 256
const commands = rows => rows.map(({ design_snapshot_gz_b64, post_state_gz_b64, ...record }) => record)
const marks = design => design.helices.flatMap(h => h.loop_skips ?? [])

async function fitClusters(page) {
  await expect(page.locator('#file-load-progress')).not.toBeVisible({ timeout: 60000 })
  const drag = await page.evaluate(() => {
    const c = window.__nadocTest.viewerDiagnostic().camera
    const d = c.position.map((v, i) => v - c.target[i]), r = Math.hypot(...d)
    const theta = Math.atan2(d[0], d[2]), phi = Math.acos(d[1] / r)
    const targetTheta = (theta < 0 ? -1 : 1) * (Math.PI / 2 - 0.12)
    const scale = document.querySelector('#canvas').getBoundingClientRect().height / (2 * Math.PI)
    return { x: (theta - targetTheta) * scale, y: (phi - (Math.PI / 2 - 0.1)) * scale }
  })
  await page.mouse.move(1100, 600)
  await page.mouse.down({ button: 'right' })
  await page.mouse.move(1100 + drag.x, 600 + drag.y, { steps: 16 })
  await page.mouse.up({ button: 'right' })
  await page.locator('#canvas').press('f')
  await page.mouse.move(1900, 20)
}

async function reopen(page, stage) {
  const before = await designState(page)
  await verifySavedExample(page, before.feature_log.length, 36)
  await page.goto(`/?doc=__e2e__twist-${stage}&open=` + encodeURIComponent('__e2e__twist 3x6 square guide.nadoc') + '&open-type=part')
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await expect.poll(async () => (await designState(page))?.feature_log?.length).toBe(before.feature_log.length)
  expect(commands((await designState(page)).feature_log)).toEqual(commands(before.feature_log))
  await expect(page.locator('#menu-view-detail-full')).toHaveClass(/is-checked/)
  await fitClusters(page)
  await page.mouse.move(1900, 20)
}

async function twist(page, guide, { a, b, degrees, handedness, index }) {
  const entryGuide = index === 1 ? guide : { ...preparation, clickPoint: p => page.mouse.click(p.x, p.y) }
  await page.locator('#menu-item-tools').hover()
  await entryGuide.click(page.locator('#menu-tools-twist'), 'Choose Tools → Twist to open the tool and select a cluster.')
  const first = (await designState(page)).cluster_transforms.find(c => c.helix_ids.length === 18)
  await expect.poll(() => page.evaluate(id => window.__nadocTest.getClusterBeadScreenPositions().some(p => p.id === id && document.elementFromPoint(p.x, p.y)?.id === 'canvas'), first.id)).toBe(true)
  const point = await page.evaluate(id => window.__nadocTest.getClusterBeadScreenPositions().find(p => p.id === id && document.elementFromPoint(p.x, p.y)?.id === 'canvas'), first.id)
  await entryGuide.clickPoint(point, 'Click the original 3×6 bundle to select its cluster. The second cluster provides a straight reference.')
  await expect(page.locator('#def-twist-value')).toBeVisible()
  for (const [id, value] of [['#def-plane-a-bp', a], ['#def-plane-b-bp', b]]) {
    if (await page.locator(id).inputValue() !== String(value)) {
      await page.locator(id).fill(String(value))
      await page.locator(id).press('Tab')
    }
  }
  await page.locator('#def-twist-total-radio').check()
  await page.locator(`#def-twist-${handedness}`).check()
  const signed = handedness === 'rh' ? degrees : -degrees
  const evaluated = page.waitForResponse(r => {
    if (!new URL(r.url()).pathname.endsWith('/deformation-preview/evaluate') || r.request().method() !== 'POST') return false
    const draft = r.request().postDataJSON()?.params
    return draft?.plane_a_bp === a && draft?.plane_b_bp === b && draft.params?.total_degrees === signed
  }, { timeout: 30000 })
  await page.locator('#def-twist-value').fill(String(degrees))
  await page.locator('#def-twist-value').press('Tab')
  expect((await evaluated).ok()).toBe(true)
  await expect(page.locator('#def-apply-btn')).toBeEnabled()
  await guide.pointAt(page.locator('#def-apply-btn'), `Set planes ${a}–${b} bp, Total twist ${degrees}° and ${handedness === 'rh' ? 'Right-handed' : 'Left-handed'}. Inspect the preview, then click Apply.`)
  await page.locator('#def-apply-btn').click({ timeout: 10000 })
  await expect(page.locator('#deform-panel')).not.toBeVisible()
  await expect.poll(async () => (await designState(page)).deformations.length).toBe(index)
  const op = (await designState(page)).deformations.at(-1)
  expect(op.params.total_degrees).toBe(signed)
  expect([...op.affected_helix_ids].sort()).toEqual([...first.helix_ids].sort())
  await reopen(page, `result-${index}`)
  await guide.capture(index === 1 ? 'The first half twists through 180° with Right-handed selected. Compare its rotating cross-section with the straight second cluster.' : 'The second half twists through 180° with Left-handed selected. The two intervals show opposite twist directions within the selected cluster.')
}

async function routingMenu(page, id) {
  await page.locator('#menu-item-tools').hover()
  await page.locator('#menu-item-tools .submenu-item').filter({ hasText: /^Routing/ }).hover()
  await expect(page.locator(id)).toBeVisible()
}

test('Twist desktop guide', async ({ page }) => {
  const guide = await createGuide(page, process.env.NADOC_GUIDE_OUTPUT, 'Twist: cluster selection, handedness, loops and skips', { feature: 'twist' })
  const errors = []
  page.on('pageerror', error => errors.push(String(error)))
  await createSquarePart(page, preparation, 'twist')
  console.log('Guide renderer:', await page.evaluate(() => { const gl = document.querySelector('#canvas').getContext('webgl2'); const ext = gl?.getExtension('WEBGL_debug_renderer_info'); return ext ? gl.getParameter(ext.UNMASKED_RENDERER_WEBGL) : 'unavailable' }))
  await openExtrude(page, preparation)
  await selectFootprint(page, preparation, false)
  await page.locator('#extrude-next').click()
  await page.locator('#slice-length').fill(String(LENGTH))
  await page.locator('#slice-extrude-btn').click()
  await expect.poll(async () => (await designState(page)).helices.filter(h => h.length_bp === LENGTH).length).toBe(18)
  await addSeparateCluster(page, preparation, LENGTH)
  await fitClusters(page)
  await page.mouse.move(1900, 20)
  guide.section('Start with a longer model', 'Use the Extrude workflow to make two separated 3-row × 6-column square-lattice clusters, each 256 bp long. All 3D images use Full representation. This lesson makes two successive 180° twists with opposite handedness, then generates and inspects loop/skip marks through NADOC’s own tools.')
  await guide.capture('Start with two 3×6 square-lattice clusters, each 256 bp long. Right-drag to view the clusters from the side, then press F to fit.')

  guide.section('Twist the first half', 'Choose Tools → Twist, then click the original 18-helix cluster. Set Plane 1 to 0 bp and Plane 2 to 127 bp. Select Total twist, enter 180° and select Right-handed. The planes bound the twisted interval. After applying, reopen the saved part for a clean result view if the tool overlay remains dimmed (GUIDE-UX-008).')
  await twist(page, guide, { a: 0, b: 127, degrees: 180, handedness: 'rh', index: 1 })
  guide.section('Change handedness for the second half', 'Choose Tools → Twist again and select the same cluster. Set planes 128–255 bp, Total twist 180° and Left-handed. These adjacent intervals demonstrate the two handedness controls along one bundle. Total twist specifies the rotation across the selected interval; Degrees/nm specifies rotation per unit length.')
  await twist(page, guide, { a: 128, b: 255, degrees: 180, handedness: 'lh', index: 2 })

  guide.section('Generate loops and skips', 'Twist rotates the bundle cross-section along the selected interval. Add Loops/Skips creates the discrete insertion/deletion marks that accompany that design intent; use LOOP/SKIP to display the saved marks. The routing action requires crossovers, so first run Full Autostaple with Standard settings on this demonstration bundle.')
  await routingMenu(page, '#menu-routing-full-autostaple')
  await guide.click(page.locator('#menu-routing-full-autostaple'), 'Choose Tools → Routing → Full Autostaple to create the prerequisite staple routing and crossovers.')
  await expect(page.getByLabel('Method', { exact: true })).toHaveValue('standard')
  const routed = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/full-autostaple') && r.request().method() === 'POST', { timeout: 120000 })
  await guide.click(page.getByRole('button', { name: 'OK', exact: true }), 'Keep Standard selected and click OK.')
  expect((await routed).ok()).toBe(true)
  await expect.poll(async () => (await designState(page)).strands.some(s => s.domains.some((d, i) => i && d.helix_id !== s.domains[i - 1].helix_id))).toBe(true)
  await routingMenu(page, '#menu-seq-update-routing')
  const applied = page.waitForResponse(r => new URL(r.url()).pathname.includes('apply-deformations') && r.request().method() === 'POST', { timeout: 120000 })
  await guide.click(page.locator('#menu-seq-update-routing'), 'Choose Tools → Routing → Add Loops/Skips to generate marks for the square lattice and its twists.')
  expect((await applied).ok()).toBe(true)
  await expect.poll(async () => marks(await designState(page)).filter(m => m.delta > 0).length).toBeGreaterThan(0)
  await expect.poll(async () => marks(await designState(page)).filter(m => m.delta < 0).length).toBeGreaterThan(0)
  const realized = await designState(page)
  const selected = new Set(realized.deformations[0].affected_helix_ids)
  for (const helix of realized.helices.filter(h => selected.has(h.id))) {
    const net = (a,b) => helix.loop_skips.filter(m => m.bp_index >= a && m.bp_index < b).reduce((sum,m) => sum+m.delta,0)
    expect(net(0,127)).toBeGreaterThan(0)
    expect(net(128,255)).toBeLessThan(0)
  }
  await reopen(page, 'marks')
  guide.section('Inspect loops and skips in 3D', 'Click LOOP/SKIP in the View toolbar (P). Orange loop markers indicate inserted bases and red × markers indicate deleted bases. The overlay follows the twisted geometry while Full remains selected.')
  await guide.click(page.locator('.vt-btn[data-vt="loopSkips"]'), 'Click LOOP/SKIP in the View toolbar to show the markers.')
  await expect.poll(() => page.evaluate(async () => (await import('/src/state/store.js')).store.getState().showLoopSkips)).toBe(true)
  await page.mouse.move(1900, 20)
  await guide.capture('Full 3D view with loop and skip highlights on the twisted 3×6 bundle. Compare the marker distribution across the two twist intervals.')

  guide.section('Inspect the same marks in the cadnano editor', 'Open Origami Editor from the top bar. NADOC’s built-in cadnano-style path view shows the same document and loop/skip marks in a flat base-pair layout. Press F to fit, then zoom in to read individual symbols. The path view is a 2D topology view; the 3D window remains in Full representation.')
  const opened = page.waitForEvent('popup')
  await guide.click(page.locator('#btn-open-editor'), 'Click Origami Editor to open the same document in NADOC’s cadnano-style editor.')
  const editor = await opened
  editor.on('pageerror', error => errors.push(String(error)))
  await expect(editor.locator('#pathview-canvas')).toBeVisible()
  await expect.poll(() => editor.evaluate(async () => (await import('/src/cadnano-editor/store.js')).editorStore.getState().design?.helices?.length)).toBe(36)
  const editorDesign = await editor.evaluate(async () => (await import('/src/cadnano-editor/store.js')).editorStore.getState().design)
  expect(marks(editorDesign)).toEqual(marks(await designState(page)))
  await expect.poll(() => editor.evaluate(async () => (await import('/src/cadnano-editor/store.js')).editorStore.getState().viewTools.loopSkips)).toBe(true)
  await editor.locator('body').press('f')
  await editor.mouse.move(1900, 20)
  await guide.captureEditor(editor, 'The cadnano-style editor shows the same routed bundle and saved loop/skip marks. Blue circles denote loops; red × symbols denote skips.')
  await editor.mouse.move(850, 520)
  for (let i = 0; i < 7; i++) {
    await editor.mouse.wheel(0, -100)
    await editor.evaluate(() => new Promise(resolve => requestAnimationFrame(resolve)))
  }
  await editor.mouse.move(1900, 20)
  await guide.captureEditor(editor, 'Scroll up over the path view to enlarge the symbols. Blue loop circles and red skip crosses appear directly on the routed strands; LOOP/SKIP remains enabled in the View toolbar.')
  await editor.close()
  await verifySavedExample(page, (await designState(page)).feature_log.length, 36)
  expect(errors).toEqual([])
  await guide.finish()
})
