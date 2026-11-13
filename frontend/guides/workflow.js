import { expect } from '@playwright/test'
import { readFile, readdir } from 'node:fs/promises'
import path from 'node:path'
import { DEFAULT_GUIDE_MODEL, guideCells } from './model.js'

export const designState = page => page.evaluate(async () => (await import('/src/state/store.js')).store.getState().currentDesign)
export const selectedCells = page => page.evaluate(() => window.SLICE.getSelectedCells())

export async function existingMaterialOpacity(page) {
  return page.evaluate(() => {
    const values = []
    window.__NADOC_DBG__.designRenderer.getHelixCtrl()?.root.traverse(object => {
      for (const material of (Array.isArray(object.material) ? object.material : [object.material])) {
        if (material) values.push(material.opacity * (material.customProgramCacheKey().endsWith('|nadoc-authoring-opacity') ? .15 : 1))
      }
    })
    return Math.max(...values)
  })
}

export async function openExtrude(page, guide) {
  await page.locator('.menu-item').filter({ hasText: 'Tools' }).first().hover()
  await guide.click(page.locator('#menu-tools-extrude'), 'Open Tools → Extrude to start a new extrusion.')
  await expect(page.locator('#extrude-panel')).toBeVisible()
}

export async function selectFootprint(page, guide, explain = true, cells = guideCells()) {
  await page.waitForFunction(() => !document.querySelector('[data-camera-transition="true"]'))
  await page.mouse.move(1350, 800)
  let points
  await expect.poll(async () => {
    points = await page.evaluate(cells => {
      const visible = window.__nadocTest.getSliceCellScreenPositions()
      return cells.map(([r, c]) => visible.find(p => p.row === r && p.col === c))
    }, cells)
    return points.every(Boolean)
  }).toBe(true)
  expect(points.every(Boolean), 'All 18 footprint cells must be visible').toBe(true)
  for (const point of points) expect(await page.evaluate(p => document.elementFromPoint(p.x, p.y)?.id, point)).toBe('canvas')
  if (explain) {
    await guide.clickPoint(points[0], 'Click a cell to select it. Click the same cell again to deselect it.')
    await expect.poll(() => selectedCells(page)).toHaveLength(1)
    await page.mouse.click(points[0].x, points[0].y)
    await expect.poll(() => selectedCells(page)).toHaveLength(0)
  }
  // Box-select the 3×6 footprint through normal canvas input.
  await page.locator('#canvas').press('Tab')
  const margin = Math.abs(points[1].x - points[0].x) * 0.48
  const start = { x: Math.min(...points.map(p => p.x)) - margin, y: Math.min(...points.map(p => p.y)) - margin }
  const end = { x: Math.max(...points.map(p => p.x)) + margin, y: Math.max(...points.map(p => p.y)) + margin }
  await guide.capture('With the canvas focused, press Tab for box selection. Left-drag from upper left to lower right, enclosing the entire circles of the 3-row × 6-column footprint. Left-to-right requires full enclosure; right-to-left selects touching cells.', { ...start, end })
  await page.mouse.move(start.x, start.y)
  await page.mouse.down()
  await page.mouse.move(end.x, end.y, { steps: 20 })
  await page.mouse.up()
  await expect.poll(async () => (await selectedCells(page)).map(c => c.join(',')).sort()).toEqual(cells.map(c => c.join(',')).sort())
  await page.locator('#canvas').press('Tab')
  await guide.capture('The count must read 18 helices. Tab returns to ordinary cell picking; a left-drag can also paint cells along its path.')
}

export async function fitOblique(page) {
  await page.locator('#canvas').press('f')
  await page.mouse.move(1150, 650)
  await page.mouse.down({ button: 'right' })
  await page.mouse.move(1300, 720, { steps: 20 })
  await page.mouse.up({ button: 'right' })
  await page.locator('#canvas').press('f')
  await page.mouse.move(1100, 650)
  await page.mouse.wheel(0, 60)
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
}

export async function endMenu(page, guide, action) {
  await page.locator('#canvas').press('f')
  await page.mouse.move(1100, 650)
  await page.mouse.wheel(0, 100)
  const toggle = page.locator('#view-tools [data-key="blunt"]')
  if (!(await toggle.getAttribute('class')).includes('active')) {
    await guide.click(toggle, 'Enable BLUNT in the toolbar to show selectable end rings.')
  }
  let end
  await expect.poll(async () => {
    end = await page.evaluate(() => window.__nadocTest.getDomainEndScreenPositions()
      .filter(p => p.openSide === 1 && document.elementFromPoint(p.x, p.y)?.id === 'canvas')
      .sort((a, b) => b.x - a.x)[0])
    return !!end
  }).toBe(true)
  await guide.clickPoint(end, `Right-click the marked far-end ring, then choose ${action === 'bend' ? 'Bend' : 'Extrude'} from its menu.`, { button: 'right' })
  await guide.click(page.locator(`#blunt-${action}-btn-ctx`), `Choose ${action === 'bend' ? 'Bend to open the bend controls' : 'Extrude to continue from this end'}.`)
  return end
}

export async function continueEnd(page, guide) {
  const before = await designState(page)
  await endMenu(page, guide, 'extrude')
  await expect(page.locator('#extrude-from')).toBeDisabled()
  await expect.poll(() => existingMaterialOpacity(page)).toBeLessThanOrEqual(0.15)
  await guide.pointAt(page.locator('#extrude-from'), 'From is locked to the selected source end. The tool chooses the initial direction away from the existing body.')
  const cells = guideCells().filter(([r, c]) => r < 2 && c <= 3)
  for (const coords of cells) {
    let cell
    await expect.poll(async () => {
      cell = await page.evaluate(([r, c]) => window.__nadocTest.getSliceCellScreenPositions().find(p => p.row === r && p.col === c), coords)
      return !!cell && cell.state === 'continuable'
    }).toBe(true)
    expect(await page.evaluate(p => document.elementFromPoint(p.x, p.y)?.id, cell)).toBe('canvas')
    await page.mouse.click(cell.x, cell.y)
  }
  await expect.poll(() => selectedCells(page)).toHaveLength(6)
  await guide.capture('Select two rows × three columns of amber cells: six compatible ends for the continuation.')
  await guide.click(page.locator('#extrude-next'), 'Click Next to keep the selected end and inspect the continuation in 3D.')
  await page.locator('#slice-length').fill('8')
  await guide.click(page.locator('#slice-extrude-btn'), 'With 8 bp, Both and Ligate adjacent selected, apply the continuation.')
  await expect.poll(async () => (await designState(page)).feature_log.length).toBe(before.feature_log.length + 1)
  expect((await designState(page)).feature_log.at(-1).op_kind).toBe('extrude-continuation')
  await expect.poll(() => existingMaterialOpacity(page)).toBeGreaterThan(0.15)
  await page.locator('#canvas').press('f')
  await page.mouse.move(1100, 650)
  await page.mouse.wheel(0, 60)
  await guide.capture('The selected 2×3 cross-section is now 8 bp longer.')
}


export async function createSquarePart(page, guide, name) {
  await page.goto(`/?doc=__e2e__${name}-guide`)
  await expect(page.locator('#canvas')).toBeVisible()
  await page.locator('.menu-item').filter({ hasText: 'File' }).first().hover()
  await guide.click(page.locator('#menu-file-new'), 'Choose File → New.')
  await page.locator('#new-design-name').fill(`__e2e__${name} 3x6 square guide`)
  await guide.click(page.locator('input[name="new-lattice-type"][value="SQUARE"]'), 'Choose Square for the lattice type. The guide uses a temporary example name; use a meaningful name for your own part.')
  await guide.click(page.getByRole('button', { name: 'Create', exact: true }), 'Click Create to open the empty square-lattice part.')
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  expect((await designState(page)).lattice_type).toBe(DEFAULT_GUIDE_MODEL.lattice)
  await expect(page.locator('#menu-view-detail-full')).toHaveClass(/is-checked/)
  await guide.capture('Use Full representation throughout this guide. Full shows the nucleotide beads and base slabs; it is the standard display for guides.')

}

// Preparation still uses real editor input, even when it is not a lesson chapter.
export const preparation = {
  capture: async () => {}, pointAt: async () => {},
  click: async locator => locator.click(),
  clickPoint: async () => { throw new Error('Preparation requires explicit canvas input') },
}
export async function verifySavedExample(page, commands, helices = 18) {
  await expect.poll(async () => {
    const files = (await readdir(process.env.NADOC_WORKSPACE)).filter(f => f.startsWith('__e2e__') && f.endsWith('.nadoc'))
    if (files.length !== 1) return false
    const saved = JSON.parse(await readFile(path.join(process.env.NADOC_WORKSPACE, files[0]), 'utf8'))
    return saved.lattice_type === 'SQUARE' && saved.helices.length === helices && saved.feature_log.length === commands
  }).toBe(true)
}

export const secondFootprint = () => guideCells().map(([r, c]) => [r + 5, c])

export async function addSeparateCluster(page, guide, length) {
  const before = await designState(page)
  await openExtrude(page, guide)
  await page.locator('#extrude-from').selectOption('XY')
  await selectFootprint(page, guide, false, secondFootprint())
  await guide.capture('Select another 3×6 footprint a few empty rows away from the existing bundle.')
  await guide.click(page.locator('#extrude-next'), 'Click Next to preview the separate extrusion.')
  await page.locator('#slice-length').fill(String(length))
  await guide.click(page.locator('#slice-extrude-btn'), `Enter ${length} bp and click Extrude to create the second cluster.`)
  await expect.poll(async () => (await designState(page)).helices.length).toBe(before.helices.length + 18)
  const after = await designState(page)
  const groups = after.cluster_transforms.filter(c => c.helix_ids.length)
  expect(groups.length).toBe(2)
  expect(groups.map(c => c.helix_ids.length).sort()).toEqual([18, 18])
  await fitOblique(page)
  await guide.capture('The two separated bundles form two clusters. Each cluster can be selected for its own tools and transformations.')
}
