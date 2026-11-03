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

const workflowKeys = [
  ['1', 'menu-routing-scaffold-ends'], ['2', 'menu-routing-full-autostaple'],
  ['4', 'menu-seq-update-routing'], ['5', 'menu-seq-assign-scaffold'],
  ['6', 'menu-seq-assign-staples'], ['0', 'menu-seq-hairpin-dimer'],
]

test('cadnano routing and sequencing keys dispatch once and respect input focus', async ({ page }) => {
  await page.goto('/cadnano-editor.html')
  await page.keyboard.press('e')
  await expect(page.locator('#select-filter [data-key="line"]')).toHaveClass(/active/)
  await page.evaluate(keys => {
    window.workflowClicks = []
    const ids = new Set(keys.map(([, id]) => id))
    // Observe dispatch without running routing on a document.
    document.addEventListener('click', e => {
      if (!ids.has(e.target.id)) return
      window.workflowClicks.push(e.target.id)
      e.preventDefault()
      e.stopImmediatePropagation()
    }, true)
    for (const id of ids) document.getElementById(id).disabled = false
  }, workflowKeys)
  await page.locator('#pathview-canvas').click({ position: { x: 200, y: 100 } })
  for (const [key, id] of workflowKeys) {
    await page.evaluate(() => { window.workflowClicks = [] })
    await page.keyboard.press(key)
    expect(await page.evaluate(() => window.workflowClicks)).toEqual([id])
    await page.evaluate(key => document.body.dispatchEvent(new KeyboardEvent('keydown', {
      key, repeat: true, bubbles: true, cancelable: true,
    })), key)
    expect(await page.evaluate(() => window.workflowClicks)).toEqual([id])
    await page.evaluate(id => { document.getElementById(id).disabled = true; window.workflowClicks = [] }, id)
    await page.keyboard.press(key)
    expect(await page.evaluate(() => window.workflowClicks)).toEqual([])
    await page.evaluate(id => { document.getElementById(id).disabled = false }, id)
  }
  for (const tag of ['input', 'textarea', 'select', 'div']) {
    await page.evaluate(tag => {
      const el = document.createElement(tag)
      if (tag === 'div') el.contentEditable = 'true'
      el.id = 'hotkey-field'
      document.body.append(el)
      el.focus()
      window.workflowClicks = []
    }, tag)
    for (const [key] of workflowKeys) await page.keyboard.press(key)
    expect(await page.evaluate(() => window.workflowClicks)).toEqual([])
    await page.locator('#hotkey-field').evaluate(el => el.remove())
  }
  await page.evaluate(keys => {
    for (const [key] of keys) for (const modifier of ['ctrlKey', 'metaKey', 'altKey', 'shiftKey']) {
      document.body.dispatchEvent(new KeyboardEvent('keydown', { key, [modifier]: true, bubbles: true }))
    }
  }, workflowKeys)
  expect(await page.evaluate(() => window.workflowClicks)).toEqual([])
})

test('cadnano scaffold sequence picker offers and submits p7560', async ({ page }) => {
  await page.goto('/cadnano-editor.html')
  await page.evaluate(async () => {
    const { editorStore } = await import('/src/cadnano-editor/store.js')
    editorStore.setState({ design: { id: '__e2e__p7560', lattice_type: 'HONEYCOMB', helices: [], crossovers: [],
      strands: [{ id: 'scaffold', strand_type: 'scaffold', domains: [
        { helix_id: 'h', start_bp: 0, end_bp: 7559, direction: 'FORWARD' },
      ] }],
    } })
  })
  // Keep this test local: inspect the outgoing request, without saving a design.
  await page.route('**/api/design/assign-scaffold-sequence', route => route.fulfill({ json: { padded_nt: 0 } }))
  await page.keyboard.press('5')
  const modal = page.locator('#assign-scaffold-modal')
  await expect(modal).toBeVisible()
  await modal.locator('input[value="p7560"]').check()
  await expect(modal.locator('#asc-warning')).toBeHidden()
  const request = page.waitForRequest('**/api/design/assign-scaffold-sequence')
  await modal.locator('#asc-apply').click()
  expect((await request).postDataJSON()).toMatchObject({ scaffold_name: 'p7560', custom_sequence: null })
})
