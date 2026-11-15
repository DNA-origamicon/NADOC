import { test, expect } from '@playwright/test'
import { readFile, stat } from 'node:fs/promises'
import path from 'node:path'
import { createGuide } from './capture.js'
import { designState, fitOblique } from './workflow.js'

const STRAIGHT = '__e2e__6hb-straight'
const BENT = '__e2e__6hb-circle-unit'
const cells = [[0,1],[1,1],[1,2],[1,3],[0,3],[0,2]]
const state = page => page.evaluate(async () => (await import('/src/state/store.js')).store.getState())
async function toolsMenu(page, submenu, id) {
  await page.locator('#menu-item-tools').hover()
  await page.locator('#menu-item-tools .submenu-item').filter({ hasText: new RegExp(`^${submenu}`) }).hover()
  await expect(page.locator(id)).toBeVisible()
}
async function saved(page, name) {
  await expect.poll(async () => {
    try {
      const d = JSON.parse(await readFile(path.join(process.env.NADOC_WORKSPACE, `${name}.nadoc`), 'utf8'))
      const current = await designState(page)
      return d.feature_log.length === current.feature_log.length && d.id === current.id
    } catch { return false }
  }, { timeout: 60000 }).toBe(true)
}
async function command(page, guide, id, caption, submenu = 'Routing') {
  const count = (await designState(page)).feature_log.length
  await toolsMenu(page, submenu, id)
  await guide.click(page.locator(id), caption)
  await expect.poll(async () => (await designState(page)).feature_log.length, { timeout: 120000 }).toBe(count + 1)
}
async function openPart(page, name) {
  await page.goto(`/?doc=__e2e__${name}-reopen&open=${encodeURIComponent(name + '.nadoc')}&open-type=part`)
  await expect.poll(async () => (await designState(page))?.helices?.length).toBe(6)
  await expect(page.locator('#file-load-progress')).not.toBeVisible({ timeout: 60000 })
  await fitOblique(page)
}
async function assembly(page, guide, name, source, count) {
  await page.goto(`/?doc=${name}`)
  await expect(page.locator('#canvas')).toBeVisible()
  page.once('dialog', dialog => dialog.accept(name))
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await guide.click(page.locator('#menu-file-new-assembly'), 'Choose File → New Assembly and give the assembly a name.')
  await expect.poll(async () => (await state(page)).assemblyActive).toBe(true)
  await page.locator('#menu-item-assembly').hover()
  await guide.click(page.locator('#menu-assembly-add-part'), 'Choose Assembly → Add Part to insert the saved periodic unit.')
  await guide.click(page.getByText(`${source}.nadoc`, { exact: true }).last(), `Choose ${source}.nadoc from the library.`)
  await expect.poll(async () => (await state(page)).currentAssembly?.instances?.length).toBe(1)
  const id = (await state(page)).currentAssembly.instances[0].id
  await expect.poll(() => page.evaluate(id =>
    window.__NADOC_DBG__?.assemblyRenderer?.getInstanceDesign(id)?.forced_ligations?.filter(f => f.is_periodic_seam).length ?? 0, id),
    { timeout: 120000 }).toBe(6)
  await page.locator('#menu-item-assembly').hover()
  await guide.click(page.locator('#menu-assembly-polymerize-origami'), 'Choose Assembly → Polymerize Origami.')
  await page.locator('#poly-mate-select').selectOption(`periodic:${id}`)
  await expect(page.locator('#poly-closure-text')).toContainText(/Chain (?:closes|does NOT close):/, { timeout: 60000 })
  await page.locator('#poly-count').fill(String(count))
  await page.locator('#poly-count').press('Tab')
  await expect(page.locator('#poly-closure-text')).toContainText(count === 6 ? 'Chain closes:' : 'Chain does NOT close:', { timeout: 60000 })
  await guide.pointAt(page.locator('#poly-count'), `Choose the part’s “via periodic boundary” entry, set Chain length to ${count} total, and keep Forward. The seed is included in this count.`)
  await guide.pointAt(page.locator('#poly-closure-text'), count === 6
    ? 'Wait for the closure calculation to finish after changing the count. Check “Chain closes” and both residuals before creating the ring. This tests the accumulated repeat transform.'
    : 'A straight chain reports “Chain does NOT close”; that is expected for a linear polymer.')
  await guide.click(page.locator('#poly-go-btn'), 'Click Polymerize to create the repeated part instances and seam mates in this assembly.')
  await expect.poll(async () => (await state(page)).currentAssembly?.instances?.length, { timeout: 60000 }).toBe(count)
  expect((await state(page)).currentAssembly.joints).toHaveLength(count - 1)
  await page.locator('#canvas').press('F2')
  await fitOblique(page)
  await guide.capture(count === 6
    ? 'Six bent units form a circular arrangement. Cylinders make the overall shape readable. The closure readout verifies geometric alignment; the feature creates five consecutive seam mates, not a sixth closing mate.'
    : 'The three units now form a real assembly polymer. Press F2 for Cylinders to inspect the overall arrangement; each repeat remains a separate part instance.')
  await expect.poll(async () => {
    try {
      const disk = JSON.parse(await readFile(path.join(process.env.NADOC_WORKSPACE, `${name}.nass`), 'utf8'))
      return (disk.instances_v2 ?? disk.instances ?? []).length
    } catch { return 0 }
  }).toBe(count)
}

test('Complete 6HB origami and periodic polymers', async ({ page }) => {
  page.setDefaultTimeout(20000)
  // Read-only fixture discovery: production hides every __e2e__ filename.
  // Expose only this run's real saved parts; all authoring requests stay real.
  await page.route('**/api/library/files', async route => {
    const response = await route.fetch(), entries = await response.json()
    for (const name of [STRAIGHT, BENT]) {
      const filename = `${name}.nadoc`
      try {
        const info = await stat(path.join(process.env.NADOC_WORKSPACE, filename))
        if (!entries.some(entry => entry.path === filename)) entries.push({ name, path: filename, type: 'part', mtime_iso: info.mtime.toISOString(), size_bytes: info.size })
      } catch (error) { if (error.code !== 'ENOENT') throw error }
    }
    await route.fulfill({ response, json: entries })
  })
  // This lesson explicitly teaches representations as well as construction.
  const guide = await createGuide(page, process.env.NADOC_GUIDE_OUTPUT, 'A complete 6HB origami: periodic ends, linear polymers and circles', { feature: 'representations' })
  const errors = []
  page.on('pageerror', error => errors.push(String(error)))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  guide.section('Create a standard honeycomb 6HB', 'Build the six-helix ring on a honeycomb lattice. Use your own descriptive filenames; the __e2e__ names shown here identify the isolated guide capture. This lesson uses a 1,236 bp initial extrusion; Seamed Autoscaffold adjusts the terminal turns to produce a single 7,560-nt scaffold matching p7560. Full representation is used for construction; later images explicitly demonstrate visualization choices.')
  await page.goto('/?doc=__e2e__6hb-guide')
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await guide.click(page.locator('#menu-file-new'), 'Choose File → New.')
  await page.locator('#new-design-name').fill(STRAIGHT)
  await page.locator('input[name="new-lattice-type"][value="HONEYCOMB"]').check()
  await guide.click(page.getByRole('button', { name: 'Create', exact: true }), 'Name the part and choose Honeycomb, then Create.')
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.locator('#menu-item-tools').hover()
  await guide.click(page.locator('#menu-tools-extrude'), 'Open Tools → Extrude. Choose the XY source plane.')
  await page.locator('#extrude-from').selectOption('XY')
  await page.waitForFunction(() => !document.querySelector('[data-camera-transition="true"]'))
  for (const [row, col] of cells) {
    const p = await page.evaluate(([r,c]) => window.__nadocTest.getSliceCellScreenPositions().find(p => p.row === r && p.col === c), [row,col])
    expect(p).toBeTruthy()
    expect(await page.evaluate(p => document.elementFromPoint(p.x,p.y)?.id, p)).toBe('canvas')
    await page.mouse.click(p.x,p.y)
  }
  await expect.poll(() => page.evaluate(() => window.SLICE.getSelectedCells().length)).toBe(6)
  await guide.capture('Select the six cells of the hexagonal ring: rows 0 and 1, columns 1–3. The count must read 6 helices.')
  await guide.click(page.locator('#extrude-next'), 'Click Next to set the bundle length.')
  await page.locator('#slice-length').fill('1236')
  await guide.click(page.locator('#slice-extrude-btn'), 'Set 1236 bp, + direction and Both strands; click Extrude.')
  await expect.poll(async () => (await designState(page)).helices.length).toBe(6)
  await fitOblique(page)

  guide.section('Route scaffold and staples', 'Run Seamed Autoscaffold to obtain matched end faces, then Standard Full Autostaple to route the interior staples. Autoscaffold can extend individual helix ends; inspect the routed scaffold length rather than assuming it equals six times the initial extrusion length.')
  await toolsMenu(page, 'Routing', '#menu-routing-scaffold-ends')
  await guide.click(page.locator('#menu-routing-scaffold-ends'), 'Choose Tools → Routing → Autoscaffold.')
  await page.locator('input[name="as-mode"][value="seamed"]').check()
  await guide.click(page.locator('#as-run'), 'Choose Seamed and click Run to route the scaffold with matched ends.')
  await expect.poll(async () => (await designState(page)).feature_log.length, { timeout: 120000 }).toBe(2)
  await toolsMenu(page, 'Routing', '#menu-routing-full-autostaple')
  await guide.click(page.locator('#menu-routing-full-autostaple'), 'Choose Tools → Routing → Full Autostaple.')
  await guide.click(page.getByRole('dialog', { name: 'Autostaple method', exact: true }).getByRole('button', { name: 'OK', exact: true }), 'Keep Standard and click OK to route the interior staples.')
  await expect.poll(async () => (await designState(page)).feature_log.length, { timeout: 120000 }).toBe(3)

  guide.section('Make the ends periodic', 'Route for Polymerization fills the bare terminal scaffold regions with connector staples and joins their terminal tips across the periodic seam. Each copy retains its own scaffold. The bridging staples join adjacent repeats; in the part they are recorded as periodic seam strands.')
  await command(page, guide, '#menu-routing-polymerization', 'Choose Tools → Routing → Route for Polymerization.')
  const routed = await designState(page)
  expect(routed.forced_ligations.filter(f => f.is_periodic_seam)).toHaveLength(6)
  await fitOblique(page)
  await guide.capture('The 6HB now has six periodic staple bridges, one for each face helix. Inspect their seam routing in the cadnano editor next.')

  guide.section('Assign the scaffold and staple sequences', 'Assign p7560 after routing so the entire 7,560-nt scaffold receives the intended sequence. Full Autostaple initially uses M13mp18; this explicit assignment replaces it. Then assign complementary staple sequences, including the periodic bridges. The saved example is checked for undefined bases.')
  await toolsMenu(page, 'Sequencing', '#menu-seq-assign-scaffold')
  await guide.click(page.locator('#menu-seq-assign-scaffold'), 'Choose Tools → Sequencing → Assign Scaffold Sequence.')
  await expect(page.locator('#asc-length-line')).toContainText('7560')
  await page.locator('input[name="asc-scaffold"][value="p7560"]').check()
  await guide.click(page.getByRole('dialog').filter({ hasText: 'Assign Scaffold Sequence' }).getByRole('button', { name: 'Apply', exact: true }), 'Select p7560 (7,560 nt), verify the matching scaffold length, and click Apply.')
  await expect.poll(async () => (await designState(page)).feature_log.length).toBe(5)
  await command(page, guide, '#menu-seq-assign-staples', 'Choose Assign Staple Sequences to complement all staples against the assigned scaffold.', 'Sequencing')
  expect((await designState(page)).strands.every(s => s.is_reference || (s.sequence && !s.sequence.includes('N')))).toBe(true)
  await saved(page, STRAIGHT)

  guide.section('Inspect topology and sequences in the cadnano editor', 'Open Origami Editor to inspect the same saved part as a flat strand diagram. Check scaffold continuity, staple crossovers, terminal connector staples and sequence assignment. The path view preserves base-pair indices even when the 3D part is bent.')
  const opened = page.waitForEvent('popup')
  await guide.click(page.locator('#btn-open-editor'), 'Click Origami Editor in the top bar.')
  const editor = await opened
  await expect(editor.locator('#pathview-canvas')).toBeVisible()
  await expect.poll(() => editor.evaluate(async () => (await import('/src/cadnano-editor/store.js')).editorStore.getState().design?.helices?.length)).toBe(6)
  await editor.locator('body').press('f')
  await guide.captureEditor(editor, 'Press F to fit all six helices. Follow the scaffold route and the staple crossovers between helices.')
  const pathBox = await editor.locator('#pathview-canvas').boundingBox()
  await editor.mouse.move(pathBox.x + pathBox.width / 2, pathBox.y + pathBox.height / 2)
  for (let i=0;i<18;i++) await editor.mouse.wheel(0,-100)
  await editor.locator('.vt-btn[data-vt="sequences"]').click()
  await editor.locator('.vt-btn[data-vt="undefinedBases"]').click()
  await guide.captureEditor(editor, 'Enable sequence letters and undefined-base highlighting. Zoom into domains to read individual bases; the verified example contains no undefined sequence bases.')

  guide.section('Use the periodic boundary view', 'Enable PBC to display translucent copies of the terminal regions beside the opposite ends. The two red boundary sliders define the display period P = far − near. Dashed seam connections pass through that boundary. Dragging a boundary changes this inspection view; editing a mirrored strand changes the real part. The view resets when disabled or reloaded.')
  await editor.locator('body').press('f')
  await editor.locator('.vt-btn[data-vt="periodicBoundary"]').click()
  await guide.captureEditor(editor, 'Click PBC to show the periodic boundary sliders, repeated end regions and dashed seam connections. Red ruler labels report the original base indices in the mirrored regions.')
  const boundary = await editor.evaluate(() => {
    const canvas = document.querySelector('#pathview-canvas'), ctx = canvas.getContext('2d')
    const { width: w, height: h } = canvas, pixels = ctx.getImageData(0,0,w,h).data
    const columns = []
    for (let x=50;x<w-10;x++) {
      let red=0, total=0
      for (let y=Math.floor(h*.55);y<h-10;y+=5) {
        const i=(y*w+x)*4; total++
        if (pixels[i]>120 && pixels[i]>pixels[i+1]*1.6 && pixels[i]>pixels[i+2]*1.4) red++
      }
      if (red/total>.8) columns.push(x)
    }
    const box=canvas.getBoundingClientRect()
    return columns.length ? { x:box.x+Math.max(...columns)*box.width/w-10, y:box.y+13*box.height/h } : null
  })
  expect(boundary, 'Periodic boundary handle visible').toBeTruthy()
  await editor.mouse.move(boundary.x,boundary.y)
  await editor.mouse.down()
  await editor.mouse.move(boundary.x+35,boundary.y,{steps:12})
  await editor.mouse.up()
  await guide.captureEditor(editor, 'Drag the far red ruler handle outward to change the display period. Read the seam-gap indicator and compare the displaced mirror with the real end; this moves the boundary, not the DNA.')
  await editor.locator('.vt-btn[data-vt="periodicBoundary"]').click()
  await editor.locator('.vt-btn[data-vt="periodicBoundary"]').click()
  await guide.captureEditor(editor, 'Toggle PBC off and on to restore the boundaries to the active strand extents before inspecting the seam.')
  const center = { x: pathBox.x + pathBox.width / 2, y: pathBox.y + pathBox.height / 2 }
  await editor.mouse.move(boundary.x+10, center.y)
  await editor.mouse.down({button:'right'})
  await editor.mouse.move(center.x, center.y, {steps:12})
  await editor.mouse.up({button:'right'})
  for (let i=0;i<18;i++) await editor.mouse.wheel(0,-100)
  await guide.captureEditor(editor, 'Right-drag to center the far boundary, then scroll up to inspect the seam and individual sequence bases. Compare the terminal scaffold and bridging staple on the real unit with the translucent neighboring unit; the mirror is an inspection view, not an assembly instance.')
  // At this fit/zoom the world-to-screen scale follows the read-only path layout.
  // The matched six helices each repeat after 1260 bp; their staggered union spans 1267.
  expect(routed.helices.every(h => h.length_bp === 1260)).toBe(true)
  const low = Math.min(...routed.helices.map(h => h.bp_start))
  const high = Math.max(...routed.helices.map(h => h.bp_start+h.length_bp))
  const bpWidth = pathBox.width / (40+(high+56)*10-Math.min(0,40+low*10)) * 10 * 1.15**18
  await editor.mouse.move(center.x-1, pathBox.y+13)
  await editor.mouse.down()
  await editor.mouse.move(center.x-(high-low-1260-0.5)*bpWidth, pathBox.y+13, {steps:12})
  await editor.mouse.up()
  await guide.captureEditor(editor, 'For this staggered 6HB, the physical repeat is 1260 bp while the default bounding span is 1267 bp. Move the far boundary 7 bp inward: the “overlap 7 bp” display lets the staggered ends interlock. This changes only the inspection period; assembly placement comes from the recorded seams.')
  await editor.close()

  guide.section('Choose useful 3D visualizations', 'Full shows nucleotide geometry; Cylinders simplify the bundle shape. Length coloring helps inspect the staple length distribution. The temperature overlay cycles through domain melting temperature and total staple folding temperature; these estimates support inspection rather than proving assembly yield. Periodic Seam Connections reveals the normally hidden long seam arcs in the single-part view.')
  await page.locator('#canvas').press('F2')
  await fitOblique(page)
  await guide.capture('Press F2 for Cylinders to inspect the long 6HB shape.')
  await page.locator('#canvas').press('F4')
  await page.locator('.vt-btn[data-vt="lengthHeatmap"]').click()
  await guide.capture('Press F4 for Full, then enable LENGTH to color staples by length.')
  await page.locator('.vt-btn[data-vt="lengthHeatmap"]').click()
  await page.locator('.vt-btn[data-vt="stapleTemperature"]').click()
  await guide.capture('Click TM to inspect domain melting temperatures with the displayed color scale.')
  await page.locator('.vt-btn[data-vt="stapleTemperature"]').click()
  await guide.capture('Click TM again for total staple folding temperatures. Check the legend to distinguish this from the domain view.')
  await page.locator('.vt-btn[data-vt="stapleTemperature"]').click()
  await page.locator('#menu-item-view').hover()
  await guide.click(page.locator('#menu-view-periodic-seam-arcs'), 'View → Periodic Seam Connections shows the long seam arcs on the unit; these are periodic connections, not strands passing through the bundle interior.')
  await guide.capture('Inspect the periodic connectors, then turn Periodic Seam Connections off for the polymer overview.')
  await page.locator('#menu-item-view').hover()
  await page.locator('#menu-view-periodic-seam-arcs').click()
  await saved(page, STRAIGHT)

  guide.section('Create an actual linear polymer assembly', 'Create a separate assembly and add the saved periodic part. The “via periodic boundary” option derives repeat placement from its seam strands. Chain length is the total number of units including the seed. Forward, Backward and Both choose where new repeats are placed relative to it.')
  await assembly(page, guide, '__e2e__6hb-linear-polymer', STRAIGHT, 3)

  guide.section('Bend a repeat for a circular polymer', 'Open the straight part and use Save As to create a separate circular unit. Tools → Bend offers Curve to make polymer circle after periodic strands exist. Set six units; the tool derives the curvature from the periodic seam span. Direction rotates the bending plane. This chapter demonstrates CAD curvature and geometric ring placement; it does not apply loop/skip compensation or validate the relaxed physical shape. The repeat is still a part; copies are created later in its assembly.')
  await openPart(page, STRAIGHT)
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await guide.click(page.locator('#menu-file-save-as'), 'Choose Save As to preserve the straight unit and create a separate bent unit.')
  await page.getByPlaceholder('filename', { exact: true }).fill(BENT)
  await guide.click(page.getByRole('button', { name: 'Save', exact: true }), 'Save the new part as the circular-unit example.')
  await page.locator('#select-filter-trigger').click()
  await guide.click(page.locator('#select-filter .sf-btn[data-key="clust"]'), 'Set Selectable to Cluster before choosing the complete 6HB.')
  let point
  await expect.poll(async () => {
    point = await page.evaluate(() => window.__nadocTest.getClusterBeadScreenPositions().find(p => document.elementFromPoint(p.x,p.y)?.id === 'canvas'))
    return !!point
  }).toBe(true)
  await guide.clickPoint(point, 'Click the 6HB to select the complete unit.')
  await expect.poll(async () => (await state(page)).selection?.items?.length ?? 0).toBeGreaterThan(0)
  await page.locator('#menu-item-tools').hover()
  await guide.click(page.locator('#menu-tools-bend'), 'Choose Tools → Bend with the complete unit selected; the planes span that selection.')
  try { await expect(page.locator('#def-polymer-circle')).toBeEnabled() }
  catch (error) { console.log('BEND PANEL:', await page.locator('#deform-panel').innerText()); throw error }
  await page.locator('#def-polymer-circle').check()
  await page.locator('#def-polymer-count').fill('6')
  await page.locator('#def-polymer-count').press('Tab')
  await expect(page.locator('#def-apply-btn')).toBeEnabled({ timeout: 60000 })
  await guide.pointAt(page.locator('#def-polymer-count'), 'Enable Curve to make polymer circle and enter 6 units. Review the calculated bend; refine this example’s angle in the next step before Apply.')
  await page.locator('#def-polymer-circle').uncheck()
  const adjusted = page.waitForResponse(response => {
    if (!new URL(response.url()).pathname.endsWith('/deformation-preview/evaluate')) return false
    const draft = response.request().postDataJSON()?.params
    return Math.abs(draft?.params?.curvature_deg_per_bp * 1266 - 60.3229) < .0001
  })
  await page.locator('#def-bend-angle').fill('60.3229')
  await page.locator('#def-bend-angle').press('Tab')
  expect((await adjusted).ok()).toBe(true)
  await expect(page.locator('#def-apply-btn')).toBeEnabled()
  await guide.pointAt(page.locator('#def-bend-angle'), 'For this exact 6HB, the automatic estimate leaves a 0.515 nm six-unit closure residual. Uncheck Curve to make polymer circle and refine Angle to 60.3229°, keeping Direction 0° and planes −12–1254 bp. The recorded manual setting meets the 0.5 nm closure tolerance; this value is specific to this example.')
  await page.locator('#def-apply-btn').click()
  await expect(page.locator('#deform-panel')).not.toBeVisible({ timeout: 60000 })
  expect((await designState(page)).deformations.at(-1).params.curvature_deg_per_bp * 1266).toBeCloseTo(60.3229, 4)
  await saved(page, BENT)
  await openPart(page, BENT)
  await guide.capture('The bent periodic unit is ready for repetition. Its source construction, routing and sequence assignment remain in its feature history.')

  guide.section('Build and inspect the circular assembly', 'Create a new assembly using the bent unit and choose six total repeats. Verify both the rotational and translational residuals before polymerizing. A circular arrangement requires the accumulated repeat transform to return to the starting frame; the closure check measures that alignment. Consecutive seam mates remain explicit assembly operations.')
  await assembly(page, guide, '__e2e__6hb-circular-polymer', BENT, 6)
  expect(errors).toEqual([])
  await guide.finish()
})
