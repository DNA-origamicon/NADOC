import { test, expect } from '@playwright/test'

test('instanced spheres have hatched solid cuts and restore pixel-for-pixel', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
  // Exercise real WebGL without loading a document or starting application jobs.
  await page.route('**/section-view-test', route => route.fulfill({ contentType: 'text/html', body:
    '<div id="right-view-actions"><div class="ox-card__body"></div></div><canvas></canvas>' }))
  await page.goto('/section-view-test')
  const result = await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const { initSectionView } = await import('/src/scene/section_view.js')
    const renderer = new THREE.WebGLRenderer({ canvas: document.querySelector('canvas'), stencil: true })
    renderer.setSize(400, 300)
    renderer.setClearColor(0xffffff)
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(40, 4 / 3, 0.1, 100)
    camera.position.set(0, 0, 7)
    camera.lookAt(0, 0, 0)
    const material = new THREE.MeshBasicMaterial({ color: 0xdd4444 })
    const mesh = new THREE.InstancedMesh(new THREE.SphereGeometry(1, 32, 24), material, 2)
    mesh.setMatrixAt(0, new THREE.Matrix4().makeTranslation(-1.1, 0, 0))
    mesh.setMatrixAt(1, new THREE.Matrix4().makeTranslation(1.1, 0, 0))
    scene.add(mesh)
    const view = initSectionView({ scene, camera, renderer, controls: { target: new THREE.Vector3(), enabled: true },
      document, addFrameCallback() {}, removeFrameCallback() {} })
    function pixels() {
      renderer.render(scene, camera)
      const gl = renderer.getContext(), buffer = new Uint8Array(400 * 300 * 4)
      gl.readPixels(0, 0, 400, 300, gl.RGBA, gl.UNSIGNED_BYTE, buffer)
      return buffer
    }
    const baseline = pixels()
    document.getElementById('section-view-btn').click()
    const cut = pixels()
    // Count blue cap pixels and dark hatch pixels inside the left sphere,
    // away from the central transform gizmo.
    let blue = 0, hatch = 0
    for (let y = 120; y < 180; y++) for (let x = 100; x < 140; x++) {
      const i = (y * 400 + x) * 4
      if (cut[i + 2] > cut[i] + 10) blue++
      if (cut[i] < 180 && cut[i + 2] > cut[i]) hatch++
    }
    view.anchor.position.z = -3
    view.sync()
    const beyond = pixels()
    const center = (150 * 400 + 120) * 4
    document.getElementById('section-view-btn').click()
    const restored = pixels()
    const same = baseline.every((value, index) => restored[index] === value)
    view.dispose(); renderer.dispose()
    return { blue, hatch, beyond: Array.from(beyond.slice(center, center + 3)), same }
  })
  expect(errors).toEqual([])
  expect(result.blue).toBeGreaterThan(1500)
  expect(result.hatch).toBeGreaterThan(100)
  expect(result.beyond).toEqual([255, 255, 255])
  expect(result.same).toBe(true)
})

for (const kind of ['invisible picking mesh', 'open surface']) {
  test(`does not project hatch from an ${kind} onto empty section space`, async ({ page }) => {
    await page.route('**/section-view-test', route => route.fulfill({ contentType: 'text/html', body:
      '<div id="right-view-actions"><div class="ox-card__body"></div></div><canvas></canvas>' }))
    await page.goto('/section-view-test')
    const hatchPixels = await page.evaluate(async kind => {
      const THREE = await import('/node_modules/three/build/three.module.js')
      const { initSectionView } = await import('/src/scene/section_view.js')
      const renderer = new THREE.WebGLRenderer({ canvas: document.querySelector('canvas'), stencil: true })
      renderer.setSize(400, 300); renderer.setClearColor(0xffffff)
      const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(40, 4 / 3, 0.1, 100)
      camera.position.set(0, 0, 7); camera.lookAt(0, 0, 0)
      const solid = new THREE.Mesh(new THREE.SphereGeometry(0.6), new THREE.MeshBasicMaterial({ color: 0xdd4444 }))
      solid.position.x = -1.2; scene.add(solid)
      const stray = new THREE.Mesh(kind === 'open surface' ? new THREE.PlaneGeometry(1.3, 1.3) : new THREE.SphereGeometry(0.65),
        new THREE.MeshBasicMaterial({ color: 0xdd4444, transparent: true, opacity: kind === 'open surface' ? 1 : 0 }))
      stray.position.set(1.2, 0, kind === 'open surface' ? -1 : 0)
      scene.add(stray)
      const view = initSectionView({ scene, camera, renderer, controls: { target: new THREE.Vector3(), enabled: true },
        document, addFrameCallback() {}, removeFrameCallback() {} })
      view.setEnabled(true); view.anchor.position.set(0, 0, 0); view.sync()
      renderer.render(scene, camera)
      const gl = renderer.getContext(), pixels = new Uint8Array(400 * 300 * 4)
      gl.readPixels(0, 0, 400, 300, gl.RGBA, gl.UNSIGNED_BYTE, pixels)
      let hatch = 0
      for (let y = 125; y < 175; y++) for (let x = 255; x < 280; x++) {
        const i = (y * 400 + x) * 4
        if (pixels[i + 2] > pixels[i] + 10) hatch++
      }
      view.dispose(); renderer.dispose()
      return hatch
    }, kind)
    expect(hatchPixels).toBe(0)
  })
}

test('section panel edits the plane, steps values, hides the gizmo, and fits a narrow sidebar', async ({ page }) => {
  await page.route('**/section-view-test', route => route.fulfill({ contentType: 'text/html', body:
    '<style>body{background:#10161e;color:#ddd;font:13px sans-serif}#right-view-actions{width:260px}button{background:#202b38;color:#ddd;border:1px solid #425164;border-radius:4px}input{color:#fff}.ox-card__body{display:grid;grid-template-columns:1fr 1fr;gap:6px}</style><div id="right-view-actions"><h2>View Actions</h2><div class="ox-card__body"></div></div><canvas></canvas>' }))
  await page.goto('/section-view-test')
  await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const { initSectionView } = await import('/src/scene/section_view.js')
    const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(40, 1, 0.1, 100)
    camera.position.z = 7
    scene.add(new THREE.Mesh(new THREE.SphereGeometry(), new THREE.MeshBasicMaterial()))
    const renderer = new THREE.WebGLRenderer({ canvas: document.querySelector('canvas'), stencil: true })
    const view = initSectionView({ scene, camera, renderer, controls: { target: new THREE.Vector3(), enabled: true },
      document, addFrameCallback() {}, removeFrameCallback() {} })
    window.sectionTest = { view, scene, renderer }
  })
  const panel = page.locator('#section-view-controls')
  await expect(panel).toBeHidden()
  await page.getByRole('button', { name: 'Section view', exact: true }).click()
  await expect(panel).toBeVisible()
  const fieldStyle = await page.locator('#section-position-x').evaluate(input => {
    const style = getComputedStyle(input)
    return { color: style.color, background: style.backgroundColor, fontSize: style.fontSize }
  })
  expect(fieldStyle).toEqual({ color: 'rgb(255, 255, 255)', background: 'rgb(13, 17, 23)', fontSize: '13px' })
  for (const axis of ['X', 'Y', 'Z']) {
    const input = page.getByRole('spinbutton', { name: `Position ${axis} (nm)`, exact: true })
    await input.fill('3.25'); await input.press('Enter')
    await page.getByRole('button', { name: `Increase position ${axis} by 2 nm`, exact: true }).click()
    await expect(input).toHaveValue('5.25')
    await page.getByRole('button', { name: `Decrease position ${axis} by 2 nm`, exact: true }).click()
    await expect(input).toHaveValue('3.25')
    const rotation = page.getByRole('spinbutton', { name: `Rotation ${axis} (°)`, exact: true })
    await rotation.fill('20'); await rotation.press('Enter')
    await page.getByRole('button', { name: `Increase rotation ${axis} by 5 degrees`, exact: true }).click()
    await expect(rotation).toHaveValue('25')
    await page.getByRole('button', { name: `Decrease rotation ${axis} by 5 degrees`, exact: true }).click()
    await expect(rotation).toHaveValue('20')
  }
  const pose = await page.evaluate(() => ({
    position: window.sectionTest.view.anchor.position.toArray(),
    rotation: window.sectionTest.view.anchor.rotation.toArray().slice(0, 3),
    planeDistance: window.sectionTest.view.plane.distanceToPoint(window.sectionTest.view.anchor.position),
  }))
  expect(pose.position).toEqual([3.25, 3.25, 3.25])
  for (const angle of pose.rotation) expect(angle).toBeCloseTo(20 * Math.PI / 180)
  expect(pose.planeDistance).toBeCloseTo(0)
  await page.getByRole('checkbox', { name: 'Hide controls' }).check()
  expect(await page.evaluate(() => {
    const { scene, view } = window.sectionTest
    return { enabled: view.enabled, gizmo: scene.children.find(o => o.isTransformControlsRoot).visible }
  })).toEqual({ enabled: true, gizmo: false })
  await page.getByRole('button', { name: 'Increase position Z by 2 nm', exact: true }).click()
  await expect(page.locator('#section-position-z')).toHaveValue('5.25')
  await page.getByRole('checkbox', { name: 'Hide controls' }).uncheck()
  expect(await page.evaluate(() => window.sectionTest.scene.children.find(o => o.isTransformControlsRoot).visible)).toBe(true)
  // Changes made by the canvas gizmo also update the number boxes.
  await page.evaluate(() => { window.sectionTest.view.anchor.position.x = -7; window.sectionTest.view.sync() })
  await expect(page.locator('#section-position-x')).toHaveValue('-7')
  const fits = await panel.evaluate(element => {
    const bounds = element.getBoundingClientRect()
    return element.scrollWidth <= element.clientWidth && [...element.querySelectorAll('input,button')].every(child => {
      const rect = child.getBoundingClientRect()
      return rect.left >= bounds.left && rect.right <= bounds.right
    })
  })
  expect(fits).toBe(true)
  await page.getByRole('button', { name: 'Flip', exact: true }).click()
  await page.evaluate(() => { window.sectionTest.scene.children.find(o => o.isMesh).position.set(4, -2, 6) })
  await page.getByRole('button', { name: 'Reset', exact: true }).click()
  const resetPose = await page.evaluate(() => ({
    position: window.sectionTest.view.anchor.position.toArray(),
    quaternion: window.sectionTest.view.anchor.quaternion.toArray(),
    normal: window.sectionTest.view.plane.normal.toArray(),
  }))
  expect(resetPose.position).toEqual([4, -2, 6])
  expect(resetPose.normal[2]).toBeCloseTo(-1)
  await expect(page.locator('#section-rotation-x')).toHaveValue('180')
  await expect(page.locator('#section-rotation-y')).toHaveValue('0')
  await expect(page.locator('#section-rotation-z')).toHaveValue('0')
  await expect(page.locator('#section-position-x')).toHaveValue('4')
  await expect(page.locator('#section-position-y')).toHaveValue('-2')
  await expect(page.locator('#section-position-z')).toHaveValue('6')
  await expect(panel).toBeVisible()
  await page.getByRole('button', { name: 'Section view', exact: true }).click()
  await expect(panel).toBeHidden()
  await page.evaluate(() => { window.sectionTest.view.dispose(); window.sectionTest.renderer.dispose() })
})
