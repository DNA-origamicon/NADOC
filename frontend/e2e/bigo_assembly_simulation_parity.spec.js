import { expect, test } from '@playwright/test'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

const PART = resolve(process.cwd(), '..', 'workspace', 'BigO.nadoc')
const ASSEMBLY = resolve(process.cwd(), '..', 'workspace', 'BigO-poly.nass')
test.skip(!existsSync(PART) || !existsSync(ASSEMBLY), 'BigO simulation parity fixtures are missing')

const ENGINES = ['cando', 'snupi', 'mrdna', 'oxdna', 'namd']

async function openDynamics(page, kind) {
  const assembly = kind === 'assembly'
  const materializations = []
  page.on('response', response => {
    if (response.url().includes('/api/assembly/flatten/load-as-design')) {
      materializations.push(response.status())
    }
  })
  await page.goto(`/?doc=__e2e__bigo-sim-${kind}&open=${assembly ? 'BigO-poly.nass' : 'BigO.nadoc'}&open-type=${assembly ? 'assembly' : 'design'}`)
  await page.waitForFunction(isAssembly => {
    const state = window.__NADOC_DBG__?.store.getState()
    return isAssembly
      ? state.assemblyActive && (state.currentAssembly?.instances?.length ?? 0) === 1
      : !state.assemblyActive && !!state.currentDesign
  }, assembly, { timeout: 90_000 })
  // The simulation audit targets sidebar controls, not continuous canvas FPS.
  // BigO has 14,112 nucleotides and two software-WebGL render loops can otherwise
  // monopolize the headless test host while Playwright waits on modal controls.
  // Stopping Three's loop leaves browser requestAnimationFrame (and therefore all
  // UI transitions/handlers) intact, while preserving the fully rendered scene.
  await page.evaluate(() => window.__NADOC_DBG__?.renderer.setAnimationLoop(null))
  await expect(page.locator('#welcome-screen')).not.toBeVisible()
  await page.waitForFunction(() => !!window.__leftSidebar, null, { timeout: 90_000 })
  const dynamicsTab = page.locator('.left-tab-btn[data-tab="dynamics"]')
  await expect(dynamicsTab).toBeEnabled({ timeout: 90_000 })
  await dynamicsTab.click()
  await page.waitForFunction(() => window.__NADOC_DBG__?.store.getState()?.simulationTabActive, null, { timeout: 30_000 })
  // Main initialization can finish between the controller becoming visible and
  // the Simulate coordinator subscribing. Replaying the authoritative tab event
  // is idempotent and makes the resource/status assertion deterministic.
  await page.evaluate(() => window.dispatchEvent(new CustomEvent('nadoc:left-tab-change', {
    detail: { activeTab: 'dynamics', collapsed: false },
  })))
  await expect(page.locator('#simulate-body')).toBeVisible()
  await expect(page.locator('#simulate-status-line')).not.toHaveText('', { timeout: 90_000 })
  if (assembly) await expect.poll(() => materializations.filter(x => x === 200).length).toBeGreaterThan(0)
  return materializations
})

async function controlAudit(page, engine) {
  await page.locator(`.engine-selector-btn[data-engine="${engine}"]`).click()
  const panel = page.locator(`#${engine === 'namd' ? 'md' : engine}-jobs-panel`)
  await expect(panel).toBeVisible()

  // Exercise every collapsible card. The same handlers must accept click and
  // contextmenu in both hosts without a page error or mode switch.
  await panel.locator('.ox-card__header:visible').evaluateAll(headers => {
    for (const header of headers) {
      header.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true }))
      header.click()
      header.click()
    }
  })

  return page.evaluate(({ engine }) => {
    const panelId = `#${engine === 'namd' ? 'md' : engine}-jobs-panel`
    const roots = [document.querySelector(panelId), document.querySelector(`#${engine}-run-controls`)]
    const rows = []
    for (const root of roots) {
      for (const el of root?.querySelectorAll('button,input,select,textarea,[role="button"]') ?? []) {
        if (el.closest('template')) continue
        const style = getComputedStyle(el)
        if (style.display === 'none' || style.visibility === 'hidden') continue
        rows.push({
          tag: el.tagName,
          id: el.id,
          type: el.getAttribute('type') || '',
          text: (el.textContent || '').replace(/\s+/g, ' ').trim(),
          value: 'value' in el ? String(el.value) : '',
          checked: 'checked' in el ? !!el.checked : null,
          disabled: 'disabled' in el ? !!el.disabled : el.getAttribute('aria-disabled') === 'true',
          title: el.getAttribute('title') || '',
        })
      }
    }
    return rows
  }, { engine })
}

async function wizardAudit(page, engine) {
  const selector = engine === 'namd' ? '#md-jobs-new-btn' : '#oxdna-jobs-new-btn'
  await page.locator(`.engine-selector-btn[data-engine="${engine}"]`).click()
  await page.locator(selector).click()
  const modal = page.locator('.modal--wizard:visible')
  await expect(modal).toBeVisible()
  const tabs = modal.locator('.wizard-tab')
  const panes = []
  for (let i = 0; i < await tabs.count(); i++) {
    await tabs.nth(i).evaluate(el => el.click())
    panes.push(await modal.evaluate(root => ({
      title: root.querySelector('.modal__title')?.textContent?.trim() || '',
      tab: root.querySelector('.wizard-tab.is-selected')?.textContent?.replace(/\s+/g, ' ').trim() || '',
      controls: [...root.querySelectorAll('button,input,select,textarea')]
        .filter(el => getComputedStyle(el).display !== 'none' && getComputedStyle(el).visibility !== 'hidden')
        .map(el => ({
          tag: el.tagName, type: el.getAttribute('type') || '',
          text: (el.textContent || '').replace(/\s+/g, ' ').trim(),
          // A fresh NAMD wizard intentionally generates a cryptographic seed.
          // Its presence/type belongs in the parity signature; its random value does not.
          value: el.closest('.wizard-field')?.querySelector('.wizard-field__label')
            ?.textContent?.trim().startsWith('Random seed') ? '<generated-seed>'
            : ('value' in el ? String(el.value) : ''),
          checked: 'checked' in el ? !!el.checked : null,
          disabled: !!el.disabled,
        })),
    })))
  }
  await page.keyboard.press('Escape')
  await expect(modal).toBeHidden()
  return panes
}

test('BigO-poly materializes the whole assembly and exposes identical simulation controls', async ({ browser }, testInfo) => {
  test.setTimeout(600_000)
  const audits = {}
  const screenshots = {}
  await Promise.all(['part', 'assembly'].map(async kind => {
    const context = await browser.newContext()
    const page = await context.newPage()
    const errors = []
    page.on('pageerror', error => errors.push(error.message))
    page.on('console', message => { if (message.type() === 'error') errors.push(message.text()) })
    await openDynamics(page, kind)
    audits[kind] = {}
    screenshots[kind] = {}
    for (const engine of ENGINES) {
      audits[kind][engine] = await controlAudit(page, engine)
      screenshots[kind][engine] = await page.locator(`#${engine === 'namd' ? 'md' : engine}-jobs-panel`).screenshot()
    }
    audits[kind].wizards = {
      oxdna: await wizardAudit(page, 'oxdna'),
      namd: await wizardAudit(page, 'namd'),
    }

    if (kind === 'assembly') {
      const counts = await page.evaluate(async () => {
        const api = await import('/src/api/client.js')
        const flat = await api.flattenAssembly()
        const state = window.__NADOC_DBG__.store.getState()
        const count = d => ({ helices: d?.helices?.length ?? 0, strands: d?.strands?.length ?? 0 })
        return {
          flattened: count(flat.design), simulation: count(state.currentDesign),
          geometry: state.currentGeometry?.length ?? 0, assemblyActive: state.assemblyActive,
        }
      })
      expect(counts.simulation).toEqual(counts.flattened)
      expect(counts.geometry).toBeGreaterThan(0)
      expect(counts.assemblyActive).toBe(true)
    }
    expect(errors).toEqual([])
    await context.close()
  }))

  await testInfo.attach('bigo-assembly-simulation-controls.json', {
    body: JSON.stringify(audits, null, 2), contentType: 'application/json',
  })
  for (const engine of ENGINES) expect(audits.assembly[engine], `${engine} controls`).toEqual(audits.part[engine])
  expect(audits.assembly.wizards, 'all wizard tabs/options').toEqual(audits.part.wizards)
  for (const engine of ENGINES) {
    expect(Buffer.compare(screenshots.assembly[engine], screenshots.part[engine]), `${engine} pixels`).toBe(0)
  }
})
