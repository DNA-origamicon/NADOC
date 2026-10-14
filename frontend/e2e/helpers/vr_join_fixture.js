import { execFileSync } from 'node:child_process'
import path from 'node:path'

const root = path.resolve(import.meta.dirname, '../../..')

// The same scaffolded fixture and compatible pose used by desktop free Join.
// Generated in memory; never reads a saved user design or starts a simulation.
export function makeVRJoinFixture() {
  return JSON.parse(execFileSync(path.join(root, '.venv/bin/python'), ['-c', `
import json
from tests.test_cluster_join_api import make_join_design
from tests.test_cluster_join_core import request
from backend.core.cluster_join import propose_cluster_join
d=make_join_design(2,n_helices=12)
d.metadata.name='__e2e__VR Join'
joined,r=propose_cluster_join(d,request(d,kinds=('side','end'),gap=2))
posed=d.model_copy(deep=True)
posed.cluster_transforms=joined.cluster_transforms
print(json.dumps(dict(design=d.model_dump(mode='json'),posed=posed.model_dump(mode='json'),matrix=r['donor_world_delta'])))
`], { cwd: root, maxBuffer: 8 * 1024 * 1024 }).toString())
}

export async function importVRJoinFixture(page, fixture, doc, { physical = false } = {}) {
  await page.goto(`/?doc=${doc}&scrywrite=${physical ? 'transactions' : 'inspect'}`)
  await page.waitForFunction(() => !!window.__nadocTest?.scrywrite)
  await page.getByRole('button', { name: 'File', exact: true }).hover()
  await page.locator('#menu-file-new').click()
  await page.locator('#new-design-name').fill('__e2e__VR Join')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  // Preserve the new private document's destination across import/autosave.
  await page.waitForFunction(() => window.__nadocSyncDebug?.status().workspacePath?.startsWith('__e2e__'))
  await page.evaluate(async content => {
    const api = await import('/src/api/client.js')
    // Keep one owned project revision store when importing the generated shape.
    content.id = window.__nadocTest.store.getState().currentDesign.id
    content.metadata.identity_last_known_path = window.__nadocSyncDebug.status().workspacePath
    await api.importDesign(JSON.stringify(content))
    document.getElementById('welcome-screen')?.classList.add('hidden')
    window.__nadocTest.applyCameraPoseForTest({ position: [85, 65, 90], target: [10, 5, 18], up: [0, 0, 1] })
  }, fixture.design)
  await page.waitForFunction(() => window.__nadocTest.store.getState().currentGeometry?.length > 0)
}
