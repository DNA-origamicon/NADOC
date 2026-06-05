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
const HINGE = path.resolve(import.meta.dirname, '../../workspace/Hinge.nadoc')

async function loadHinge(page) {
  const fileMenu = page.locator('.menu-item').filter({ hasText: 'File' }).first()
  await fileMenu.hover()
  await page.click('#menu-file-new')
  await page.fill('#new-design-name', 'dsdna-link-sel-test')
  await page.getByRole('button', { name: 'Create', exact: true }).click()
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 10_000 })
  // Load into THIS tab's document: the in-tab api client auto-stamps
  // X-NADOC-Doc, so the design lands in the doc the tab is reading. A
  // default-doc `page.request.post` would load into a different document
  // (multi-doc) and the tab would still see the empty New-Part design.
  //
  // Hinge.nadoc ships overhangs OH1/OH2 but NO linker (the fixture lost its
  // bundled L1 ds linker), so build it in-tab to keep this spec
  // self-contained. The connection auto-names itself L1 (first linker).
  // _syncFromDesignResponse pulls the generated linker topology + geometry
  // into the store so the arc renderer can build the bridge meshes.
  await page.evaluate(async (hingePath) => {
    const api = await import('/src/api/client.js')
    await api.loadDesign(hingePath)
    const { store } = await import('/src/state/store.js')
    const oh = label => store.getState().currentDesign.overhangs.find(o => o.label === label)
    const resp = await api._request('POST', '/design/overhang-connections', {
      overhang_a_id: oh('OH1').id, overhang_a_attach: 'free_end',
      overhang_b_id: oh('OH2').id, overhang_b_attach: 'free_end',
      linker_type: 'ds', length_value: 7, length_unit: 'bp',
    })
    await api._syncFromDesignResponse(resp)
  }, HINGE)
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
  test.setTimeout(60_000)  // loadHinge builds the L1 linker in-tab; 30s is too tight under parallel workers
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
  test.setTimeout(60_000)  // loadHinge builds the L1 linker in-tab; 30s is too tight under parallel workers
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
  test.setTimeout(60_000)  // loadHinge builds the L1 linker in-tab; 30s is too tight under parallel workers
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
