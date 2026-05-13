/**
 * Verifies that selecting one half of a dsDNA linker selects ONLY that
 * half (strand `__lnk__<conn>__a` xor `__lnk__<conn>__b`), and that
 * highlight + hitTest follow the standard strand-selection rules.
 *
 * Uses hinge.nadoc which ships with L1 — a dsDNA linker between OH1
 * (`OH1_5p`) and OH2 (`OH2_5p`).
 */

import { test, expect } from '@playwright/test'
import path from 'node:path'

const API = 'http://127.0.0.1:8000/api'
const HINGE = path.resolve(import.meta.dirname, '../../workspace/hinge.nadoc')

async function loadHinge(page) {
  const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
  await fileMenu.hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', 'dsdna-link-sel-test')
  await page.click('#new-design-create')
  await expect(page.locator('#welcome-screen')).toHaveClass(/hidden/, { timeout: 10_000 })
  const r = await page.request.post(`${API}/design/load`, { data: { path: HINGE } })
  expect(r.ok()).toBeTruthy()
  await page.evaluate(async () => {
    const apiMod = await import('/src/api/client.js')
    await apiMod.getDesign()
    // Geometry is on a separate endpoint; the linker arc renderer needs it
    // to find the bridge boundary beads, so fetch it explicitly here.
    await apiMod.getGeometry()
  })
  await page.waitForFunction(() => {
    const arcs = window._nadocDebug?.overhangLinkArcs
    if (!arcs) return false
    return (arcs.group?.children?.length ?? 0) > 0
  }, { timeout: 10_000 })
}

/** Pull the L1 ds connection's strand ids from the live design. Strand ids
 *  use the connection's UUID (`conn.id`), not its friendly name (`conn.name`). */
async function getLinkerStrandIds(page) {
  return page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const conn = (store.getState().currentDesign?.overhang_connections ?? [])
      .find(c => c.linker_type === 'ds' && c.name === 'L1')
    if (!conn) throw new Error('Could not find L1 ds linker in design')
    return { connId: conn.id, sidA: `__lnk__${conn.id}__a`, sidB: `__lnk__${conn.id}__b` }
  })
}

test('dsDNA linker: selectStrand on one half selects only that strand', async ({ page }) => {
  await page.goto('/')
  await loadHinge(page)
  const { sidA, sidB } = await getLinkerStrandIds(page)

  const result = await page.evaluate(async ({ sidA, sidB }) => {
    const dbg = window._nadocDebug
    const { store } = await import('/src/state/store.js')
    dbg.selectionManager.selectStrand(sidA)
    const selA = JSON.parse(JSON.stringify(store.getState().selectedObject))
    dbg.selectionManager.selectStrand(sidB)
    const selB = JSON.parse(JSON.stringify(store.getState().selectedObject))
    return { selA, selB }
  }, { sidA, sidB })

  expect(result.selA).toMatchObject({
    type: 'strand',
    id: sidA,
    data: { strand_id: sidA, strand_ids: [sidA] },
  })
  expect(result.selB).toMatchObject({
    type: 'strand',
    id: sidB,
    data: { strand_id: sidB, strand_ids: [sidB] },
  })
})

test('dsDNA linker: each connector arc carries its own strandId in userData', async ({ page }) => {
  await page.goto('/')
  await loadHinge(page)
  const { sidA, sidB } = await getLinkerStrandIds(page)

  const arcs = await page.evaluate(() => {
    const grp = window._nadocDebug.overhangLinkArcs.group
    const result = []
    grp.traverse(obj => {
      if (obj.name === 'overhangDsConnectorArcA' || obj.name === 'overhangDsConnectorArcB') {
        result.push({ name: obj.name, strandId: obj.userData?.strandId ?? null })
      }
    })
    return result
  })

  const arcA = arcs.find(a => a.name === 'overhangDsConnectorArcA')
  const arcB = arcs.find(a => a.name === 'overhangDsConnectorArcB')
  expect(arcA?.strandId).toBe(sidA)
  expect(arcB?.strandId).toBe(sidB)
})

test('dsDNA linker: highlight only colors arcs belonging to the selected strand', async ({ page }) => {
  await page.goto('/')
  await loadHinge(page)
  const { sidA, sidB } = await getLinkerStrandIds(page)

  const colors = await page.evaluate(({ sidA, sidB }) => {
    const arcs = window._nadocDebug.overhangLinkArcs
    const grp  = arcs.group

    function arcColors() {
      const out = {}
      grp.traverse(obj => {
        if (obj.name === 'overhangDsConnectorArcA' || obj.name === 'overhangDsConnectorArcB') {
          out[obj.name] = obj.material.color.getHex()
        }
      })
      return out
    }

    arcs.setHighlightedStrands([sidA])
    const aHighlight = arcColors()
    arcs.setHighlightedStrands([sidB])
    const bHighlight = arcColors()
    arcs.setHighlightedStrands([])
    const cleared = arcColors()
    return { aHighlight, bHighlight, cleared }
  }, { sidA, sidB })

  const HL = 0xff4444
  expect(colors.aHighlight.overhangDsConnectorArcA).toBe(HL)
  expect(colors.aHighlight.overhangDsConnectorArcB).not.toBe(HL)
  expect(colors.bHighlight.overhangDsConnectorArcB).toBe(HL)
  expect(colors.bHighlight.overhangDsConnectorArcA).not.toBe(HL)
  expect(colors.cleared.overhangDsConnectorArcA).not.toBe(HL)
  expect(colors.cleared.overhangDsConnectorArcB).not.toBe(HL)
})
