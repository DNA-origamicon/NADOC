/**
 * Belt-path define UI: the two-phase interactive picker.
 *   joint phase → emphasized (1.5×) revolute markers
 *   rim phase   → un-emphasized markers + a mouse-follow circle + rim connectors
 * then the glowing belt tube + persistence. Drives the live app against
 * workspace/belt_test.nass (two revolute-mated pulleys with rim interface points).
 *
 * Run: cd frontend && npx playwright test e2e/belt_path_define.spec.js \
 *        --config playwright.bench.config.js --reporter=list
 */
import { test, expect } from '@playwright/test'
import { existsSync, readFileSync } from 'node:fs'
import { resolve as resolvePath } from 'node:path'

const FIXTURE = resolvePath(process.cwd(), '..', 'workspace', 'belt_test.nass')
test.setTimeout(120_000)
test.skip(!existsSync(FIXTURE), `fixture missing: ${FIXTURE}`)

// Scene probes — counts/sizes of the belt overlay objects.
function probe(page) {
  return page.evaluate(() => {
    const D = window.__NADOC_DBG__
    const vis = o => { let p = o; while (p) { if (!p.visible) return false; p = p.parent } return true }
    let markerRings = [], beltMeshes = 0, circleVisible = false, circleA = false, circleB = false, pathMeshes = 0
    D.scene.traverse(o => {
      if (o.name === 'beltJointMarkers' && o.visible) {
        o.traverse(c => { if (c.isMesh && c.geometry?.type === 'TorusGeometry') markerRings.push(+c.geometry.parameters.radius.toFixed(3)) })
      }
      if (o.name === 'beltPreview') o.traverse(c => { if (c.isMesh) beltMeshes++ })
      if (o.name === 'beltPaths') o.traverse(c => { if (c.isMesh) pathMeshes++ })
      if (o.name === 'beltRimCircle') circleVisible = vis(o)
      if (o.name === 'beltCircleA') circleA = vis(o)
      if (o.name === 'beltCircleB') circleB = vis(o)
    })
    return { markerRings: markerRings.sort(), beltMeshes, pathMeshes, circleVisible, circleA, circleB }
  })
}

function setSel(page, id, match) {
  return page.evaluate(({ id, match }) => {
    const sel = document.getElementById(id)
    const opt = [...sel.options].find(o => o.textContent.includes(match) && o.value)
    sel.value = opt.value
    sel.dispatchEvent(new Event('change', { bubbles: true }))
    return sel.value
  }, { id, match })
}

test('belt picker: emphasized markers → rim circle → belt tube → persist', async ({ page }) => {
  page.on('pageerror', e => console.log('[pageerror] ' + e.message))
  await page.goto('http://localhost:5173/')
  await page.waitForFunction(() => !!window.__NADOC_DBG__?.store, null, { timeout: 30_000 })

  const nass = readFileSync(FIXTURE, 'utf-8')
  await page.evaluate(async (content) => {
    const api = await import('/src/api/client.js')
    await api.importAssembly(content)
    window.__NADOC_DBG__.store.setState({ assemblyActive: true })
  }, nass)
  await page.waitForFunction(
    () => (window.__NADOC_DBG__.store.getState().currentAssembly?.joints?.length ?? 0) === 2,
    null, { timeout: 30_000 })
  await page.waitForTimeout(3000) // settle renderer rebuild → connector map populated

  await page.evaluate(() => {
    const b = document.getElementById('menu-assembly-define-belt')
    b.removeAttribute('disabled'); b.click()
  })
  await expect(page.locator('#belt-path-panel')).toBeVisible({ timeout: 10_000 })

  // ── Phase: pick joint A — two emphasized markers (1.5× of RING_R 1.18 ≈ 1.77) ──
  const p0 = await probe(page)
  console.log('joint-A phase:', JSON.stringify(p0))
  expect(p0.markerRings.length).toBe(2)
  expect(p0.markerRings.every(r => Math.abs(r - 1.77) < 0.02)).toBe(true)
  expect(p0.beltMeshes).toBe(0)
  expect(await page.locator('#belt-hint').textContent()).toContain('pulley A')

  // Pick pulley A's revolute → rim-A phase: markers un-emphasized + the picked
  // joint excluded, so one normal-size ring (≈1.18). Mouse-follow circle appears.
  await setSel(page, 'belt-joint-a', 'PulleyA')
  const p1 = await probe(page)
  console.log('rim-A phase:', JSON.stringify(p1))
  expect(p1.markerRings.length).toBe(1)
  expect(Math.abs(p1.markerRings[0] - 1.18) < 0.02).toBe(true)
  expect(await page.locator('#belt-hint').textContent()).toContain('rim connector')
  // connector dropdown A now lists the rim connector.
  expect(await page.locator('#belt-conn-a').textContent()).toContain('PulleyA_rim')

  // Mouse-follow circle: needs a laid-out canvas + real camera projection, which
  // this state-injection harness can't supply (the editor UI transition is
  // skipped, so the canvas has no layout box). Best-effort only.
  const box = await page.locator('canvas').first().boundingBox()
  if (box) {
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
    await page.mouse.move(box.x + box.width / 2 + 30, box.y + box.height / 2 + 20)
    await page.waitForTimeout(150)
    console.log('after pointer move, circleVisible:', (await probe(page)).circleVisible)
  } else {
    console.log('canvas not laid out (landing overlay) — skipping mouse-circle probe')
  }

  // Pick rim A → joint-B phase: emphasized markers again, jointA excluded (1 ring ≈1.77).
  // Pulley A's locked circle now persists.
  await setSel(page, 'belt-conn-a', 'PulleyA_rim')
  const p2 = await probe(page)
  console.log('joint-B phase:', JSON.stringify(p2))
  expect(p2.markerRings.length).toBe(1)
  expect(Math.abs(p2.markerRings[0] - 1.77) < 0.02).toBe(true)
  expect(p2.circleA).toBe(true)   // locked circle A persists into pulley-B phase
  expect(p2.circleB).toBe(false)
  expect(await page.locator('#belt-hint').textContent()).toContain('pulley B')

  // Pick joint B + rim B → done: belt tube + BOTH locked circles shown, Create enabled.
  await setSel(page, 'belt-joint-b', 'PulleyB')
  await setSel(page, 'belt-conn-b', 'PulleyB_rim')
  const p3 = await probe(page)
  console.log('done phase:', JSON.stringify(p3))
  expect(p3.beltMeshes).toBeGreaterThanOrEqual(2)
  expect(p3.circleA).toBe(true)
  expect(p3.circleB).toBe(true)   // both circles shown until Create
  expect(await page.locator('#belt-create-btn').isDisabled()).toBe(false)
  await page.screenshot({ path: 'playwright-report/belt_preview.png' })

  // Create → persists, panel closes, all overlay circles cleared.
  await page.evaluate(() => document.getElementById('belt-create-btn').click())
  await page.waitForFunction(
    () => (window.__NADOC_DBG__.store.getState().currentAssembly?.belt_paths?.length ?? 0) === 1,
    null, { timeout: 10_000 })
  await expect(page.locator('#belt-path-panel')).toBeHidden({ timeout: 5_000 })
  const cleared = await probe(page)
  expect(cleared.circleA || cleared.circleB).toBe(false)
  const belt = await page.evaluate(() => window.__NADOC_DBG__.store.getState().currentAssembly.belt_paths[0])
  console.log('persisted:', JSON.stringify({ name: belt.name, rA: belt.pulley_a.radius, rB: belt.pulley_b.radius }))
  expect(belt.pulley_a.radius).toBeGreaterThan(0)
  expect(belt.pulley_b.radius).toBeGreaterThan(0)

  // ── Real-time coupling: rotate pulley A → pulley B follows at ratio rA/rB ──
  // (rA=3, rB=2 → 1.5; open belt, parallel same-direction axes → same sign).
  const coupled = await page.evaluate(async (b) => {
    const api = await import('/src/api/client.js')
    await api.patchAssemblyJoint(b.pulley_a.joint_id, { current_value: 1.0 })
    const js = window.__NADOC_DBG__.store.getState().currentAssembly.joints
    return js.find(j => j.id === b.pulley_b.joint_id).current_value
  }, belt)
  console.log('coupled jointB value after rotating jointA to 1.0:', coupled)
  expect(coupled).toBeCloseTo(1.5, 3)

  // ── Persistent path render + visibility toggle ──────────────────────────────
  // After Create (panel closed) the persistent belt tube is drawn.
  expect((await probe(page)).pathMeshes).toBeGreaterThanOrEqual(2)

  // Toggle hides it; toggle again restores it.
  await page.evaluate((id) => window.__NADOC_DBG__.toggleBeltVisibility(id), belt.id)
  expect((await probe(page)).pathMeshes).toBe(0)
  await page.evaluate((id) => window.__NADOC_DBG__.toggleBeltVisibility(id), belt.id)
  expect((await probe(page)).pathMeshes).toBeGreaterThanOrEqual(2)

  // While the define/edit panel is open, the persistent tube is suppressed
  // (the panel shows its own live preview instead).
  await page.evaluate(() => window.__NADOC_DBG__.beltPathPanel.open(
    window.__NADOC_DBG__.store.getState().currentAssembly.belt_paths[0]))
  expect((await probe(page)).pathMeshes).toBe(0)
  await page.evaluate(() => document.getElementById('belt-cancel-btn').click())
  await expect(page.locator('#belt-path-panel')).toBeHidden({ timeout: 5_000 })
  expect((await probe(page)).pathMeshes).toBeGreaterThanOrEqual(2)

  // ── Edit mode: open the stored belt → button says "Apply", prefilled, both circles ──
  await page.evaluate(() => window.__NADOC_DBG__.beltPathPanel.open(
    window.__NADOC_DBG__.store.getState().currentAssembly.belt_paths[0]))
  await expect(page.locator('#belt-path-panel')).toBeVisible({ timeout: 5_000 })
  expect(await page.locator('#belt-create-btn').textContent()).toBe('Apply')
  expect(await page.locator('#belt-joint-a').inputValue()).not.toBe('')
  expect(await page.locator('#belt-conn-a').inputValue()).not.toBe('')
  const pe = await probe(page)
  expect(pe.circleA && pe.circleB).toBe(true)

  // Cancel reverts — nothing changes on the backend.
  const idBefore = belt.id
  await page.evaluate(() => document.getElementById('belt-cancel-btn').click())
  await expect(page.locator('#belt-path-panel')).toBeHidden({ timeout: 5_000 })
  let bp = await page.evaluate(() => window.__NADOC_DBG__.store.getState().currentAssembly.belt_paths)
  expect(bp.length).toBe(1)
  expect(bp[0].id).toBe(idBefore)
  expect(bp[0].name).toBe('Belt')

  // Edit again → rename via Apply → PATCH persists (same id, no new belt).
  await page.evaluate(() => window.__NADOC_DBG__.beltPathPanel.open(
    window.__NADOC_DBG__.store.getState().currentAssembly.belt_paths[0]))
  await page.fill('#belt-name', 'RenamedBelt')
  await page.evaluate(() => document.getElementById('belt-create-btn').click())
  await page.waitForFunction(
    () => window.__NADOC_DBG__.store.getState().currentAssembly.belt_paths[0]?.name === 'RenamedBelt',
    null, { timeout: 10_000 })
  bp = await page.evaluate(() => window.__NADOC_DBG__.store.getState().currentAssembly.belt_paths)
  expect(bp.length).toBe(1)
  expect(bp[0].id).toBe(idBefore)
  console.log('edit applied:', JSON.stringify({ id: bp[0].id === idBefore, name: bp[0].name }))

  // ── Belt rider (Phase 1 attach): round-trip + detach ────────────────────────
  const rider = await page.evaluate(async (b) => {
    const api = await import('/src/api/client.js')
    await api.createBeltRider({
      belt_path_id: b.id, instance_id: b.pulley_b.instance_id,
      connector_label: 'PulleyB_rim', arc_param: 0.3,
      transform: { values: [1, 0, 0, 7, 0, 1, 0, 8, 0, 0, 1, 9, 0, 0, 0, 1] },
    })
    const a = window.__NADOC_DBG__.store.getState().currentAssembly
    return { count: a.belt_riders.length, arc: a.belt_riders[0]?.arc_param, id: a.belt_riders[0]?.id }
  }, belt)
  console.log('rider attached:', JSON.stringify(rider))
  expect(rider.count).toBe(1)
  expect(rider.arc).toBeCloseTo(0.3, 3)

  const afterDetach = await page.evaluate(async (rid) => {
    const api = await import('/src/api/client.js')
    await api.deleteBeltRider(rid)
    return window.__NADOC_DBG__.store.getState().currentAssembly.belt_riders.length
  }, rider.id)
  expect(afterDetach).toBe(0)

  // ── Phase 2: rotating a pulley drives the rider along the belt ───────────────
  // Attach a fixed (non-pulley) part as a rider so ONLY the rider logic moves it,
  // then rotate pulley A and confirm its live transform travels along the loop.
  const ride = await page.evaluate(async (b) => {
    const THREE = window.__NADOC_DBG__.THREE
    const G = await import('/src/scene/belt_geometry.js')
    const api = await import('/src/api/client.js')
    const D = window.__NADOC_DBG__
    const asm = D.store.getState().currentAssembly
    const jb = new Map(asm.joints.map(j => [j.id, j]))
    const ja = jb.get(b.pulley_a.joint_id)
    const cargo = asm.instances.find(i => i.fixed)            // an axle — not coupling-driven
    const local = new THREE.Matrix4()                         // identity → part sits on the belt frame
    await api.createBeltRider({
      belt_path_id: b.id, instance_id: cargo.id, arc_param: 0.1,
      ref_angle: ja.current_value ?? 0,
      local_transform: local.clone().transpose().toArray(),
      transform: { values: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1] },
    })
    const posOf = () => {
      const m = D.assemblyRenderer.getLiveTransform(cargo.id)
      return m ? new THREE.Vector3().setFromMatrixPosition(m).toArray() : null
    }
    const before = posOf()
    await api.patchAssemblyJoint(b.pulley_a.joint_id, { current_value: (ja.current_value ?? 0) + 0.6 })
    const after = posOf()
    return { before, after, moved: (before && after) ? new THREE.Vector3(...before).distanceTo(new THREE.Vector3(...after)) : 0 }
  }, belt)
  console.log('rider rode:', JSON.stringify(ride))
  expect(ride.before).not.toBe(null)
  expect(ride.moved).toBeGreaterThan(1.0)   // ~0.6 rad × rA(3) ≈ 1.8
})
