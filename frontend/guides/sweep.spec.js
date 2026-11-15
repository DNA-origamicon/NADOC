import { test, expect } from '@playwright/test'
import { createGuide } from './capture.js'
import { createSquarePart, selectFootprint, designState, fitOblique, verifySavedExample } from './workflow.js'

test('Sweep desktop guide', async ({ page }) => {
  const guide = await createGuide(page, process.env.NADOC_GUIDE_OUTPUT, 'Sweep: a 3×6 square-lattice path', { feature: 'sweep' })
  const errors = []
  page.on('pageerror', error => errors.push(String(error)))
  const ready = async () => {
    await expect(page.locator('#sweep-status')).toContainText('bp per helix')
    await expect(page.locator('#sweep-apply')).toBeEnabled()
  }
  const coordinate = axis => page.getByRole('spinbutton', { name: `Point ${axis} (nm)` })

  guide.section('Create a square-lattice part', 'Sweep carries a lattice cross-section along a spline. This example uses the same three rows × six columns (18 helices) as the Extrude guide, with a path defined in nanometers.')
  await createSquarePart(page, guide, 'sweep')
  guide.section('Choose the source and plane', 'Open Tools → Sweep. From selects a new bundle or an existing helix end. For this example choose New bundle and XY. Plane sets the initial cross-section; choose it before selecting cells, because changing planes clears the footprint.')
  await page.locator('.menu-item').filter({ hasText: 'Tools' }).first().hover()
  await guide.click(page.locator('#menu-tools-sweep'), 'Open Tools → Sweep.')
  await expect(page.locator('#sweep-panel')).toBeVisible()
  await guide.pointAt(page.locator('#sweep-source'), 'Keep From set to New bundle.')
  await page.locator('#sweep-plane').selectOption('XY')
  await guide.pointAt(page.locator('#sweep-plane'), 'Choose XY for a cross-section initially normal to Z. XZ and YZ are also available.')

  guide.section('Select the 3×6 cross-section', 'The picker faces the selected plane and shares the Extrude selection gestures. Select rows 0–2 and columns 1–6: 18 helices. Drag the tool window by its title bar if it covers your intended cells.')
  await selectFootprint(page, guide)
  guide.section('Choose strands and ligation', 'Include chooses Both, Scaffold or Staples. Ligate adjacent requests joining compatible strand ends when continuing a source. Use Both with Ligate adjacent checked for this example.')
  for (const value of ['scaffold', 'staples', 'both']) {
    await page.locator('#sweep-strands').selectOption(value)
    await guide.pointAt(page.locator('#sweep-strands'), `Choose ${value === 'both' ? 'Both for this example' : value === 'scaffold' ? 'Scaffold to create only scaffold strands' : 'Staples to create only staple strands'}.`)
  }
  await guide.pointAt(page.locator('#sweep-ligate'), 'Keep Ligate adjacent checked. The new-bundle example has no upstream ends to join.')

  guide.section('Define the path in nanometers', 'Click Next to leave the cross-section picker and define the path in 3D. XYZ values are offsets in nm from the cross-section center. Select a point in the list to edit it. The initial XY path runs from Origin (0, 0, 0) to Point 1 (0, 0, 10). Previous returns to cross-section selection while retaining the path.')
  await expect(page.locator('#sweep-apply')).toBeEnabled()
  await guide.click(page.locator('#sweep-apply'), 'Click Next to open Step 2: Define sweep path.')
  await ready()
  await coordinate('Z').fill('30')
  await ready()
  await page.mouse.move(1100, 600)
  await page.mouse.wheel(0, 250)
  await guide.pointAt(coordinate('Z'), 'With Point 1 selected, set Z to 30 nm. Keep X = 0 and Y = 0.')
  await guide.click(page.getByRole('button', { name: 'Add sweep point' }), 'Click + Add point. The new point extrapolates the last segment and becomes selected.')
  await coordinate('X').fill('12')
  await ready()
  await page.mouse.move(1100, 600)
  await page.mouse.wheel(0, 200)
  await guide.pointAt(coordinate('X'), 'For Point 2 enter X = 12, Y = 0, Z = 60 nm. The spline bends toward positive X. Scroll down over the canvas to zoom out as the path grows.')
  await expect(coordinate('Z')).toHaveValue('60')
  await guide.pointAt(page.getByRole('listbox', { name: 'Sweep points' }), 'Review the ordered path: Origin (0, 0, 0), Point 1 (0, 0, 30), Point 2 (12, 0, 60). The × beside a non-origin point deletes it; a path needs at least two points.')

  guide.section('Control direction and twist', 'Select a point, then enable Control direction and twist to set Tilt X, Tilt Y and Twist in degrees. Green arrows indicate direction and amber arrows indicate the right axis. Disabling the checkbox restores automatic orientation. Selected points also have position handles in the canvas; Tab on the canvas or point entry switches to free-angle rotation handles.')
  await guide.click(page.getByRole('checkbox', { name: 'Control point orientation' }), 'Enable Control direction and twist for Point 2.')
  await page.getByRole('spinbutton', { name: 'Twist (degrees)' }).fill('15')
  await page.getByRole('spinbutton', { name: 'Twist (degrees)' }).press('Tab')
  await ready()
  await guide.pointAt(page.getByRole('spinbutton', { name: 'Twist (degrees)' }), 'Enter 15° in Twist to inspect the end cross-section orientation.')
  await guide.click(page.getByRole('checkbox', { name: 'Control point orientation' }), 'Disable Control direction and twist to use automatic orientation for the final example.')
  await ready()

  guide.section('Review and confirm', 'The status reports path length in nm and bp per helix. New BP reports the total new base-pair sites across the selected cross-section. Review any curvature warning before confirming; adjust the path if needed. Confirm creates the swept bundle.')
  await guide.pointAt(page.locator('#sweep-info'), 'Read New BP and the path-length status for the 18 selected helices.')
  await guide.click(page.locator('#sweep-apply'), 'Click Confirm to build the sweep.')
  await expect(page.locator('#sweep-panel')).not.toBeVisible()
  await expect.poll(async () => (await designState(page)).helices.length).toBe(18)
  expect((await designState(page)).feature_log.map(entry => entry.op_kind)).toEqual(['sweep'])
  await fitOblique(page)
  await guide.capture('The completed 3×6 bundle follows the curved path. Right-drag to orbit and press F to fit the result; Full representation shows the nucleotide geometry.')
  await verifySavedExample(page, 1)
  expect(errors).toEqual([])
  await guide.finish()
})
