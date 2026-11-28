import { test, expect } from '@playwright/test'

// Isolated launcher owns every workspace/autosave, store, browser profile, cache
// and output under NADOC_HISTORY_E2E_ROOT and removes it in finally. No downloads,
// screenshots, traces or videos; source construction uses native recorded commands.
test.skip(!process.env.NADOC_HISTORY_E2E_ROOT, 'Requires isolated launcher')

test('assembly atomistic color switches repaint spheres and sticks', async ({ page, request }) => {
  const doc = '__e2e__assembly-atom-colors', errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', message => { if (message.type() === 'error' && /THREE|shader|WebGL/i.test(message.text())) errors.push(message.text()) })
  await page.goto(`/?doc=${doc}`, { waitUntil: 'domcontentloaded' })
  await page.waitForFunction(() => !!window.__NADOC_DBG__?.scene)
  const response = await request.post('http://127.0.0.1:8004/api/design/bundle', {
    headers: { 'X-NADOC-Doc': `${doc}-source` }, data: { cells: [[0, 0]], length_bp: 21 },
  })
  expect(response.ok()).toBe(true)
  const source = (await response.json()).design
  page.once('dialog', dialog => dialog.accept(doc))
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await page.locator('#menu-file-new-assembly').click()
  await page.mouse.click(900, 450)
  await page.waitForFunction(() => window.__NADOC_DBG__.store.getState().assemblyActive)
  await page.evaluate(async design => {
    const api = await import('/src/api/client.js')
    if (!await api.addInstance({ name: '__e2e__colored-part', source: { type: 'inline', design } })) throw new Error('Add failed')
    const id = window.__NADOC_DBG__.store.getState().currentAssembly.instances[0].id
    if (!await api.patchInstance(id, { representation: 'ballstick' })) throw new Error('Ballstick failed')
  }, source)
  await page.waitForFunction(() => !!window.__NADOC_DBG__.scene.getObjectByName('atomBond_shared'))
  const original = await page.evaluate(() => JSON.stringify(window.__NADOC_DBG__.store.getState().currentAssembly.instances[0].source))
  async function color(mode) {
    await page.locator('.menu-item').filter({ hasText: 'View', exact: true }).first().hover()
    // Use the app's ordinary menu action, including its supported-mode guard.
    await page.locator(`#menu-view-coloring-${mode}`).evaluate(button => {
      if (button.disabled) throw new Error('Color mode disabled')
      button.click()
    })
    await page.waitForFunction(mode => window.__NADOC_DBG__.store.getState().coloringMode === mode, mode)
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
    return page.evaluate(() => {
      const { scene, THREE } = window.__NADOC_DBG__
      const read = name => {
        const mesh = scene.getObjectByName(name)
        if (!mesh) return null
        const shader = { uniforms: {}, vertexShader: THREE.ShaderLib.phong.vertexShader, fragmentShader: THREE.ShaderLib.phong.fragmentShader }
        mesh.material.onBeforeCompile(shader)
        const texture = shader.uniforms.u_atomColor?.value ?? shader.uniforms.u_segColor.value
        return Array.from(texture.image.data.slice(0, 80))
      }
      return { atoms: read('atomImpostor_C'), bonds: read('atomBond_shared'), expectedCarbon: new THREE.Color(0x505050).toArray() }
    })
  }
  const cpk = await color('cpk')
  expect(cpk.atoms.slice(0, 3)).toEqual(cpk.expectedCarbon.map(Math.fround))
  const strand = await color('strand')
  expect(strand.atoms).not.toEqual(cpk.atoms)
  expect(strand.bonds).not.toEqual(cpk.bonds)
  expect((await color('cpk')).bonds).toEqual(cpk.bonds)
  await color('base')
  await color('cluster')
  await color('source')
  await page.evaluate(async () => {
    const api = await import('/src/api/client.js')
    const id = window.__NADOC_DBG__.store.getState().currentAssembly.instances[0].id
    if (!await api.patchInstance(id, { representation: 'stick' })) throw new Error('Stick failed')
  })
  await page.waitForFunction(() => !window.__NADOC_DBG__.scene.getObjectByName('atomImpostor_C') && !!window.__NADOC_DBG__.scene.getObjectByName('atomBond_shared'))
  expect((await color('cpk')).bonds).toEqual(cpk.bonds)
  expect((await color('strand')).bonds).toEqual(strand.bonds)
  expect(await page.evaluate(() => JSON.stringify(window.__NADOC_DBG__.store.getState().currentAssembly.instances[0].source))).toBe(original)
  expect(errors).toEqual([])
})
