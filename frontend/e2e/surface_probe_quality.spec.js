import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { existsSync, rmSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const DOC = '__e2e__surface-probe'
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
 for detail,radius in [('coarse',.28),('chimerax',.14),('chimerax',.24),('chimerax',.10)]:
  m=_build_design_surface_mesh(d,.2,radius,1.3,15,detail)
  out['surfaces'][f'{detail}-{radius:.2f}']=base64.b64encode(pack_surface_bin(old.surface_to_json(m,d))).decode()
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

test('figure quality permits probe changes and restores each preset radius', async ({ page }) => {
  test.setTimeout(180000)
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
  for (const [detail,radius] of [['coarse',.28],['chimerax',.14],['chimerax',.24],['chimerax',.10],['chimerax',.14],['coarse',.28]]) {
    const response = page.waitForResponse(r => r.url().includes('/api/design/surface-bin?') && r.url().includes(`detail=${detail}`) && r.status() === 200)
    if (!results.length) await page.evaluate(() => window.__nadocTest.setRepresentation('surface'))
    else await page.evaluate(({detail,radius}) => {
      const selected = document.getElementById('menu-view-surface-detail').classList.contains('is-checked')
      if(selected !== (detail === 'chimerax')) {
        document.getElementById(detail === 'chimerax' ? 'menu-view-surface-detail' : 'menu-view-surface').click()
      } else {
        const probe = document.getElementById('sl-surface-probe')
        probe.value=String(radius); probe.dispatchEvent(new Event('input',{bubbles:true}));probe.dispatchEvent(new Event('change',{bubbles:true}))
      }
    }, {detail,radius})
    const bytes = await (await response).body()
    expect(bytes.equals(Buffer.from(fixture.surfaces[`${detail}-${radius.toFixed(2)}`], 'base64'))).toBe(true)
    await expect(page.locator('#sl-surface-probe')).toBeEnabled()
    await expect(page.locator('#sl-surface-probe')).toHaveValue(String(radius))
    await expect(page.locator('#cb-surface-smooth-eight')).toHaveCount(0)
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
    results.push({ detail, radius, bytes: bytes.length, census })
  }
  expect(results[1].census.pixelHash).toBe(results[4].census.pixelHash)
  expect(results[1].census.pixelHash).not.toBe(results[2].census.pixelHash)
  expect(errors).toEqual([])
  console.log('SURFACE_GENERATION_APP', JSON.stringify(results))
})
