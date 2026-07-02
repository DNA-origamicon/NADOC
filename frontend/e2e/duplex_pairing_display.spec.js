import { test, expect } from '@playwright/test'

// Proposal-B Phase 3 (visible): loading a design that carries a legacy
// OverhangBinding derives a register-bearing Duplex on load, and the Overhang
// Connections section colours the pairing from that stored register — paired
// window green, the leftover TOEHOLD grey. Fixture built by
// scripts/gen_duplex_demo_fixture.py (overhang A 6 bp bound to B 4 bp → 2 bp toehold).
const FIXTURE = '/home/joshua/NADOC/workspace/playwright_tests/duplex_demo.nadoc'

const GREEN = 'rgb(63, 185, 80)'    // #3fb950 paired
const GREY  = 'rgb(139, 148, 158)'  // #8b949e toehold

test('duplex pairing display: derived-on-load duplex colours paired + toehold', async ({ page }) => {
  const errors = []
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()) })

  await page.goto('/')
  await page.waitForTimeout(1500)

  // Load the fixture — the load path derives duplexes from the binding.
  await page.evaluate(async (p) => {
    const a = await import('/src/api/client.js')
    await a.loadDesign(p)
    await a.getGeometry()
    document.getElementById('welcome-screen')?.classList.add('hidden')
  }, FIXTURE)
  await page.waitForTimeout(1200)

  // The derived duplex should be present, and we read its overhang ids.
  const ids = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const d = store.getState().currentDesign
    const dx = (d?.duplexes ?? [])[0]
    return dx ? { count: d.duplexes.length, a: dx.left.overhang_id, b: dx.right.overhang_id } : null
  })
  expect(ids, 'a duplex was derived on load').not.toBeNull()
  expect(ids.count).toBe(1)

  // Expand the Overhang Connections section and select the two overhangs.
  await page.evaluate(({ a, b }) => {
    document.getElementById('oconn-heading')?.click()
    const selA = document.getElementById('oconn-select-a')
    const selB = document.getElementById('oconn-select-b')
    selA.value = a; selA.dispatchEvent(new Event('change'))
    selB.value = b; selB.dispatchEvent(new Event('change'))
  }, ids)
  await page.waitForTimeout(500)

  // Read the coloured preview under side A (the 6 bp overhang with the toehold).
  const segs = await page.evaluate(() => {
    const row = document.getElementById('oconn-seq-row-a')
    const prev = row?.nextElementSibling
    if (!prev || !prev.classList.contains('oconn-seq-preview')) return []
    return [...prev.querySelectorAll('span')].map(s => ({ text: s.textContent, color: s.style.color }))
  })

  await page.screenshot({ path: 'e2e/screenshots/duplex_pairing_display.png', fullPage: true })

  // The 4 bp bound window is green (paired); the 2 bp tail is grey (toehold).
  const paired = segs.find(s => s.text === 'AAAC')
  const toehold = segs.find(s => s.text === 'GG')
  expect(paired, `paired span among ${JSON.stringify(segs)}`).toBeTruthy()
  expect(paired.color).toBe(GREEN)
  expect(toehold, `toehold span among ${JSON.stringify(segs)}`).toBeTruthy()
  expect(toehold.color).toBe(GREY)

  // ── The Overhangs SIDEBAR also shows the coverage line for the same overhang ──
  const sidebarSegs = await page.evaluate(() => {
    document.getElementById('overhang-panel-heading')?.click()
    const list = document.getElementById('overhang-list')
    return list ? [...list.querySelectorAll('span')].map(s => ({ text: s.textContent, color: s.style.color })) : []
  })
  const sPaired = sidebarSegs.find(s => s.text === 'AAAC')
  const sToehold = sidebarSegs.find(s => s.text === 'GG')
  expect(sPaired, `sidebar paired span among ${JSON.stringify(sidebarSegs)}`).toBeTruthy()
  expect(sPaired.color).toBe(GREEN)
  expect(sToehold?.color).toBe(GREY)

  // ── Driver toggle (Q4): two buttons + ▶ marks the driver; flipping persists ──
  const driver = await page.evaluate(() => {
    const btns = [...document.querySelectorAll('.oconn-driver-box button')]
    const prevA = document.getElementById('oconn-seq-row-a')?.nextElementSibling
    return { nBtns: btns.length, marker: prevA ? prevA.textContent.includes('▶') : false }
  })
  expect(driver.nBtns).toBe(2)
  expect(driver.marker).toBe(true)   // ▶ on the driver overhang's line

  const flip = await page.evaluate(async () => {
    const { store } = await import('/src/state/store.js')
    const before = store.getState().currentDesign.duplexes[0].driver
    const btns = [...document.querySelectorAll('.oconn-driver-box button')]
    const inactive = btns.find(b => b.style.background !== 'rgb(31, 111, 235)')
    inactive?.click()
    await new Promise(r => setTimeout(r, 700))
    return { before, after: store.getState().currentDesign.duplexes[0].driver }
  })
  expect(flip.after).not.toBe(flip.before)   // the user's driver choice persisted

  expect(errors, `console errors:\n${errors.join('\n')}`).toEqual([])
})
