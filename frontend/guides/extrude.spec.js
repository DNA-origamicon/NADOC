import { test, expect } from '@playwright/test'
import { createGuide } from './capture.js'
import { designState, selectedCells, createSquarePart, openExtrude, selectFootprint, fitOblique, continueEnd, addSeparateCluster, verifySavedExample } from './workflow.js'

test('Extrude desktop guide', async ({ page }) => {
  const guide = await createGuide(page, process.env.NADOC_GUIDE_OUTPUT, 'Extrude: a 3×6 square-lattice walkthrough', { feature: 'extrude' })
  const errors = []
  page.on('pageerror', error => errors.push(String(error)))
  page.on('console', message => { if (message.type() === 'error' && /Shader Error|VALIDATE_STATUS|GL_INVALID/.test(message.text())) errors.push(message.text()) })
  guide.section('Create a square-lattice part', 'The shared guide model is three rows × six columns: 18 helices on a square lattice. This lesson uses 64 bp initially.')
  await createSquarePart(page, guide, 'extrude')

  guide.section('Choose a source plane', 'The From control chooses the construction plane. XY extrudes normal to XY, XZ normal to XZ, and YZ normal to YZ. The camera turns smoothly to face the selected plane over 0.5 seconds, and orbit is locked during cross-section selection. Changing the plane clears an in-progress footprint: choose the plane before selecting cells. Tools → Extrude starts a new footprint; end continuation uses a different entry point shown later.')
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

  guide.section('Choose strands and ligation', 'Both, Scaffold and Staples select which strand classes the extrusion creates or extends. Ligate adjacent requests joining compatible neighboring strand ends at the extrusion boundary; leaving it unchecked keeps the new segment unligated. Compatibility depends on the source ends and selected strand classes.')
  for (const value of ['scaffold', 'staples', 'both']) {
    await guide.click(page.locator(`input[name="slice-strand-filter"][value="${value}"]`), `Choose ${value === 'both' ? 'Both for the main example' : value === 'scaffold' ? 'Scaffold to restrict the extrusion to scaffold strands' : 'Staples to restrict the extrusion to staple strands'}.`)
  }
  await guide.click(page.locator('#slice-ligate-adjacent'), 'Uncheck Ligate adjacent when the new segment should remain unligated to upstream ends.')
  await expect(page.locator('#slice-ligate-adjacent')).not.toBeChecked()
  await guide.click(page.locator('#slice-ligate-adjacent'), 'Restore Ligate adjacent for this example and the later continuation.')



  guide.section('Set length, units and direction', 'Step 1 selects the cross-section. Click Next for Step 2: the camera transitions over 0.5 seconds to a fitted oblique 3D view. The initial length is zero; enter a nonzero length to show the preview. Changing the length or direction refits the preview. Previous returns to the normal cross-section view while retaining the length and selected cells. Square-lattice spinner/arrow steps are 8 bp; you can type a different integer directly. In nm mode the entered distance is rounded to an integer number of base pairs using 0.334 nm/bp. Changing the unit reinterprets the field; enter the corresponding numeric value explicitly. +/− controls the extrusion direction, independently of the grid color.')
  await expect(page.locator('#slice-length')).not.toBeVisible()
  await guide.click(page.locator('#extrude-next'), 'Click Next. The footprint is retained, the picker is hidden, and the camera changes to a fitted 3D view for length and direction.')
  await expect(page.locator('#extrude-from')).not.toBeVisible()
  await expect.poll(async () => (await page.evaluate(() => window.__nadocTest.getSliceCellScreenPositions())).length).toBe(0)
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
  await guide.capture('The negative-direction readout and preview change together.')
  await guide.click(page.locator('#slice-dir-fwd'), 'Return to + for the main example.')

  guide.section('Use scaffold-length recommendations', 'The 7249 and 8064 chips propose a per-helix length for the current selection. They reserve 14 nt per helix for end loops: floor(target / selected helices) − 14. The recommendation sizes the selected extrusion.')
  for (const [target, bp] of [[7249, 388], [8064, 434]]) {
    await guide.click(page.locator('#slice-scaffold-rec .rec-chip').filter({ hasText: String(target) }), `Click ${target} to fill ${bp} bp for 18 selected helices.`)
    await expect(page.locator('#slice-length')).toHaveValue(String(bp))
    await guide.pointAt(page.locator('#slice-length'), `The recommendation sets the field to ${bp} bp and switches the unit to bp. Restore 64 bp for this lesson.`)
  }
  await page.locator('#slice-length').fill('64')

  guide.section('Build the extrusion', 'Review the 18-cell cross-section, 64 bp length and forward direction, then apply the extrusion.')
  await guide.click(page.locator('#slice-extrude-btn'), 'With 18 cells, 64 bp, +, Both and Ligate adjacent selected, click Extrude.')
  await expect.poll(async () => (await designState(page)).helices.filter(h => h.length_bp === 64).length).toBe(18)
  await fitOblique(page)
  await guide.capture('Right-drag to orbit the result. Press F to fit, then scroll down slightly if the sidebars crowd the model. This is the 3×6 square-lattice, 64 bp example.')

  guide.section('Continue from an existing end', 'Use BLUNT end rings to identify the source. Right-click an end → Extrude, or left-click the end and use the Extrude action in Properties. Amber cells represent compatible ends that can be continued. Step 1 faces the inherited source plane; Next opens the length preview in 3D. Existing geometry is shown at 15% opacity while the tool is open, making the new preview easier to see; closing or applying restores its normal display. The plane is inherited from the source; +/− defaults away from the body. Select only the ends you intend to extend. Ligate adjacent joins compatible strand ends at the boundary.')
  await continueEnd(page, guide)

  guide.section('Create a separate cluster', 'Open Tools → Extrude and select another 3×6 footprint a few cells away from the existing geometry. The gap creates a separate cluster that you can select and transform independently.')
  await addSeparateCluster(page, guide, 64)

  await verifySavedExample(page, 3, 36)
  expect(errors).toEqual([])
  await guide.finish()
})
