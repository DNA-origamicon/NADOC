import { expect } from '@playwright/test'

// Read rendered positions, then deliver actual mouse input. No topology writes
// through the automation facade or API. Keep the seed away from VR's [0..2] cells.
export const DESKTOP_VR_CELLS = [[0,5],[1,5],[1,6],[1,7],[0,7],[0,6]]
export async function paintDesktopVRSeed(page, testInfo) {
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.locator('.menu-item').filter({ hasText: 'Tools' }).first().hover()
  await page.click('#menu-tools-extrude')
  await expect(page.locator('#extrude-from')).toHaveValue('XY')
  for (const [index, [row, col]] of DESKTOP_VR_CELLS.entries()) {
    let cell
    await expect.poll(async () => {
      cell = await page.evaluate(([r,c]) => window.__nadocTest.getSliceCellScreenPositions()
        .find(p => p.row === r && p.col === c), [row,col])
      return !!cell
    }, {message:`rendered desktop cell ${row},${col}`}).toBe(true)
    await page.mouse.click(cell.x, cell.y)
    await expect(page.locator('#extrude-panel .ctx-count')).toHaveText(new RegExp(`^${index+1} hel`))
  }
  await page.fill('#slice-length', '42')
  await page.click('#slice-dir-fwd')
  await page.screenshot({path:testInfo.outputPath('desktop-seed-preview.png')})
  await page.click('#slice-extrude-btn')
  await expect.poll(() => page.evaluate(async () =>
    (await import('/src/state/store.js')).store.getState().currentDesign.helices.length)).toBe(6)
  const design = await page.evaluate(async () =>
    (await import('/src/state/store.js')).store.getState().currentDesign)
  expect(design.helices.map(h => h.grid_pos).sort()).toEqual([...DESKTOP_VR_CELLS].sort())
  expect(design.helices.every(h => h.length_bp === 42)).toBe(true)
  expect(design.lattice_frames).toHaveLength(1)
  expect(design.helices.every(h => h.lattice_frame_id === design.lattice_frames[0].id)).toBe(true)
  // Off-origin construction can leave the bundle under a sidebar. Use the normal
  // fit shortcut before reviewing pixels or entering VR.
  await page.locator('#canvas').click({position:{x:30,y:30}})
  await page.keyboard.press('f')
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await page.screenshot({path:testInfo.outputPath('desktop-seed-committed.png')})
  return design
}
