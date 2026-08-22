import { test, expect } from '@playwright/test'
import { createShort6hbPlateFixture, readPlateLayout } from './helpers/plate_fixture.js'

const idsOf = items => items.map(x => x.strand_id).sort()

async function expectTubeIds(page, API, headers, expected) {
  await expect.poll(async () => idsOf((await readPlateLayout(page, API, headers)).tubes))
    .toEqual([...expected].sort())
}

async function rightClickWell(page, API, headers, strandId) {
  const layout = await readPlateLayout(page, API, headers)
  const well = layout.wells.find(w => w.strand_id === strandId)
  expect(well, `${strandId} is not in a plate`).toBeTruthy()
  const box = await page.locator('#plate-canvas').boundingBox()
  expect(box).toBeTruthy()

  // Mirror plate_view.resetView's one-plate fit and physical A-H / 1-12 grid.
  const rows = layout.orientation === '12x8' ? 12 : 8
  const cols = layout.orientation === '12x8' ? 8 : 12
  const worldW = 22 + cols * 30 + (layout.orientation === '12x8' ? 22 : 14)
  const worldH = layout.plate_count * (20 + 20 + rows * 30) + (layout.plate_count - 1) * 36
  const zoom = Math.max(0.15, Math.min(4, (box.width - 32) / worldW, (box.height - 32) / worldH))
  const panX = (box.width - worldW * zoom) / 2
  const screen = layout.orientation === '12x8'
    ? { row: well.col, col: 7 - well.row }
    : { row: well.row, col: well.col }
  const plateTop = well.plate * (20 + 20 + rows * 30 + 36)
  const x = box.x + panX + (22 + screen.col * 30 + 15) * zoom
  const y = box.y + 16 + (plateTop + 20 + 20 + screen.row * 30 + 15) * zoom
  await page.mouse.click(x, y, { button: 'right' })
  await expect(page.locator('.context-menu__item')).toHaveText('Send to tubes')
  await page.locator('.context-menu__item').click()
}

async function sendTubeBack(page, strandId) {
  const row = page.locator(`#plate-tubes [data-strand-id="${strandId}"]`)
  await expect(row).toBeVisible()
  await row.click({ button: 'right' })
  await expect(page.locator('.context-menu__item')).toHaveText('Send to plates')
  await page.locator('.context-menu__item').click()
}

test('short 6HB round-trips strand, color, and group through wells and tubes', async ({ page }, testInfo) => {
  const doc = `e2e-plate-tube-roundtrip-${testInfo.repeatEachIndex}-${testInfo.workerIndex}`
  const { API, headers, ids } = await createShort6hbPlateFixture(page, doc)
  await expect(page.locator('#welcome-screen')).not.toBeVisible({ timeout: 20_000 })
  await page.locator('.left-tab-btn[data-tab="plates"]').click()
  await expect(page.locator('#tab-content-plates')).toBeVisible()
  await page.getByRole('button', { name: 'Auto-fill' }).click()
  await expect.poll(async () => (await readPlateLayout(page, API, headers))?.wells?.length || 0)
    .toBeGreaterThan(2)

  // Staple mode: exactly one identity crosses each boundary and returns.
  await rightClickWell(page, API, headers, ids[0])
  await expectTubeIds(page, API, headers, [ids[0]])
  await expect(page.locator('#plate-tubes .plate-tubes-scroll')).toBeVisible()

  // Send-to-tubes is one undo step and one redo step; the visible tube list
  // follows the restored backend layout rather than staying stale.
  await page.keyboard.press('Control+Z')
  await expectTubeIds(page, API, headers, [])
  await expect(page.locator(`#plate-tubes [data-strand-id="${ids[0]}"]`)).toHaveCount(0)
  await page.keyboard.press('Control+Y')
  await expectTubeIds(page, API, headers, [ids[0]])
  await expect(page.locator(`#plate-tubes [data-strand-id="${ids[0]}"]`)).toBeVisible()

  await sendTubeBack(page, ids[0])
  await expectTubeIds(page, API, headers, [])

  // Send-to-plates is independently undoable and redoable too.
  await page.keyboard.press('Control+Z')
  await expectTubeIds(page, API, headers, [ids[0]])
  await expect(page.locator(`#plate-tubes [data-strand-id="${ids[0]}"]`)).toBeVisible()
  await page.keyboard.press('Control+Y')
  await expectTubeIds(page, API, headers, [])
  await expect(page.locator(`#plate-tubes [data-strand-id="${ids[0]}"]`)).toHaveCount(0)

  // Color mode: ids 0+1 share red, while id 2 is deliberately a different color.
  await page.getByRole('button', { name: 'Mode: Staple' }).click()
  await rightClickWell(page, API, headers, ids[0])
  await expectTubeIds(page, API, headers, ids.slice(0, 2))
  const colorRows = page.locator('#plate-tubes [data-color="#f01234"]')
  await expect(colorRows).toHaveCount(2)
  await sendTubeBack(page, ids[0])
  await expectTubeIds(page, API, headers, [])

  // Group mode: group-A is ids 0+2, proving this is not accidentally color-based.
  await page.getByRole('button', { name: 'Mode: Color' }).click()
  await rightClickWell(page, API, headers, ids[0])
  await expectTubeIds(page, API, headers, [ids[0], ids[2]])
  await expect(page.locator('#plate-tubes [data-group-id="group-A"]')).toHaveCount(2)
  await sendTubeBack(page, ids[0])
  await expectTubeIds(page, API, headers, [])

  const final = await readPlateLayout(page, API, headers)
  expect(new Set(final.wells.map(w => w.strand_id)).size).toBe(final.wells.length)
  expect(final.wells.some(w => w.strand_id === ids[0])).toBe(true)
  expect(final.wells.some(w => w.strand_id === ids[1])).toBe(true)
  expect(final.wells.some(w => w.strand_id === ids[2])).toBe(true)
})
