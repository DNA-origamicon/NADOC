import { test, expect } from '@playwright/test'
import { createGuide } from './capture.js'
import { createSquarePart, preparation, openExtrude, selectFootprint, designState, fitOblique, verifySavedExample, endMenu } from './workflow.js'

const row = (page, n) => page.locator(`#fl-list > [data-fl-row="${n}"]`)
async function closeDialog(page) { await page.locator('.modal__overlay:visible .modal__close').click() }
async function undo(page) {
  await page.locator('#menu-item-edit').hover()
  await page.locator('#menu-edit-undo').click()
}
async function seek(page, n) {
  const rail = await page.locator('#fl-rail').boundingBox()
  const target = await row(page, n).boundingBox()
  const thumb = await page.locator('#fl-rail div').filter({ has: page.locator('.feature-seek-readiness') }).boundingBox()
  await page.mouse.move(thumb.x + thumb.width / 2, thumb.y + thumb.height / 2)
  await page.mouse.down()
  await page.mouse.move(rail.x + 9, target.y + target.height / 2, { steps: 8 })
  await page.mouse.up()
  await expect(page.locator('#fl-rail [data-readiness="ready"]')).toBeAttached()
}

// Verify the scaffold's authored state AND its displayed coordinates across history.
async function scaffoldState(page) {
  return page.evaluate(async () => {
    const state = (await import('/src/state/store.js')).store.getState()
    const d = state.currentDesign
    const geometry = Object.fromEntries(state.currentGeometry.filter(n => n.strand_type === 'scaffold')
      .map(n => [`${n.helix_id}:${n.bp_index}:${n.direction}:${n.copy_k ?? n.copy ?? 0}`, n.backbone_position]))
    const rendered = window.__nadocTest.getResidueArrangements()
    return { strands: d.strands.filter(s => s.strand_type === 'scaffold'), helices: d.helices,
      deformations: d.deformations, clusters: d.cluster_transforms, geometry,
      rendered: Object.fromEntries(Object.keys(geometry).map(k => [k, rendered[k]?.bead])) }
  })
}
async function assertScaffoldRestored(page, before, label, { sequenceAssignment = false } = {}) {
  const after = await scaffoldState(page)
  if (sequenceAssignment) {
    // Full Autostaple assigns the scaffold sequence as part of its normal pipeline.
    const withoutSequence = strands => strands.map(({ sequence, ...strand }) => strand)
    before = { ...before, strands: withoutSequence(before.strands) }
    after.strands = withoutSequence(after.strands)
  }
  const issues = []
  for (const field of ['strands','helices','deformations','clusters']) {
    if (JSON.stringify(before[field]) !== JSON.stringify(after[field])) issues.push({ field, changed: true })
  }
  for (const field of ['geometry','rendered']) {
    const changed = []
    for (const k of new Set([...Object.keys(before[field]), ...Object.keys(after[field])])) {
      const a = before[field][k], b = after[field][k]
      if (!a || !b) { changed.push({ key:k, before:a, after:b }); continue }
      const av = Array.isArray(a) ? a : [a.x,a.y,a.z]
      const bv = Array.isArray(b) ? b : [b.x,b.y,b.z]
      const delta = Math.hypot(...av.map((v,i) => v-bv[i]))
      if (delta > 1e-5) changed.push({ key:k, delta, before:a, after:b })
    }
    if (changed.length) issues.push({ field, count:changed.length, examples:changed.slice(0,5) })
  }
  console.log('Scaffold restoration:', label, JSON.stringify(issues))
  expect(Object.keys(before.geometry).length).toBeGreaterThan(0)
  expect(issues, label).toEqual([])
}

// These are real orbit gestures. Reverse each gesture in reverse order to
// return to the comparison view without changing the authored structure.
async function inspectPerspectives(page, guide, stage) {
  async function orbit(dx, dy) {
    await page.mouse.move(1000, 560)
    await page.mouse.down({ button: 'right' })
    await page.mouse.move(1000 + dx, 560 + dy, { steps: 30 })
    await page.mouse.up({ button: 'right' })
    await page.waitForTimeout(600)
    await page.locator('#canvas').press('f')
    await page.waitForTimeout(500)
    await page.mouse.wheel(0, 100)
    await page.waitForTimeout(300)
  }
  await orbit(300, 110)
  await guide.capture(`${stage} — reverse oblique view. Right-drag to expose the scaffold ends hidden behind the bundle. Check that the terminal runs follow the bent body without a jump back to the straight axis.`)
  await orbit(180, -180)
  await guide.capture(`${stage} — end-region view. Orbit vertically as well as horizontally to separate overlapping rows. Inspect both ends and the junction between the 3×6 body and 2×6 continuation; use the view cube to orient yourself.`)
  await orbit(-180, 180)
  await orbit(-300, -110)
}

async function assertScaffoldContinuity(page) {
  const state = await scaffoldState(page)
  const distance = (a,b) => Math.hypot(...a.map((value,i) => value-b[i]))
  let max = 0, checked = 0
  for (const strand of state.strands) for (const domain of strand.domains) {
    const lo = Math.min(domain.start_bp,domain.end_bp), hi = Math.max(domain.start_bp,domain.end_bp)
    for (let bp=lo; bp<hi; bp++) {
      const a=state.geometry[`${domain.helix_id}:${bp}:${domain.direction}:0`]
      const b=state.geometry[`${domain.helix_id}:${bp+1}:${domain.direction}:0`]
      expect(a).toBeTruthy(); expect(b).toBeTruthy()
      max=Math.max(max,distance(a,b)); checked++
    }
  }
  expect(checked).toBeGreaterThan(0)
  console.log('Scaffold consecutive-base continuity:', { checked, maxDistanceNm:max })
  expect(max, 'Routing caps must not jump between bent and straight coordinate frames').toBeLessThan(2)
}

async function routingMenu(page, id) {
  await page.locator('#menu-item-tools').hover()
  await page.locator('#menu-item-tools .submenu-item').filter({ hasText: /^Routing/ }).hover()
  await expect(page.locator(id)).toBeVisible()
}
const editorState = page => page.evaluate(async () => (await import('/src/cadnano-editor/store.js')).editorStore.getState().design)

// Read-only canvas observation, like the existing 3D coordinate helpers. All edits
// below are real pointer drags; the adapter never changes design or selection.
async function installEndpointObserver(context) {
  await context.route('**/src/cadnano-editor/pathview.js', async route => {
    const response = await route.fetch()
    const source = await response.text()
    const marker = '  // ── Public interface'
    expect(source).toContain(marker)
    await route.fulfill({ response, body: source.replace(marker, `
  window.__guideEnds = () => _design.strands.filter(s => !s.is_circular && s.strand_type === 'staple').flatMap(s =>
    [['5p', s.domains[0], 'start_bp'], ['3p', s.domains.at(-1), 'end_bp']].flatMap(([end,d,key]) => {
      const row = _rowMap.get(d.helix_id)
      if (!row || Math.abs(d.start_bp-d.end_bp) < 8) return []
      const x = _bpCenterX(d[key]) * _zoom + _panX
      const y = row[d.direction === 'FORWARD' ? 'fwdY' : 'revY'] * _zoom + _panY
      const hit = _hitTest(x,y)
      const delta = (key === 'start_bp' ? Math.sign(d.end_bp-d.start_bp) : Math.sign(d.start_bp-d.end_bp)) * 2
      return [{ id:s.id, end, helix:d.helix_id, bp:d[key], delta, x,y,
        dx: (_bpCenterX(d[key]+delta)-_bpCenterX(d[key])) * _zoom,
        hittable: hit?.strand.id === s.id && hit.endWhich === end && !_hitTestCrossoverSprite(x,y) }]
    }))
` + marker) })
  })
}

test('Feature Log desktop guide', async ({ page, context }) => {
  await installEndpointObserver(context)
  page.setDefaultTimeout(20000)
  const guide = await createGuide(page, process.env.NADOC_GUIDE_OUTPUT, 'Feature Log: inspect, edit and verify the construction recipe')
  const errors = []
  page.on('pageerror', error => errors.push(String(error)))
  await createSquarePart(page, preparation, 'feature-log')
  await openExtrude(page, preparation)
  await selectFootprint(page, preparation, false)
  await page.locator('#extrude-next').click()
  await page.locator('#slice-length').fill('64')
  await page.locator('#slice-extrude-btn').click()
  await expect.poll(async () => (await designState(page)).helices.length).toBe(18)
  await fitOblique(page)
  let count = (await designState(page)).feature_log.length
  let helixCount = 18

  guide.section('Prepare the first extrusion', 'Start with a 3-row × 6-column square-lattice footprint, extruded 64 bp with Both strands. First practice editing and recipe verification on this initial feature, then add the 2×6 continuation, Bend, Autoscaffold and Full Autostaple. The later exercises use that richer construction history.')
  await guide.capture('The starting 3×6 extrusion has one recorded operation. Next revise its length before adding dependent operations.')
  guide.section('Edit a recorded feature', 'Click the pencil on an editable row to reopen its parameter editor. Native tools such as Extrude, Sweep, Bend/Twist and Move/Rotate use their corresponding editors; other feature types use parameter dialogs. Inspect the preview and apply the change to that feature. Later supported operations regenerate against the revised inputs. Cancel leaves the published recipe unchanged. Availability depends on feature type, cursor position, retained recovery data and downstream support; use the disabled control’s tooltip for the reason. Generated features may show a rebuild arrow instead of a pencil. Orange rail dots and connecting segments identify autogenerated steps belonging to the same generated run.')
  await guide.click(row(page, count).locator('button[title^="Edit"]'), 'Click the extrusion row’s pencil to edit its recorded parameters.')
  await expect(page.locator('#extrude-next')).toBeVisible()
  await page.locator('#extrude-next').click()
  await page.locator('#slice-length').fill('80')
  await guide.pointAt(page.locator('#slice-extrude-btn'), 'Change Length from 64 to 80 bp. Apply the historical edit using the tool’s confirmation button.')
  await page.locator('#slice-extrude-btn').click()
  await expect(page.locator('#extrude-panel')).not.toBeVisible()
  await expect.poll(async () => (await designState(page)).feature_log.at(-1).params.length_bp).toBe(80)
  expect((await designState(page)).feature_log).toHaveLength(count)
  await fitOblique(page)
  await guide.capture('The bundle is now 80 bp long. Editing updates the existing feature rather than appending a second extrusion.')

  guide.section('Undo and redo a history change', 'Use Edit → Undo (Ctrl+Z) to undo the last change, and Edit → Redo (Ctrl+Y) to restore it. These controls belong to the edit stack. The feature rail instead chooses a stage within the construction recipe. Use a named loadout when you want to retain an alternative for later work.')
  await undo(page)
  await expect.poll(async () => (await designState(page)).feature_log.at(-1).params.length_bp).toBe(64)
  await guide.capture('Undo restores the original 64 bp input in the same feature row.')
  await page.locator('#menu-item-edit').hover()
  await guide.click(page.locator('#menu-edit-redo'), 'Choose Edit → Redo to restore the 80 bp edit.')
  await expect.poll(async () => (await designState(page)).feature_log.at(-1).params.length_bp).toBe(80)

  guide.section('Check the published recipe', 'Click repair, then Check published recipe. This independently regenerates the published construction and reports its status. If a feature fails, inspect its issue and use Inspect failing input. Error badges identify failed and unevaluated steps; hover their explanations. Missing targets can also produce a warning triangle. Address the first failing input before interpreting later failures.')
  await guide.click(page.getByRole('button', { name: 'repair', exact: true }), 'Open repair to check the published recipe. Advanced repair proposals are outside this designer walkthrough.')
  await page.getByRole('button', { name: 'Check published recipe', exact: true }).click()
  await expect(page.locator('.part-repair [role="status"]').first()).toContainText('regenerated successfully', { timeout: 60000 })
  await guide.capture('Published geometry: regenerated successfully confirms that this example’s saved recipe reproduces its authored state.')
  await closeDialog(page)

  guide.section('Add the 2×6 continuation', 'Enable BLUNT, right-click a far-end ring and choose Extrude. Select two rows × six columns of the original footprint, then Next. Set 32 bp with Both strands and Ligate adjacent, and apply. This produces a stepped end: twelve helices continue beyond the original 80 bp body. F2 records the selected source ends and continuation inputs separately from F1.')
  await endMenu(page, guide, 'extrude')
  await page.waitForFunction(() => !document.querySelector('[data-camera-transition="true"]'))
  await page.waitForTimeout(500)
  const expectedCells = []
  for (let r = 0; r < 2; r++) for (let c = 1; c <= 6; c++) {
    const point = await page.evaluate(([r,c]) => window.__nadocTest.getSliceCellScreenPositions().find(p => p.row === r && p.col === c), [r,c])
    expect(point?.state).toBe('continuable')
    expect(await page.evaluate(p => document.elementFromPoint(p.x,p.y)?.id, point)).toBe('canvas')
    await page.mouse.click(point.x, point.y)
    expectedCells.push([r,c])
    await expect.poll(() => page.evaluate(() => window.SLICE.getSelectedCells().map(c => c.join(',')).sort())).toEqual(expectedCells.map(c => c.join(',')).sort())
  }
  await expect.poll(() => page.evaluate(() => window.SLICE.getSelectedCells().length)).toBe(12)
  await guide.capture('Select the 2×6 subset of amber source-end cells. The continuation selection contains twelve helices.')
  await page.locator('#extrude-next').click()
  await page.locator('#slice-length').fill('32')
  await guide.click(page.locator('#slice-extrude-btn'), 'Apply the extra 32 bp extrusion to these twelve ends.')
  await expect.poll(async () => (await designState(page)).feature_log.length).toBe(2)
  expect((await designState(page)).feature_log[1].op_kind).toBe('extrude-continuation')
  expect((await designState(page)).feature_log[1].params.cells).toEqual(expectedCells)
  expect((await designState(page)).helices).toHaveLength(18)
  await fitOblique(page)
  await guide.capture('F1 builds the 3×6 body; F2 adds the 2×6 continuation. They remain distinct recorded operations.')

  guide.section('Bend before routing', 'Choose Tools → Bend and click the cluster bead for the bundle. Set Plane 1 to 0 bp, Plane 2 to 79 bp, Angle to 30° and Direction to 0°, then Apply. This bends the original body before either routing operation. Reopen the saved part if the tool leaves its dimmed preview overlay behind (GUIDE-UX-008).')
  await page.locator('#menu-item-tools').hover()
  await page.locator('#menu-tools-bend').click()
  const blunt = page.locator('#view-tools [data-key="blunt"]')
  if ((await blunt.getAttribute('class')).includes('active')) await blunt.click()
  await page.waitForFunction(() => !document.querySelector('[data-camera-transition="true"]'))
  await page.waitForTimeout(500)
  const cluster = (await designState(page)).cluster_transforms.filter(c => c.helix_ids.length).sort((a,b) => b.helix_ids.length-a.helix_ids.length)[0]
  const bead = await page.evaluate(id => window.__nadocTest.getClusterBeadScreenPositions().find(p => p.id === id && document.elementFromPoint(p.x,p.y)?.id === 'canvas'), cluster.id)
  expect(bead).toBeTruthy()
  await guide.clickPoint(bead, 'Click a backbone bead to select the cluster for Bend. Turn BLUNT off so end rings do not intercept the selection.')
  await expect(page.locator('#def-bend-angle')).toBeEnabled()
  for (const [id,value] of [['#def-plane-a-bp','0'],['#def-plane-b-bp','79'],['#def-bend-dir','0']]) {
    await page.locator(id).fill(value)
    await page.locator(id).press('Tab')
  }
  const preview = page.waitForResponse(r => {
    if (!r.url().endsWith('/deformation-preview/evaluate') || r.request().method() !== 'POST') return false
    const p = r.request().postDataJSON()?.params
    return p?.plane_a_bp === 0 && p?.plane_b_bp === 79 && Math.abs(p.params?.curvature_deg_per_bp * 79 - 30) < 1e-4
  })
  await page.locator('#def-bend-angle').fill('30')
  await page.locator('#def-bend-angle').press('Tab')
  expect((await preview).ok()).toBe(true)
  await expect(page.locator('#def-apply-btn')).toBeEnabled()
  await guide.pointAt(page.locator('#def-apply-btn'), 'Apply the 30° bend over planes 0–79 bp. F3 will preserve these parameters.')
  await page.locator('#def-apply-btn').click()
  await expect.poll(async () => (await designState(page)).feature_log.length).toBe(3)
  helixCount = (await designState(page)).helices.length
  console.log('Continued/bent guide:', helixCount, 'helix records;', cluster.helix_ids.length, 'in selected cluster')
  await verifySavedExample(page, 3, helixCount)
  await page.goto('/?doc=__e2e__feature-log-bent&open=' + encodeURIComponent('__e2e__feature-log 3x6 square guide.nadoc') + '&open-type=part')
  await expect.poll(async () => (await designState(page))?.feature_log?.length).toBe(3)
  await fitOblique(page)
  await guide.capture('The bent, stepped bundle now has three construction operations, before scaffold and staple routing.')

  guide.section('Inspect the geometry from several sides', 'Right-drag the 3D canvas to orbit, then press F to fit the part and scroll down slightly for margin. Check the opposite side and look along the end regions as well as using the main oblique view. The view cube shows your orientation. Compare these perspectives before routing, after Autoscaffold, after Full Autostaple and after scrubbing. End bases, back rows and connections can hide behind an otherwise plausible overall silhouette.')
  await inspectPerspectives(page, guide, 'Before routing, F3')

  guide.section('Add scaffold and staple routing', 'Choose Tools → Routing → Autoscaffold, keep Seamed and click Run. Then choose Full Autostaple, keep Standard and click OK. Autoscaffold may adjust terminal positions; inspect its result rather than assuming the routed ends retain their extrusion indices. F4 and F5 record these generated routing operations after the two extrusions and Bend.')
  await routingMenu(page, '#menu-routing-scaffold-ends')
  await page.locator('#menu-routing-scaffold-ends').click()
  await page.locator('input[name="as-mode"][value="seamed"]').check()
  await page.locator('#as-run').click()
  await expect.poll(async () => (await designState(page)).feature_log.length, { timeout: 120000 }).toBe(4)
  await assertScaffoldContinuity(page)
  await guide.capture('Autoscaffold is F4: new terminal scaffold bases follow the deformation of the ends they extend. Inspect their continuity before applying Autostaple.')
  await inspectPerspectives(page, guide, 'After Autoscaffold, F4')
  const scaffoldBeforeStaple = await scaffoldState(page)
  await routingMenu(page, '#menu-routing-full-autostaple')
  await page.locator('#menu-routing-full-autostaple').click()
  await page.getByRole('dialog', { name: 'Autostaple method', exact: true }).getByRole('button', { name: 'OK', exact: true }).click()
  await expect.poll(async () => (await designState(page)).feature_log.length, { timeout: 120000 }).toBe(5)
  await assertScaffoldRestored(page, scaffoldBeforeStaple, 'Autostaple preserves scaffold routing and geometry', { sequenceAssignment: true })
  await assertScaffoldContinuity(page)
  count = 5
  helixCount = (await designState(page)).helices.length
  await page.locator('#canvas').press('f')
  await guide.capture('Full Autostaple is F5. Use this five-step recipe for the navigation, dependency and history-change exercises below.')

  await inspectPerspectives(page, guide, 'After Full Autostaple, F5')

  guide.section('Read the tab', 'Use the open Feature Log sidebar on the left. The vertical Feature Log launcher opens an additional sidebar; close extra copies with their header ×. This example now has five construction steps: a 3×6 extrusion, a 2×6 end continuation, Bend, Autoscaffold and Full Autostaple. F0 is the initial state. F1, F2 and later rows are ordered operations; hover a shortened label to read it. The heading collapses the section. The loadout selector chooses a saved design branch. Row buttons act on one feature; repair and filter act on the log. Selecting a strand, domain, cluster or overhang in the model outlines rows that reference it in green.')
  await guide.pointAt(page.locator('#feature-log-panel-heading'), 'Read the operation labels and their order before changing history. Hover each small button for its exact action and availability.')

  guide.section('Browse construction stages', 'Drag the blue handle along the vertical rail and release at a notch to scrub through construction. Clicking a bare notch does not seek. F0 restores the initial stage; a feature notch shows the state after that operation. Later rows dim while viewing an earlier stage. Browsing retains the recipe. Return to the last notch before changing its order, suppressing features or evaluating repair. A spinning ring means editable detail is loading; wait for Ready to edit. If loading fails, scrub again to retry.')
  const scaffoldBeforeScrub = await scaffoldState(page)
  await seek(page, 0)
  await expect.poll(async () => (await designState(page)).feature_log_cursor).toBe(-2)
  await guide.capture('At F0 the extrusion is absent, but its feature row remains. The blue cursor marks the inspected construction stage.')
  await seek(page, 2)
  await guide.capture('At F2, the 3×6 body and the extra 2×6 continuation are present, while Bend and the routing operations are still ahead of the cursor.')
  await seek(page, 3)
  await guide.capture('At F3, Bend has shaped the bundle. Autoscaffold and Full Autostaple remain dimmed because they have not yet been applied at this stage.')
  await seek(page, count)
  await expect.poll(async () => (await designState(page)).helices.length).toBe(helixCount)
  await assertScaffoldRestored(page, scaffoldBeforeScrub, 'Return to F5 after F0/F2/F3 scrub')
  await assertScaffoldContinuity(page)
  await inspectPerspectives(page, guide, 'Returned to F5 after scrubbing')
  await guide.capture('Return to the final notch to restore the complete editable part. Seeking and reverting have different consequences: reverting removes recipe entries.')

  guide.section('Inspect dependencies', 'Right-click a part feature row, or focus it and press Shift+F10, then choose View dependencies. Parents supply inputs to the selected operation; Dependents consume its outputs. Conservative ordering relationships may also appear. The actual regeneration check decides whether a proposed edit is valid. Use this view before moving, suppressing or deleting an earlier step.')
  await expect(page.locator('#sync-status-text')).toContainText('saved')
  await page.waitForTimeout(1000)
  await row(page, 1).click({ button: 'right' })
  await guide.capture('The row context menu provides Suppress, Move… and View dependencies for this multi-step part.')
  await page.getByText('View dependencies', { exact: true }).click()
  await expect(page.getByRole('dialog')).toBeVisible()
  await guide.capture('Read the first extrusion’s Parents and Dependents. Its outputs feed later construction; inspect these relationships before changing its order or deleting it.')
  await closeDialog(page)

  guide.section('Suppress and restore an operation', 'Suppress retains the feature definition while regenerating the part without applying it. The row gains a Suppressed badge. Right-click it again and choose Unsuppress to restore its contribution. Dependencies are checked before publication; an unresolved consumer prevents the change. Return to the current end of an editable loadout first.')
  await expect(page.locator('#sync-status-text')).toContainText('saved')
  await page.waitForTimeout(1000)
  await row(page, count).click({ button: 'right' })
  await page.getByText('Suppress', { exact: true }).click()
  await guide.capture('The suppression dialog explains that the saved definition will remain and regeneration will check its dependents.')
  await page.getByRole('button', { name: 'Suppress', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(row(page, count).locator('[data-history-status="suppressed"]')).toBeVisible()
  await guide.capture('The Suppressed badge records that the operation is disabled. The recipe still contains its inputs.')
  await expect(page.locator('#sync-status-text')).toContainText('saved')
  await page.waitForTimeout(1000)
  await row(page, count).click({ button: 'right' })
  await page.getByText('Unsuppress', { exact: true }).click()
  await page.getByRole('button', { name: 'Unsuppress', exact: true }).click()
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(row(page, count).locator('[data-history-status="suppressed"]')).toHaveCount(0)
  await expect.poll(async () => (await designState(page)).helices.length).toBe(helixCount)

  guide.section('Move a feature', 'For a part with at least two feature rows, right-click the operation and choose Move…. Select its final position, then click Move. NADOC regenerates the proposed order and refuses unresolved dependencies. The dialog disables Move until a different position is selected. Cancel closes it without applying the reorder. Here, inspect the available positions for the first extrusion, then cancel to preserve its upstream position.')

  await expect(page.locator('#sync-status-text')).toContainText('saved')
  await page.waitForTimeout(1000)
  await row(page, 1).click({ button: 'right' })
  await page.getByText('Move…', { exact: true }).click()
  const selectStyle = await page.getByLabel('New feature position').evaluate(select => {
    const style = getComputedStyle(select)
    const luminance = color => color.match(/[\d.]+/g).slice(0, 3).map(Number)
      .map(v => v / 255).map(v => v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4)
      .reduce((sum, v, i) => sum + v * [0.2126, 0.7152, 0.0722][i], 0)
    const values = [luminance(style.color), luminance(style.backgroundColor)].sort((a,b) => a-b)
    const bounds = select.getBoundingClientRect(), modal = select.closest('[role="dialog"]').getBoundingClientRect()
    return { color: style.color, background: style.backgroundColor,
      contrast: (values[1] + 0.05) / (values[0] + 0.05), fits: bounds.left >= modal.left && bounds.right <= modal.right }
  })
  console.log('Move selector appearance:', JSON.stringify(selectStyle))
  expect(selectStyle.contrast).toBeGreaterThanOrEqual(4.5)
  expect(selectStyle.fits).toBe(true)
  await guide.capture('Move selects a new position in the recipe. Moving the first extrusion behind operations that consume it can fail dependency validation. Cancel this inspection.')
  await page.getByRole('button', { name: 'Cancel', exact: true }).click()

  guide.section('Delete versus revert', 'The red × deletes a feature. In a standalone part, supported later steps are regenerated; if dependents prevent a simple deletion, review the offered cascade-delete or revert decision. Cascade removes the dependent operations listed by the dialog. The amber ↶ reverts to before the selected feature and removes it together with every later entry. Read the confirmation before accepting. Undo can restore the change. Large Fine Routing groups receive an additional deletion confirmation.')
  await guide.click(row(page, count).locator('button[title^="Revert"]'), 'Click ↶ to inspect Revert to before this feature.')
  await guide.capture('Revert discards this operation and the later tail of the recipe. Reverting the final Full Autostaple operation keeps both extrusions, Bend and Autoscaffold.')
  await page.getByRole('button', { name: 'Revert', exact: true }).click()
  await expect.poll(async () => (await designState(page)).feature_log.length).toBe(count - 1)
  await undo(page)
  await expect.poll(async () => (await designState(page)).feature_log.length).toBe(count)
  await guide.click(row(page, count).locator('button[title="Delete this feature"]'), 'Click × to delete the final Full Autostaple operation. A simple part feature deletion can apply immediately.')
  await expect.poll(async () => (await designState(page)).feature_log.length).toBe(count - 1)
  await undo(page)
  await expect.poll(async () => (await designState(page)).helices.length).toBe(helixCount)

  guide.section('Filter the log and expand Fine Routing', 'Click filter to choose visible categories. Fine routing is initially on; Document ops and Annotations and view volumes are initially off. Filters change visibility while preserving the recipe and feature numbering, so gaps can appear. Preferences persist for the document and synchronize across windows. A Fine Routing row groups small routing edits: click its triangle to expand individual sub-steps, inspect their rail positions, and use their available delete/revert controls. Collapse with the upper triangle, lower collapse row or connector spine. Tooltips explain unavailable child operations. Document ops is a separate journal of metadata and loadout changes, without geometry seek positions. Annotation and view-volume checkpoints appear when explicitly recorded; ordinary presentation autosaves do not produce construction rows.')
  await guide.click(page.getByRole('button', { name: 'filter', exact: true }), 'Open filter to inspect the three visibility categories.')
  await guide.capture('Enable Document ops to inspect the document journal; leave Fine routing enabled when diagnosing individual routing steps.')
  await page.getByLabel('Document ops', { exact: true }).check()
  await page.keyboard.press('Escape')

  guide.section('Keep alternatives with loadouts', 'The selector at the top switches loadouts. Click + to create an alternative from the current state, then the adjacent pencil to name it. The × deletes the active loadout after confirmation; the final remaining loadout cannot be deleted. Locked loadouts show a lock symbol and protect their saved state. Loadouts preserve alternative recipes; assembly targets have their own loadout context. Document ops shows the recorded create, rename, select and delete actions.')
  await guide.click(page.locator('button[title="Create loadout"]'), 'Click + to create a second loadout from the current bent, routed design.')
  await expect(page.locator('select[title="Select loadout"] option')).toHaveCount(2)
  page.once('dialog', dialog => dialog.accept('Routed alternative'))
  await page.locator('button[title="Rename loadout"]').click()
  await expect(page.locator('select[title="Select loadout"] option:checked')).toHaveText('Routed alternative')
  await guide.capture('Name the new loadout Routed alternative. The document journal records its creation and rename separately from the construction steps.')
  const original = await page.locator('select[title="Select loadout"] option').first().getAttribute('value')
  await page.locator('select[title="Select loadout"]').selectOption(original)
  await guide.capture('Use the selector to return to the original loadout. Each branch retains its construction process.')

  guide.section('Assembly targets and configurations', 'In an assembly, the Target selector offers Assembly, Configurations and individual part instances. Assembly shows assembly operations; choose an instance to inspect its embedded part history and loadouts. Repeated instances and their joins belong to the assembly recipe. In the current assembly UI, pencil editing is offered for the latest supported polymerization or overhang-connection operation. Deleting an earlier assembly entry replays later entries and refuses unsupported replay; ↶ drops the selected entry and all later ones. Part-instance controls currently differ from standalone-part controls: the context-menu dependency/suppression/reorder actions and standalone repair launcher are not offered, and some embedded history deletion paths remove log records without rebuilding geometry. For provenance-preserving changes, edit the source part in its own editor rather than using those embedded deletion controls. These are current implementation limitations.')
  guide.section('Capture and use assembly configurations', 'Choose Configurations in Target. Click + Capture Configuration to save the current assembly state. Click a configuration row to restore it, ▶ to animate to it, ⟳ to overwrite it with the current state, the pencil to rename it (Enter saves; Escape cancels), and × to delete it. The configuration list is distinct from the ordered assembly construction recipe. Animation also offers Pin to feature: enter that mode from the animation panel, click the desired feature when prompted, or Cancel to leave the picker. This section is a control reference; the captured part example does not contain an assembly or animation.')
  guide.section('Use the same log in Origami Editor', 'Open Origami Editor from the top bar, then choose its Feature Log tab beside the path view. This is the same document and construction recipe as the 3D editor. The shared panel provides history navigation, filters and supported history actions alongside the 2D topology view. Press F over the path view to fit the strands.')
  await assertScaffoldRestored(page, scaffoldBeforeScrub, 'After suppression, revert/delete Undo and loadout round trip')
  const opened = page.waitForEvent('popup')
  await page.locator('#btn-open-editor').click()
  const editor = await opened
  editor.on('pageerror', error => errors.push(String(error)))
  await expect(editor.locator('#pathview-canvas')).toBeVisible()
  await editor.locator('[data-tab="feature-log"]').click()
  await expect(editor.locator('#cadnano-feature-log-container')).toHaveClass(/is-active/)
  await expect.poll(() => editor.evaluate(async () => (await import('/src/cadnano-editor/store.js')).editorStore.getState().design?.feature_log?.length)).toBe(count)
  await editor.locator('body').press('f')
  await guide.captureEditor(editor, 'Choose Feature Log beside the path view to inspect both extrusions, Bend, Autoscaffold and Full Autostaple in the same document.')
  guide.section('Make two fine routing edits', 'In Origami Editor, use the Select tool and drag a free staple end inward by two bases. Repeat on a different staple end. These are two separate resize actions, not a multi-selection drag. The Feature Log collects consecutive small routing edits into one Fine Routing group, while retaining each operation and its exact end reference.')
  const baseline = await editorState(editor)
  const snapshots = [baseline]
  const used = []
  for (let i = 0; i < 2; i++) {
    await editor.locator('body').press('f')
    const box = await editor.locator('#pathview-canvas').boundingBox()
    const ends = await editor.evaluate(() => window.__guideEnds())
    const end = ends.find(e => e.hittable && !used.includes(e.id) && e.x > 60 && e.x < box.width - 40 && e.y > 30 && e.y < box.height - 30)
    expect(end, 'a visible free staple end for a real resize drag').toBeTruthy()
    used.push(end.id)
    const start = { x:box.x + end.x, y:box.y + end.y }
    const finish = { x:start.x + end.dx, y:start.y }
    await guide.captureEditor(editor, `Resize ${i+1}: drag the marked staple ${end.end === '5p' ? '5′' : '3′'} end from bp ${end.bp} to ${end.bp + end.delta}, shortening it by two bases.`, { ...start, end:finish })
    const resized = editor.waitForResponse(r => r.url().endsWith('/strand-end-resize') && r.request().method() === 'POST')
    await editor.mouse.move(start.x,start.y)
    await editor.mouse.down()
    await editor.mouse.move(finish.x,finish.y,{ steps:12 })
    await editor.mouse.up()
    expect((await resized).ok()).toBe(true)
    await expect.poll(async () => (await editorState(editor)).feature_log.at(-1)?.children?.length).toBe(i+1)
    const current = await editorState(editor)
    const child = current.feature_log.at(-1).children.at(-1)
    expect(child.op_subtype).toBe('strand-end-resize')
    expect(child.params.entries).toHaveLength(1)
    expect(child.params.entries[0].delta_bp).toBe(end.delta)
    snapshots.push(current)
  }
  count++
  await expect.poll(async () => (await designState(page)).feature_log.at(-1)?.children?.length).toBe(2)
  await guide.captureEditor(editor, 'Two distinct endpoint drags produce one Fine Routing group with two retained sub-steps. The group follows Full Autostaple.')
  await editor.getByTitle('Expand Fine Routing', { exact:true }).click()
  await guide.captureEditor(editor, 'Expand the triangle to show both Resize strand ends sub-steps, their individual rail notches, pencils, delete buttons and revert arrows.')

  guide.section('Scrub inside the group', 'Drag the blue rail handle to the first resize sub-step. The first end is resized and the second is still at its original position. The complete group remains in the recipe. Drag to the second sub-step or final group notch to recover both edits. Grouping does not flatten the edit history.')
  await seek(editor, `${count}.0`)
  await expect.poll(async () => (await editorState(editor)).strands).toEqual(snapshots[1].strands)
  await guide.captureEditor(editor, 'At the first sub-step only the first resize is applied. The second sub-step remains in the log ahead of the cursor.')
  await seek(editor, count)
  await expect.poll(async () => (await editorState(editor)).strands).toEqual(snapshots[2].strands)

  guide.section('Revert one sub-step or the whole group', 'The second sub-step’s ↶ reverts to before that resize: it removes the second edit and later history, retaining the first resize. Undo restores it. The Fine Routing group’s ↶ instead reverts to before the entire group, removing both resizes while retaining Full Autostaple and the earlier construction. Undo restores both. The individual × deletes its sub-step subject to downstream regeneration; its pencil opens its recorded inputs.')
  await row(editor, `${count}.1`).getByTitle('Revert to before sub-step 2', { exact:true }).click()
  await guide.captureEditor(editor, 'Confirm the second sub-step revert to keep the first resize and discard the second.')
  await editor.getByRole('button', { name:'Revert', exact:true }).click()
  await expect.poll(async () => (await editorState(editor)).feature_log.at(-1).children.length).toBe(1)
  await expect.poll(async () => (await editorState(editor)).strands).toEqual(snapshots[1].strands)
  await guide.captureEditor(editor, 'After reverting the second sub-step, the first resize remains as the sole child of Fine Routing.')
  await editor.keyboard.press('Control+z')
  await expect.poll(async () => (await editorState(editor)).feature_log.at(-1).children.length).toBe(2)
  await row(editor,count).getByTitle('Revert to before this Fine Routing cluster', { exact:true }).click()
  await editor.getByRole('button', { name:'Revert', exact:true }).click()
  await expect.poll(async () => (await editorState(editor)).feature_log.length).toBe(count-1)
  await expect.poll(async () => (await editorState(editor)).strands).toEqual(baseline.strands)
  await guide.captureEditor(editor, 'Group revert removes both resizes and restores the routed baseline. Both extrusions, Bend, Autoscaffold and Full Autostaple remain.')
  await editor.keyboard.press('Control+z')
  await expect.poll(async () => (await editorState(editor)).strands).toEqual(snapshots[2].strands)
  await expect.poll(async () => (await designState(page)).feature_log.at(-1)?.children?.length).toBe(2)
  await guide.captureEditor(editor, 'Undo restores the Fine Routing group and both individual resize operations. The saved example retains them for further exploration.')

  await editor.close()

  await verifySavedExample(page, count, helixCount)
  const before = await designState(page)
  const scaffoldBeforeReopen = await scaffoldState(page)
  await page.goto('/?doc=__e2e__feature-log-reopen&open=' + encodeURIComponent('__e2e__feature-log 3x6 square guide.nadoc') + '&open-type=part')
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await expect.poll(async () => (await designState(page))?.feature_log?.length).toBe(count)
  const after = await designState(page)
  expect(after.feature_log.map(f => [f.id, f.feature_type, f.op_kind, f.params, (f.children ?? []).map(c => [c.id, c.op_subtype, c.params])])).toEqual(before.feature_log.map(f => [f.id, f.feature_type, f.op_kind, f.params, (f.children ?? []).map(c => [c.id, c.op_subtype, c.params])]))
  expect(after.strands).toEqual(before.strands)
  guide.section('Save and reopen', 'Save the part with its feature log and loadouts. Reopen it and inspect the saved operation inputs before continuing. The downloadable example accompanying this guide is reopened and independently replayed by the publication guard. The illustrated actions use a disposable example; apply them to your own design after inspecting its dependencies.')
  await fitOblique(page)
  await assertScaffoldRestored(page, scaffoldBeforeReopen, 'Saved/reopened scaffold')
  await guide.capture('Reopened example: both extrusions, Bend, Autoscaffold, Full Autostaple and the two recorded Fine Routing resizes remain available.')
  expect(errors).toEqual([])
  await guide.finish()
})
