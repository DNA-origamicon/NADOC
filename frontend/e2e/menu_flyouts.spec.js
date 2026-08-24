import { test, expect } from '@playwright/test'

async function verifyFlyout(page, topId, submenuLabel) {
  const before = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    body: document.body.scrollWidth - document.body.clientWidth,
  }))
  const top = page.locator(topId)
  // Empty-workspace boot disables editing menus; enable the shell so this test
  // can exercise its CSS flyout geometry without loading or mutating a design.
  await top.evaluate(element => element.classList.remove('disabled'))
  await top.locator(':scope > button').hover()
  const dropdown = top.locator(':scope > .dropdown')
  await expect(dropdown).toBeVisible()

  const row = dropdown.locator('.submenu-item', { hasText: submenuLabel }).first()
  await row.hover()
  const submenu = row.locator(':scope > .submenu')
  await expect(submenu).toBeVisible()

  const boxes = await Promise.all([dropdown.boundingBox(), row.boundingBox(), submenu.boundingBox()])
  const [menuBox, rowBox, flyoutBox] = boxes
  expect(menuBox).toBeTruthy()
  expect(rowBox).toBeTruthy()
  expect(flyoutBox).toBeTruthy()

  // A real flyout is a separate adjacent box, not content expanding the root menu.
  const opensRight = Math.abs(flyoutBox.x - (menuBox.x + menuBox.width)) <= 3
  const opensLeft = Math.abs((flyoutBox.x + flyoutBox.width) - menuBox.x) <= 3
  expect(opensRight || opensLeft).toBe(true)
  expect(flyoutBox.x + flyoutBox.width <= page.viewportSize().width + 1).toBe(true)
  expect(flyoutBox.x >= -1).toBe(true)

  const visibility = await submenu.evaluate((element, box) => {
    const style = getComputedStyle(element.parentElement.closest('.dropdown'))
    const hit = document.elementFromPoint(box.x + box.width / 2, box.y + box.height / 2)
    return {
      rootOverflowX: style.overflowX,
      rootOverflowY: style.overflowY,
      hitInsideFlyout: Boolean(hit && element.contains(hit)),
    }
  }, flyoutBox)
  expect(visibility.rootOverflowX).toBe('visible')
  expect(visibility.rootOverflowY).toBe('visible')
  expect(visibility.hitInsideFlyout).toBe(true)

  const overflow = await page.evaluate(() => ({
    document: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    body: document.body.scrollWidth - document.body.clientWidth,
  }))
  expect(overflow.document).toBeLessThanOrEqual(0)
  expect(overflow.document).toBe(before.document)
  expect(overflow.body).toBe(before.body)
}

for (const width of [1280, 760]) {
  test(`main menu flyouts are adjacent without side-scroll at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await page.goto('/')
    await verifyFlyout(page, '#menu-item-export', 'Atomistic')
    await verifyFlyout(page, '#menu-item-tools', 'Sequencing')
    await verifyFlyout(page, '#menu-item-tools', 'Automation')
  })

  test(`Origami editor flyouts are adjacent without side-scroll at ${width}px`, async ({ page }) => {
    await page.setViewportSize({ width, height: 800 })
    await page.goto('/cadnano-editor.html')
    await verifyFlyout(page, '#menu-item-export', 'Atomistic')
  })
}

test('diagnostic commands live in the top-level Debug menu', async ({ page }) => {
  await page.goto('/')

  const debugMenu = page.locator('#menu-item-debug')
  await debugMenu.locator(':scope > button').hover()
  await expect(debugMenu.locator(':scope > .dropdown')).toBeVisible()
  await expect(debugMenu.locator('#menu-view-debug')).toContainText('Debug Overlay')
  await expect(debugMenu.locator('#menu-help-molecular-placement-audit')).toBeVisible()
  await expect(debugMenu.locator('#menu-debug-inspect')).toBeVisible()

  await expect(page.locator('#menu-item-view #menu-view-debug')).toHaveCount(0)
  await expect(page.locator('#menu-view-periodic-seam-arcs')).toContainText('Periodic Seam Connections')
})

test('View menu toolbar toggles follow toolbar order', async ({ page }) => {
  await page.goto('/')
  const ids = await page.locator('#menu-item-view > .dropdown > .dropdown-item[id]').evaluateAll(items =>
    items.map(item => item.id),
  )
  const positions = ids.reduce((result, id, index) => ({ ...result, [id]: index }), {})

  const viewOrder = [
    'menu-view-sequences',
    'menu-view-undefined-bases',
    'menu-view-loop-skip',
    'menu-view-overhang-names',
  ]
  const modeOrder = [
    'menu-view-extra-base-spacing',
    'menu-view-deform',
    'menu-view-unfold',
    'menu-view-cadnano',
  ]
  for (const group of [viewOrder, modeOrder]) {
    expect(group.map(id => positions[id])).toEqual([...group.map(id => positions[id])].sort((a, b) => a - b))
  }
})
