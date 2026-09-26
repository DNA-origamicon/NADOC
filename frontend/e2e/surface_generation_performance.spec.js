import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { existsSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const DOC = '__e2e__surface-generation'
const ROOT = fileURLToPath(new URL('../../', import.meta.url))
const ownedPaths = [`.session/${DOC}`, `.nadoc-projects/${DOC}`, `${DOC}.nadoc`]
  .map(path => `${ROOT}workspace/${path}`)
let fixture

test.beforeAll(() => {
  for (const path of ownedPaths) expect(existsSync(path)).toBe(false)
  fixture = JSON.parse(execFileSync('uv', ['run', 'python', '-c', `
import base64,json,subprocess,sys,types
from unittest.mock import patch
from tests.conftest import make_6hb_design
from backend.core import surface
from backend.core.oxdna_health import pack_surface_bin
from backend.api.routes_display_geometry import _build_design_surface_mesh
old=types.ModuleType('surface_browser_baseline');sys.modules[old.__name__]=old
exec(subprocess.check_output(['git','show','0dc8b857378b077a739289f413a23cfad3e234a3:backend/core/surface.py'],text=True),old.__dict__)
d=make_6hb_design(21);d.id='${DOC}';d.metadata.name='${DOC}'
out={'design':d.model_dump_json(),'surfaces':{}}
names=['compute_surface','compute_surface_from_cloud','smooth_mesh','cg_surface_mesh','compute_split_surfaces_from_cloud']
with patch.multiple(surface,**{n:getattr(old,n) for n in names}):
 for detail in ['coarse','chimerax']:
  m=_build_design_surface_mesh(d,.2,.28,1.3,15,detail)
  out['surfaces'][detail]=base64.b64encode(pack_surface_bin(old.surface_to_json(m,d))).decode()
print(json.dumps(out))
`], { cwd: ROOT, encoding: 'utf8', maxBuffer: 64 * 1024 * 1024 }))
})

test.afterEach(async ({ page, request }) => {
  try {
    await page.close()
    await request.delete(`${process.env.NADOC_E2E_API_BASE}/api/documents/${DOC}`)
  } finally {
    for (const path of ownedPaths) rmSync(path, { recursive: true, force: true })
    for (const path of ownedPaths) expect(existsSync(path)).toBe(false)
  }
})

test('standard and beautiful surfaces preserve every binary byte through the real UI', async ({ page }) => {
  test.setTimeout(120000)
  const errors = []
  page.on('pageerror', error => errors.push(error.message))
  page.on('console', msg => { if (msg.type() === 'error' && /WebGL|shader/i.test(msg.text())) errors.push(msg.text()) })
  await page.goto(`/?doc=${DOC}`)
  await page.waitForFunction(() => window.__nadocTest)
  await page.evaluate(async content => {
    const api = await import('/src/api/client.js')
    await api.importDesign(content)
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, fixture.design)
  const results = []
  for (const detail of ['coarse', 'chimerax', 'coarse']) {
    const response = page.waitForResponse(r => r.url().includes('/api/design/surface-bin?') && r.url().includes(`detail=${detail}`) && r.status() === 200)
    if (!results.length) await page.evaluate(() => window.__nadocTest.setRepresentation('surface'))
    else await page.evaluate(detail => {
      const cb = document.getElementById('cb-surface-figure-quality')
      cb.checked = detail === 'chimerax'
      cb.dispatchEvent(new Event('change', { bubbles: true }))
    }, detail)
    const bytes = await (await response).body()
    expect(bytes.equals(Buffer.from(fixture.surfaces[detail], 'base64'))).toBe(true)
    if (detail === 'chimerax') await expect(page.locator('#sl-surface-probe')).toBeDisabled()
    else await expect(page.locator('#sl-surface-probe')).toBeEnabled()
    // Verify that the returned triangles reached the real scene before rendering.
    await expect.poll(() => page.evaluate(() => {
      const m = window.__nadocTest.scene.getObjectByName('dna-surface')
      if (!m?.visible) return 0
      return (m.geometry.index?.count ?? m.geometry.attributes.position.count) / 3
    }), { timeout: 30000 }).toBe(bytes.readUInt32LE(8))
    await page.evaluate(() => window.__nadocTest.applyCameraPoseForTest({ position: [4, 4, 35], target: [4, 4, 3] }))
    const census = await page.evaluate(() => window.__nadocTest.renderedPixelCensus())
    expect(census.visible).toBeGreaterThan(100)
    expect(census.colorful).toBeGreaterThan(100)
    results.push({ detail, bytes: bytes.length, census })
  }
  expect(errors).toEqual([])
  console.log('SURFACE_GENERATION_APP', JSON.stringify(results))
})
