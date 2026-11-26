import {test, expect} from '@playwright/test'

// No authored documents, downloads, or scratch beyond the configured reporter's
// automatically removed output. Every context closes its graphics resources.
for (const [backend, label, native = false] of [['webgl', 'WebGL'], ['webgpu', 'WebGPU'], ['optix', 'OptiX'], ['optix', 'OptiX', true]]) {
  test(`${label} ${native ? 'native connection' : 'module download'} failure appears in the Appearance export status`, async ({page}) => {
    await page.route('**/trace-error-fixture', r => r.fulfill({contentType: 'text/html', body: '<html><body></body></html>'}))
    const module = backend === 'webgl' ? 'engine' : backend
    await page.route(native ? '**/api/render/optix/session' : `**/src/scene/photo_renderer/path_trace_${module}.js`, r => r.abort('failed'))
    await page.goto('/trace-error-fixture')
    await page.evaluate(async backend => {
      const html = new DOMParser().parseFromString(await (await fetch('/')).text(), 'text/html')
      const panel = html.getElementById('photo-settings'); panel.disabled = false; document.body.append(panel)
      const THREE = await import('/node_modules/three/build/three.module.js')
      const {createPhotoMode} = await import('/src/scene/photo_mode.js')
      const {initPhotoPanel} = await import('/src/ui/photo_panel.js')
      const scene = new THREE.Scene(), camera = new THREE.PerspectiveCamera(), renderer = new THREE.WebGLRenderer()
      renderer.setSize(32, 32)
      const mode = createPhotoMode({scene, camera, renderer, setRenderFn(){}, resetRenderFn(){}, setResizeCallback(){}, clearResizeCallback(){}})
      const ui = initPhotoPanel(mode); mode.activate(); ui.onEnter()
      mode.setPathTracing(true); mode.setPathTraceExportBackend(backend)
      // Keep the real export-button handler, with a bounded image for this failure test.
      const render = mode.renderToBlob; mode.renderToBlob = () => render(32, 32)
      window.__traceCleanup = () => {ui.dispose(); mode.deactivate(); renderer.dispose()}
    }, backend)
    await page.locator('#photo-export-btn').click()
    await expect(page.locator('#photo-export-note')).toContainText(native ? 'OptiX connection failed while starting the native renderer' : `${label} export failed while loading the renderer`)
    await expect(page.locator('#photo-export-note')).toContainText(native ? 'backend is running' : 'Reload NADOC')
    await expect(page.locator('#photo-export-btn')).toBeEnabled()
    await page.evaluate(() => window.__traceCleanup())
  })
}
