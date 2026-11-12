import { test, expect } from '@playwright/test'
import { readFile, readdir } from 'node:fs/promises'
import path from 'node:path'
import { createGuide } from './capture.js'
import { DEFAULT_GUIDE_MODEL, guideCells } from './model.js'

const designState = page => page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign)
const selectedCells = page => page.evaluate(() => window.SLICE.getSelectedCells())

async function existingMaterialOpacity(page) {
  return page.evaluate(() => {
    const values = []
    window.__NADOC_DBG__.designRenderer.getHelixCtrl()?.root.traverse(object => {
      for (const material of (Array.isArray(object.material) ? object.material : [object.material])) {
        if (material) values.push(material.opacity * (material.customProgramCacheKey().endsWith('|nadoc-authoring-opacity') ? .15 : 1))
      }
    })
    return Math.max(...values)
  })
}

async function openExtrude(page, guide) {
  await page.locator('.menu-item').filter({ hasText: 'Tools' }).first().hover()
  await guide.click(page.locator('#menu-tools-extrude'), 'Open Tools → Extrude to start a new extrusion.')
  await expect(page.locator('#extrude-panel')).toBeVisible()
}

async function selectFootprint(page, guide, explain = true) {
  await page.waitForFunction(() => !document.querySelector('[data-camera-transition="true"]'))
  const cells = guideCells()
  await page.mouse.move(1350, 800)
  let points
  await expect.poll(async () => {
    points = await page.evaluate(cells => {
      const visible = window.__nadocTest.getSliceCellScreenPositions()
      return cells.map(([r, c]) => visible.find(p => p.row === r && p.col === c))
    }, cells)
    return points.every(Boolean)
  }).toBe(true)
  expect(points.every(Boolean), 'All 18 footprint cells must be visible').toBe(true)
  for (const point of points) expect(await page.evaluate(p => document.elementFromPoint(p.x, p.y)?.id, point)).toBe('canvas')
  if (explain) {
    await guide.clickPoint(points[0], 'Click a cell to select it. Click the same cell again to deselect it.')
    await expect.poll(() => selectedCells(page)).toHaveLength(1)
    await page.mouse.click(points[0].x, points[0].y)
    await expect.poll(() => selectedCells(page)).toHaveLength(0)
  }
  // Box-select the 3×6 footprint through normal canvas input.
  await page.locator('#canvas').press('Tab')
  const margin = Math.abs(points[1].x - points[0].x) * 0.48
  const start = { x: Math.min(...points.map(p => p.x)) - margin, y: Math.min(...points.map(p => p.y)) - margin }
  const end = { x: Math.max(...points.map(p => p.x)) + margin, y: Math.max(...points.map(p => p.y)) + margin }
  await guide.capture('With the canvas focused, press Tab for box selection. Left-drag from upper left to lower right, enclosing the entire circles of the 3-row × 6-column footprint. Left-to-right requires full enclosure; right-to-left selects touching cells.', { ...start, end })
  await page.mouse.move(start.x, start.y)
  await page.mouse.down()
  await page.mouse.move(end.x, end.y, { steps: 20 })
  await page.mouse.up()
  await expect.poll(async () => (await selectedCells(page)).map(c => c.join(',')).sort()).toEqual(cells.map(c => c.join(',')).sort())
  await page.locator('#canvas').press('Tab')
  await guide.capture('The count must read 18 helices. Tab returns to ordinary cell picking; a left-drag can also paint cells along its path.')
}

async function fitOblique(page) {
  await page.locator('#canvas').press('f')
  await page.mouse.move(1150, 650)
  await page.mouse.down({ button: 'right' })
  await page.mouse.move(1300, 720, { steps: 20 })
  await page.mouse.up({ button: 'right' })
  await page.locator('#canvas').press('f')
  await page.mouse.move(1100, 650)
  await page.mouse.wheel(0, 60)
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
}

async function endMenu(page, guide, action) {
  await page.locator('#canvas').press('f')
  await page.mouse.move(1100, 650)
  await page.mouse.wheel(0, 100)
  const toggle = page.locator('#view-tools [data-key="blunt"]')
  if (!(await toggle.getAttribute('class')).includes('active')) {
    await guide.click(toggle, 'Enable BLUNT in the toolbar to show selectable end rings.')
  }
  let end
  await expect.poll(async () => {
    end = await page.evaluate(() => window.__nadocTest.getDomainEndScreenPositions()
      .filter(p => p.openSide === 1 && document.elementFromPoint(p.x, p.y)?.id === 'canvas')
      .sort((a, b) => b.x - a.x)[0])
    return !!end
  }).toBe(true)
  await guide.clickPoint(end, `Right-click the marked far-end ring, then choose ${action === 'bend' ? 'Bend' : 'Extrude'} from its menu.`, { button: 'right' })
  await guide.click(page.locator(`#blunt-${action}-btn-ctx`), `Choose ${action === 'bend' ? 'Bend to prepare the deformed-end example' : 'Extrude to continue from this end'}.`)
  return end
}

async function continueEnd(page, guide) {
  const before = await designState(page)
  const end = await endMenu(page, guide, 'extrude')
  await expect(page.locator('#extrude-from')).toBeDisabled()
  await expect.poll(() => existingMaterialOpacity(page)).toBeLessThanOrEqual(0.15)
  await guide.pointAt(page.locator('#extrude-from'), 'From is locked to the selected source end. The tool chooses the initial direction away from the existing body.')
  const helix = before.helices.find(h => h.id === end.helixId)
  let cell
  await expect.poll(async () => {
    cell = await page.evaluate(([r, c]) => window.__nadocTest.getSliceCellScreenPositions().find(p => p.row === r && p.col === c), helix.grid_pos)
    return !!cell && cell.state === 'continuable'
  }).toBe(true)
  expect(await page.evaluate(p => document.elementFromPoint(p.x, p.y)?.id, cell)).toBe('canvas')
  await guide.clickPoint(cell, 'Select the amber cell at the chosen end. This focused example extends one helix within the 3×6 model; select more compatible cells to extend a wider footprint.')
  await expect.poll(() => selectedCells(page)).toHaveLength(1)
  await guide.click(page.locator('#extrude-next'), 'Click Next to keep the selected end and inspect the continuation in 3D.')
  await page.locator('#slice-length').fill('8')
  {
    await guide.click(page.locator('#slice-dir-bwd'), 'For this far end, − points back into existing DNA. Inspect the red overlap feedback.')
    await guide.click(page.locator('#slice-extrude-btn'), 'Attempting the overlapping extrusion is refused. Correct the direction rather than forcing the operation.')
    expect((await designState(page)).feature_log).toEqual(before.feature_log)
    await guide.click(page.locator('#slice-dir-fwd'), 'Restore + to extrude away from this far end. A near-end continuation normally defaults to −.')
  }
  await guide.click(page.locator('#slice-extrude-btn'), 'With 8 bp, Both and Ligate adjacent selected, apply the continuation.')
  await expect.poll(async () => (await designState(page)).feature_log.length).toBe(before.feature_log.length + 1)
  expect((await designState(page)).feature_log.at(-1).op_kind).toBe('extrude-continuation')
  await expect.poll(() => existingMaterialOpacity(page)).toBeGreaterThan(0.15)
  await page.locator('#canvas').press('f')
  await page.mouse.move(1100, 650)
  await page.mouse.wheel(0, 60)
  await guide.capture('The selected end has been extended and the continuation has its own history entry. Unselected helices retain their previous extent.')
}

test('Extrude desktop guide', async ({ page }) => {
  const guide = await createGuide(page, process.env.NADOC_GUIDE_OUTPUT, 'Extrude: a 3×6 square-lattice walkthrough', { feature: 'extrude' })
  const errors = []
  page.on('pageerror', error => errors.push(String(error)))
  page.on('console', message => { if (message.type() === 'error' && /Shader Error|VALIDATE_STATUS|GL_INVALID/.test(message.text())) errors.push(message.text()) })
  guide.section('Create a square-lattice part', 'The shared guide model is three rows × six columns: 18 helices on a square lattice. This lesson uses 64 bp initially. A painted lattice footprint is not yet a routed origami; scaffold routing and staple design are separate operations.')
  await page.goto('/?doc=__e2e__extrude-guide')
  await expect(page.locator('#canvas')).toBeVisible()
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await guide.click(page.locator('#menu-file-new'), 'Choose File → New.')
  await page.locator('#new-design-name').fill('__e2e__Extrude 3x6 square guide')
  await guide.click(page.locator('input[name="new-lattice-type"][value="SQUARE"]'), 'Choose Square for the lattice type. The guide uses a temporary example name; use a meaningful name for your own part.')
  await guide.click(page.getByRole('button', { name: 'Create', exact: true }), 'Click Create to open the empty square-lattice part.')
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  expect((await designState(page)).lattice_type).toBe(DEFAULT_GUIDE_MODEL.lattice)
  await expect(page.locator('#menu-view-detail-full')).toHaveClass(/is-checked/)
  await guide.capture('Use Full representation throughout this guide. Full shows the nucleotide beads and base slabs; it is the standard display for guides.')

  guide.section('Choose a source plane', 'The From control chooses the construction plane, not a camera view. XY extrudes normal to XY, XZ normal to XZ, and YZ normal to YZ. The camera turns smoothly to face the selected plane over 0.5 seconds, and orbit is locked during cross-section selection. Changing the plane clears an in-progress footprint: choose the plane before selecting cells. Tools → Extrude starts a new footprint; end continuation uses a different entry point shown later.')
  await openExtrude(page, guide)
  for (const plane of ['XZ', 'YZ', 'XY']) {
    await page.locator('#extrude-from').selectOption(plane)
    await guide.pointAt(page.locator('#extrude-from'), `Choose ${plane} in From. ${plane === 'XY' ? 'Return to XY for the main example.' : 'Notice the construction plane changes.'}`)
    expect(await selectedCells(page)).toEqual([])
    const camera = await page.evaluate(() => window.__nadocTest.viewerDiagnostic().camera)
    const direction = camera.position.map((v, i) => v - camera.target[i])
    const axis = { XY: 2, XZ: 1, YZ: 0 }[plane]
    expect(Math.abs(direction[axis]) / Math.hypot(...direction)).toBeCloseTo(1, 5)
  }
  await page.mouse.move(1500, 850)

  guide.section('Select the 3×6 footprint', 'Select three consecutive rows and six consecutive columns. Here the displayed indices are rows 0–2 and columns 1–6, positioned beside the floating tool panel. The offset is only to keep the targets visible; the footprint is still 3×6. Drag the tool-window title bar if it covers your intended cells. Extrude and Sweep share this cross-section picker and normal-view workflow. Grid colors identify strand-direction parity; the +/− extrusion buttons below are a separate choice.')
  await selectFootprint(page, guide)

  guide.section('Set length, units and direction', 'Step 1 selects the cross-section. Click Next for Step 2: the camera transitions over 0.5 seconds to a fitted oblique 3D view, and the lattice cannot be repainted accidentally. The initial length is zero; enter a nonzero length to show the preview. Changing the length or direction refits the preview. Previous returns to the normal cross-section view while retaining the length and selected cells. Square-lattice spinner/arrow steps are 8 bp; you can type a different integer directly. In nm mode the entered distance is rounded to an integer number of base pairs using 0.334 nm/bp. Changing the unit reinterprets the field; enter the corresponding numeric value explicitly. +/− controls the extrusion direction, independently of the grid color.')
  await expect(page.locator('#slice-length')).not.toBeVisible()
  await guide.click(page.locator('#extrude-next'), 'Click Next. The footprint is retained, the picker is hidden, and the camera changes to a fitted 3D view for length and direction.')
  await expect(page.locator('#extrude-from')).not.toBeVisible()
  await expect.poll(async () => (await page.evaluate(() => window.__nadocTest.getSliceCellScreenPositions())).length).toBe(0)
  await page.locator('#slice-length').fill('0')
  await guide.click(page.locator('#slice-extrude-btn'), 'With length 0, Extrude refuses to build and asks for a length. The footprint remains available for correction.')
  expect((await designState(page)).helices).toHaveLength(0)
  await page.locator('#slice-length').fill('64')
  await guide.pointAt(page.locator('#slice-length'), 'Enter 64 bp. The readout should show 18 × 64 bp = 1152 bp total.')
  await expect(page.locator('#slice-total-bp')).toContainText('1152')
  await page.locator('#slice-length').press('ArrowUp')
  await expect(page.locator('#slice-length')).toHaveValue('72')
  await page.locator('#slice-length').press('ArrowDown')
  await page.locator('#slice-unit').selectOption('nm')
  await page.locator('#slice-length').fill('21.376')
  await guide.pointAt(page.locator('#slice-unit'), 'For the same 64 bp length, choose nm and enter 21.376. The total remains 1152 bp.')
  await expect(page.locator('#slice-total-bp')).toContainText('1152')
  await page.locator('#slice-unit').selectOption('bp')
  await page.locator('#slice-length').fill('64')
  await guide.click(page.locator('#slice-dir-bwd'), 'Click − to preview extrusion on the opposite side of the plane.')
  await guide.capture('The negative-direction readout and preview change together. No DNA has been committed yet.')
  await guide.click(page.locator('#slice-dir-fwd'), 'Return to + for the main example.')

  guide.section('Use scaffold-length recommendations', 'The 7249 and 8064 chips propose a per-helix length for the current selection. They reserve 14 nt per helix for end loops: floor(target / selected helices) − 14. They size this extrusion alone, not the entire existing design. They do not route a scaffold, assign its sequence, or certify a scaffold-length fit after later routing.')
  for (const [target, bp] of [[7249, 388], [8064, 434]]) {
    await guide.click(page.locator('#slice-scaffold-rec .rec-chip').filter({ hasText: String(target) }), `Click ${target} to fill ${bp} bp for 18 selected helices.`)
    await expect(page.locator('#slice-length')).toHaveValue(String(bp))
    await guide.pointAt(page.locator('#slice-length'), `The recommendation sets the field to ${bp} bp and switches the unit to bp. Restore 64 bp for this lesson.`)
  }
  await page.locator('#slice-length').fill('64')

  guide.section('Choose strands and ligation', 'Both, Scaffold and Staples select which strand classes the extrusion creates or extends. These controls do not perform an autoscaffold or autostaple routing operation. Ligate adjacent requests joining compatible neighboring strand ends at the extrusion boundary; leaving it unchecked keeps the new segment unligated. Compatibility depends on the source ends and selected strand classes. In an empty part there are no upstream ends to join.')
  await guide.click(page.locator('#slice-cancel-btn'), 'Click Previous to return to the cross-section and strand choices. The view becomes normal to the source plane again.')
  expect(await selectedCells(page)).toHaveLength(18)
  await expect(page.locator('#slice-length')).toHaveValue('64')
  for (const value of ['scaffold', 'staples', 'both']) {
    await guide.click(page.locator(`input[name="slice-strand-filter"][value="${value}"]`), `Choose ${value === 'both' ? 'Both for the main example' : value === 'scaffold' ? 'Scaffold to restrict the extrusion to scaffold strands' : 'Staples to restrict the extrusion to staple strands'}.`)
  }
  await guide.click(page.locator('#slice-ligate-adjacent'), 'Uncheck Ligate adjacent when the new segment should remain unligated to upstream ends.')
  await expect(page.locator('#slice-ligate-adjacent')).not.toBeChecked()
  await guide.click(page.locator('#slice-ligate-adjacent'), 'Restore Ligate adjacent for this example and the later continuation.')

  await guide.click(page.locator('#extrude-next'), 'Click Next again. The same 18 cells and 64 bp length are retained and shown in 3D.')

  guide.section('Cancel a preview, then build', 'Preview changes are not authored structure. Cancel in Step 1, the window close button, or Escape discards the pending operation. Previous in Step 2 returns to selection without discarding inputs. Reopen the tool to start again. When ready, click Extrude (or press Enter in the length field). A successful operation is recorded in feature history. Red overlap feedback means the proposed extrusion intersects existing DNA; change direction/length or remove conflicting cells before applying.')
  await guide.click(page.getByRole('button', { name: 'Close Extrude', exact: true }), 'Close the Extrude window to discard this preview and selection.')
  await expect(page.locator('#extrude-panel')).not.toBeVisible()
  expect((await designState(page)).helices).toHaveLength(0)
  await openExtrude(page, guide)
  await page.locator('#extrude-from').selectOption('XY')
  await selectFootprint(page, guide, false)
  await guide.click(page.locator('#extrude-next'), 'Click Next to set the extrusion length in 3D.')
  await page.locator('#slice-length').fill('64')
  await guide.click(page.locator('#slice-extrude-btn'), 'With 18 cells, 64 bp, +, Both and Ligate adjacent selected, click Extrude.')
  await expect.poll(async () => (await designState(page)).helices.filter(h => h.length_bp === 64).length).toBe(18)
  await fitOblique(page)
  await guide.capture('Right-drag to orbit the result. Press F to fit, then scroll down slightly if the sidebars crowd the model. This is the 3×6 square-lattice, 64 bp example.')

  guide.section('Edit the recorded extrusion', 'The feature log preserves the construction inputs. Editing the feature changes its recorded parameters and rebuilds dependent operations. Cancel abandons the edit; Apply commits it. Undo and Redo operate through Edit → Undo/Redo (Ctrl+Z/Ctrl+Y). Review later dependent features after upstream changes.')
  const edit = page.locator('#left-panel button[title^="Edit "][title$=" parameters"]').first()
  await guide.click(edit, 'Click the edit control on the Extrude feature row.')
  await expect(page.locator('#extrude-panel')).toBeVisible()
  await guide.click(page.locator('#extrude-next'), 'The recorded footprint opens in Step 1. Click Next to edit its length in 3D.')
  await page.locator('#slice-length').fill('72')
  await guide.pointAt(page.locator('#slice-length'), 'Change the length to 72 bp. Close the window first to verify that the original 64 bp design is preserved.')
  await guide.click(page.getByRole('button', { name: 'Close Extrude', exact: true }), 'Close the window to cancel this trial edit.')
  await expect(page.locator('#extrude-panel')).not.toBeVisible()
  await expect.poll(async () => { const d = await designState(page); return d.helices.length === 18 && d.helices.every(h => h.length_bp === 64) }).toBe(true)
  await guide.click(edit, 'Reopen the feature edit to make a deliberate change.')
  await guide.click(page.locator('#extrude-next'), 'Click Next to return to the length controls.')
  await page.locator('#slice-length').fill('72')
  await guide.click(page.locator('#slice-extrude-btn'), 'Click Apply to rebuild the recorded extrusion at 72 bp.')
  await expect.poll(async () => { const d = await designState(page); return d.helices.length === 18 && d.helices.every(h => h.length_bp === 72) }).toBe(true)
  await page.locator('.menu-item').filter({ hasText: 'Edit' }).first().hover()
  await guide.click(page.locator('#menu-edit-undo'), 'Use Edit → Undo to restore 64 bp.')
  await expect.poll(async () => { const d = await designState(page); return d.helices.length === 18 && d.helices.every(h => h.length_bp === 64) }).toBe(true)
  await page.locator('.menu-item').filter({ hasText: 'Edit' }).first().hover()
  await guide.click(page.locator('#menu-edit-redo'), 'Use Edit → Redo to restore the 72 bp edit. The saved example retains this demonstrated change.')
  await expect.poll(async () => { const d = await designState(page); return d.helices.length === 18 && d.helices.every(h => h.length_bp === 72) }).toBe(true)

  guide.section('Continue from an existing end', 'Use BLUNT end rings to identify the source. Right-click an end → Extrude, or left-click the end and use the Extrude action in Properties. Amber cells represent compatible ends that can be continued. Step 1 faces the inherited source plane; Next opens the length preview in 3D. Existing geometry is shown at 15% opacity while the tool is open, making the new preview easier to see; closing or applying restores its normal display. The plane is inherited from the source; +/− defaults away from the body. Select only the ends you intend to extend. Ligate adjacent controls boundary joining; an unligated segment is a different result, not an equivalent continuation.')
  await continueEnd(page, guide)

  guide.section('Deformed-end continuation: current limitation', 'For a bent or twisted source, show Deformed View, right-click an end and choose Extrude. The tool uses the local deformed frame and locks From to the source. However, the current backend places new cells using honeycomb coordinates even for a square source, and its request does not carry the strand-filter/ligation controls. This square-lattice guide therefore demonstrates entry and Cancel only. Do not treat the square deformed-continuation result as verified. GUIDE-UX-004 tracks the gap; the feature remains partially covered until it is resolved and a successful continuation is demonstrated. We add a small 10° Bend through the normal UI to show the entry point; this is geometric CAD deformation, not physical relaxation.')
  await endMenu(page, guide, 'bend')
  await expect(page.locator('#def-bend-angle')).toBeVisible()
  const evaluated = page.waitForResponse(r => new URL(r.url()).pathname.endsWith('/deformation-preview/evaluate'))
  await page.locator('#def-bend-angle').fill('10')
  await page.locator('#def-bend-angle').press('Tab')
  expect((await evaluated).ok()).toBe(true)
  await guide.pointAt(page.locator('#def-bend-angle'), 'For this preparation step, use a 10° Bend. Review the selected scope and start/end planes.')
  await expect(page.locator('#def-apply-btn')).toBeEnabled()
  await guide.click(page.locator('#def-apply-btn'), 'Apply the Bend before continuing its deformed end.')
  await expect.poll(async () => (await designState(page)).deformations.length).toBeGreaterThan(0)
  const beforeDeformedPreview = await designState(page)
  await endMenu(page, guide, 'extrude')
  await expect(page.locator('#mode-indicator')).toContainText('DEFORMED CONTINUATION')
  await expect(page.locator('#extrude-from')).toBeDisabled()
  await guide.pointAt(page.locator('#extrude-from'), 'The source plane is locked in deformed continuation. This entry point is available, but square-lattice placement is not verified: stop here for this model.')
  await guide.click(page.locator('#slice-cancel-btn'), 'Cancel this deformed-continuation preview. No deformed extrusion is committed in the downloadable example.')
  expect((await designState(page)).feature_log).toEqual(beforeDeformedPreview.feature_log)
  await page.locator('#canvas').press('f')
  await page.mouse.move(1100, 650)
  await page.mouse.wheel(0, 100)

  guide.section('Save and troubleshoot', 'The downloaded example includes the full demonstrated construction: the edited 3×6 extrusion, straight continuation and Bend preparation. The deformed-continuation preview is canceled because of the documented square-lattice limitation. Use the feature log to inspect the earlier stages. If a target is covered, drag the tool-window title bar or adjust the camera. If the footprint count is wrong, check full-circle enclosure for left-to-right box selection. If no preview appears, check for a nonzero length. If an overlap or backend error occurs, keep the pending inputs, correct the source/direction/length and retry. Cancel abandons the pending operation. Source-plane changes reset an unfinished footprint. Desktop controls are covered here; headset interactions require a separate VR guide.')
  await guide.capture('Inspect the final geometry and ordered feature log. NADOC autosaves the part; use File → Save As when you need a separately named user copy.')
  await expect.poll(async () => {
    const files = (await readdir(process.env.NADOC_WORKSPACE)).filter(f => f.startsWith('__e2e__') && f.endsWith('.nadoc'))
    if (files.length !== 1) return false
    const saved = JSON.parse(await readFile(path.join(process.env.NADOC_WORKSPACE, files[0]), 'utf8'))
    return saved.lattice_type === 'SQUARE' && saved.helices.length >= 18 && saved.feature_log.length >= 3
  }).toBe(true)
  // Exercise the shared Sweep host without authoring or adding guide chapters.
  const beforeSweep = (await designState(page)).feature_log
  await page.locator('.menu-item').filter({ hasText: 'Tools' }).first().hover()
  await page.locator('#menu-tools-sweep').click()
  await expect.poll(() => existingMaterialOpacity(page)).toBeLessThanOrEqual(0.15)
  for (const plane of ['XZ', 'YZ', 'XY']) {
    await page.locator('#sweep-plane').selectOption(plane)
    await page.waitForFunction(() => !document.querySelector('[data-camera-transition="true"]'))
    const camera = await page.evaluate(() => window.__nadocTest.viewerDiagnostic().camera)
    const direction = camera.position.map((v, i) => v - camera.target[i])
    expect(Math.abs(direction[{ XY: 2, XZ: 1, YZ: 0 }[plane]]) / Math.hypot(...direction)).toBeCloseTo(1, 5)
  }
  const sweepCell = await page.evaluate(() => window.__nadocTest.getSliceCellScreenPositions()
    .find(p => p.state === 'free' && document.elementFromPoint(p.x, p.y)?.id === 'canvas'))
  expect(sweepCell).toBeTruthy()
  await page.mouse.click(sweepCell.x, sweepCell.y)
  await expect(page.locator('#sweep-apply')).toBeEnabled()
  await page.locator('#sweep-apply').click()
  await expect(page.locator('#sweep-path')).toBeVisible()
  await page.locator('#sweep-cancel').click()
  await expect(page.locator('#sweep-footprint')).toBeVisible()
  expect(await selectedCells(page)).toHaveLength(1)
  await page.getByRole('button', { name: 'Close Sweep', exact: true }).click()
  await expect.poll(() => existingMaterialOpacity(page)).toBeGreaterThan(0.15)
  expect((await designState(page)).feature_log).toEqual(beforeSweep)
  expect(errors).toEqual([])
  await guide.finish()
})
