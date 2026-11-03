import { test, expect } from '@playwright/test'

test('deselecting a connection version removes the rendered cyan and magenta glows', async ({ page }) => {
  // Isolate the panel and real WebGL glow renderer from user documents and
  // camera framing. Two known bead positions make both colours observable.
  await page.route('**/__connection-glow-test', route => route.fulfill({
    contentType: 'text/html', body: '<html><body style="margin:0"></body></html>',
  }))
  await page.goto('/__connection-glow-test')
  await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const { createGlowLayer } = await import('/src/scene/glow_layer.js')
    const { initOverhangConnectionsPanel } = await import('/src/ui/overhang_connections_panel.js')
    const { createSelectionController } = await import('/src/scene/selection_controller.js')
    const { store } = await import('/src/state/store.js')
    const { mountIds } = await import('/src/test-helpers/factory_dom.js')
    mountIds({
      'oconn-heading': 'h2', 'oconn-arrow': 'span', 'oconn-body': 'div',
      'oconn-select-a': 'select', 'oconn-select-b': 'select',
      'oconn-button-box': 'button', 'oconn-length-row': 'div', 'oconn-length': 'input',
      'oconn-generate': 'button', 'oconn-list': 'div', 'oconn-popover': 'div',
    })
    const a = 'ovhg_h1_5_5p', b = 'ovhg_h2_9_3p'
    store.setState({ currentDesign: {
      overhangs: [{ id: a }, { id: b }], strands: [],
      connection_versions: [{ id: 'v1', name: 'V1', overhang_a_id: a, overhang_b_id: b,
        connection_type: 'root-to-root-ssdna-linker', applied: false }],
    } })
    const scene = new THREE.Scene()
    const camera = new THREE.OrthographicCamera(-10, 10, 5, -5, 0.1, 100)
    camera.position.z = 20
    const renderer = new THREE.WebGLRenderer({ preserveDrawingBuffer: true })
    renderer.setSize(400, 200)
    renderer.domElement.id = 'glow-canvas'
    document.body.appendChild(renderer.domElement)
    initOverhangConnectionsPanel({ store, scene, createGlowLayer,
      designRenderer: { getBackboneEntries: () => [
        { nuc: { overhang_id: a }, pos: { x: -4, y: 0, z: 0 } },
        { nuc: { overhang_id: b }, pos: { x: 4, y: 0, z: 0 } },
      ] },
    })
    document.getElementById('oconn-heading').click()
    const selection = createSelectionController({ store })
    renderer.domElement.addEventListener('click', () => selection.clear())
    window.glowPixels = () => {
      renderer.render(scene, camera)
      const gl = renderer.getContext()
      return [120, 280].map(x => {
        const pixel = new Uint8Array(4)
        gl.readPixels(x, 100, 1, 1, gl.RGBA, gl.UNSIGNED_BYTE, pixel)
        return [...pixel].slice(0, 3)
      })
    }
    window.redrawGlow = () => {
      store.setState({ currentGeometry: [] })
      store.setState({ currentDesign: { ...store.getState().currentDesign } })
    }
    document.getElementById('oconn-list').style.paddingBottom = '30px'
  })

  for (const surface of ['scene', 'sidebar']) {
    await page.locator('.oconn-version-row').click()
    const [cyan, magenta] = await page.evaluate(() => window.glowPixels())
    expect(cyan[1]).toBeGreaterThan(30)
    expect(cyan[2]).toBeGreaterThan(30)
    expect(magenta[0]).toBeGreaterThan(30)
    expect(magenta[2]).toBeGreaterThan(30)
    if (surface === 'scene') await page.locator('#glow-canvas').click({ position: { x: 5, y: 5 } })
    else {
      const box = await page.locator('#oconn-list').boundingBox()
      await page.mouse.click(box.x + 5, box.y + box.height - 5)
    }
    await expect(page.locator('.oconn-version-row.is-selected')).toHaveCount(0)
    expect(await page.evaluate(() => window.glowPixels())).toEqual([[0, 0, 0], [0, 0, 0]])
    await page.evaluate(() => window.redrawGlow())
    expect(await page.evaluate(() => window.glowPixels())).toEqual([[0, 0, 0], [0, 0, 0]])
  }
})
