import { test, expect } from '@playwright/test'

test('caDNAno top-bar hotkeys match the shared 3D-view controls', async ({ page }) => {
  await page.goto('/cadnano-editor.html')

  const activeCycleKeys = () => page.locator('#select-filter [data-tab-cycle].active')
    .evaluateAll(buttons => buttons.map(button => button.dataset.key))

  await page.keyboard.press('e')
  expect(await activeCycleKeys()).toEqual(['line'])
  await page.keyboard.press('e')
  expect(await activeCycleKeys()).toEqual(['ends'])
  await page.keyboard.press('q')
  expect(await activeCycleKeys()).toEqual(['line'])

  const pickable = () => page.locator('#select-filter .sf-btn.active')
    .evaluateAll(buttons => buttons
      .map(button => button.dataset.key)
      .filter(key => key === 'scaf' || key === 'stap'))
  await page.keyboard.press('s')
  expect(await pickable()).toEqual(['stap'])
  await page.keyboard.press('s')
  expect(await pickable()).toEqual(['scaf'])
  await page.keyboard.press('s')
  expect(await pickable()).toEqual(['scaf', 'stap'])

  for (const key of ['g', 'p']) {
    const button = page.locator(`.vt-btn[data-hotkey="${key}"]`)
    const before = await button.evaluate(el => el.classList.contains('active'))
    await page.keyboard.press(key)
    await expect(button).toHaveClass(before ? /^(?!.*\bactive\b)/ : /\bactive\b/)
  }
})
