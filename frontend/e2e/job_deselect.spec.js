/**
 * job_deselect.spec.js — TROUBLESHOOTING/verification spec for "clicking the selected job
 * row deselects it, without throwing away cached visualization".
 *
 * Not part of the routine dev cycle. It exists because the two claims are only observable
 * in the real app: (a) the toggle works on EVERY engine tab, and (b) the 3D overlay left by
 * the deselected job is still on screen afterwards — a unit test can assert the controller
 * wasn't torn down, but only pixels prove the render survived
 * (memory/feedback_display_toggle_visual_verify.md).
 *
 * Read-only: opens existing designs through the app's own library and clicks existing
 * finished jobs. Submits/stops/deletes nothing, writes no .nadoc.
 *
 * Runs against the USER'S dev servers (playwright.livedev.config.js), booting on a PINNED
 * ?doc so the default document is untouched.
 *
 *   npx playwright test --config playwright.livedev.config.js \
 *     e2e/job_deselect.spec.js --reporter=list
 */
import { test, expect } from '@playwright/test'

const SHOTS = 'e2e/screenshots'

// Engine → a design that actually HAS a finished job of that engine on this machine.
// (BLADE has no jobs at all here, so it is covered only by its unit tests — its panel is
// the same `_deselectJob` shape as CanDo/SNUPI.)
const ENGINES = [
  { engine: 'oxdna', design: '3x6x400_test' },
  { engine: 'namd',  design: '3x6x400_test' },
  { engine: 'cando', design: '3x6x400_test' },
  { engine: 'snupi', design: '3x6x400_test' },
  { engine: 'mrdna', design: '6hb_2xT' },
]

async function openDesign(page, doc, design) {
  await page.goto(`/?doc=${doc}`)
  await page.waitForSelector('#canvas')
  const welcome = page.locator('#welcome-screen')
  const needsPick = await welcome.evaluate(el => !el.classList.contains('hidden')).catch(() => true)
  if (needsPick) {
    const row = welcome.locator('.lib-row-name', { hasText: new RegExp(`^${design}$`) }).first()
    await row.waitFor({ state: 'visible', timeout: 60_000 })
    await row.click({ timeout: 15_000 })
  }
  await expect(welcome).toHaveClass(/hidden/, { timeout: 60_000 })
  await page.waitForFunction(() => {
    let n = 0
    window.__nadocTest?.scene?.traverse(o => {
      if (o.isInstancedMesh && o.name === 'backboneSpheres') n += o.count
    })
    return n > 0
  }, null, { timeout: 60_000 })
  await page.waitForTimeout(500)
}

/** The unified Simulate list is the ONE list the user clicks (each engine panel's own
 *  list is display:none in index.html). Selection is an inline background on the row. */
const listRows = (page) => page.locator('#simulate-jobs-list [data-job-id]')
const isSelected = (row) => row.evaluate(el => el.style.background !== '')

async function openDynamics(page, engine) {
  await page.locator('.left-tab-btn[data-tab="dynamics"]').click({ timeout: 15_000 })
  await page.locator(`.engine-selector-btn[data-engine="${engine}"]`).click({ timeout: 15_000 })
  await page.waitForTimeout(900)
}

/** Dolly until the whole part fills the frame — default framing leaves a 400-nt design ~80 px
 *  wide, which proves nothing to a human reader, and dollying INSIDE it makes every screenshot
 *  a parallax lottery. `ticks` positive = closer. */
async function dolly(page, ticks) {
  const box = await page.locator('#canvas').boundingBox()
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2)
  for (let i = 0; i < Math.abs(ticks); i++) {
    await page.mouse.wheel(0, ticks > 0 ? -240 : 240)
    await page.waitForTimeout(120)
  }
  await page.waitForTimeout(800)
}

test.describe('click the selected job row to deselect', () => {
  for (const { engine, design } of ENGINES) {
    test(`${engine}: second click on the selected row clears the selection, a third re-selects`, async ({ page }) => {
      await openDesign(page, `deselect-${engine}`, design)
      await openDynamics(page, engine)
      const row = listRows(page).first()
      await row.waitFor({ state: 'visible', timeout: 30_000 })

      await row.click()
      await page.waitForTimeout(700)
      expect(await isSelected(row)).toBe(true)
      await expect(page.locator('#simulate-jobs-status')).not.toHaveText(/Select a run/)

      await row.click()                                   // same row again → deselect
      await page.waitForTimeout(700)
      expect(await isSelected(listRows(page).first())).toBe(false)
      await expect(page.locator('#simulate-jobs-status')).toHaveText(/Select a run/)
      // Job actions (Archive/Delete) are selection-scoped → they go away too.
      await expect(page.locator('#simulate-job-actions')).toBeHidden()

      await row.click()                                   // and back
      await page.waitForTimeout(700)
      expect(await isSelected(listRows(page).first())).toBe(true)
    })
  }

  test('the deselected job\'s 3D overlay stays on screen (nothing cached is cleared)', async ({ page }) => {
    await openDesign(page, 'deselect-viz', '3x6x400_test')
    await openDynamics(page, 'cando')
    await dolly(page, 3)                                  // whole part in frame, not inside it
    const canvas = page.locator('#canvas')
    const status = page.locator('#cando-jobs-display-status')

    const native = await canvas.screenshot({ path: `${SHOTS}/deselect-0-native.png` })

    const row = listRows(page).first()
    await row.waitFor({ state: 'visible', timeout: 30_000 })
    await row.click()
    await page.waitForTimeout(1000)

    // Turn on the predicted-shape overlay → the model visibly deforms.
    const deform = page.locator('.cando-display-mode[value="deform"]')
    await expect(deform).toBeEnabled({ timeout: 30_000 })
    await deform.check()
    await page.waitForTimeout(6000)                       // let the deform settle
    const on = await canvas.screenshot({ path: `${SHOTS}/deselect-1-overlay-on.png` })
    expect(on.equals(native)).toBe(false)                 // the overlay really is on screen
    await expect(status).toHaveText(/./)

    const settled = await canvas.screenshot()
    // Baseline: untouched, the render is static — so a later byte-difference is attributable
    // to the deselect and not to an animation still running.
    expect(settled.equals(on)).toBe(true)

    await row.click()                                     // deselect
    await page.waitForTimeout(2500)
    expect(await isSelected(listRows(page).first())).toBe(false)
    const after = await canvas.screenshot({ path: `${SHOTS}/deselect-2-after-deselect.png` })
    expect(after.equals(on)).toBe(true)                   // same pixels → overlay untouched
    await expect(status).toHaveText(/./)                  // controller still reports a mode

    // …and "Off" is still reachable, so the lingering overlay can be taken down without
    // re-selecting first (every other mode radio locks with no job selected).
    const off = page.locator('.cando-display-mode[value="off"]')
    await expect(off).toBeEnabled()
    await off.check()
    await page.waitForTimeout(2500)
    const cleared = await canvas.screenshot({ path: `${SHOTS}/deselect-3-off.png` })
    expect(cleared.equals(after)).toBe(false)             // restored to native positions
  })
})
