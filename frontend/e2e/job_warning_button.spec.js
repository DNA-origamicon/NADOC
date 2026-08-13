import { expect, test } from '@playwright/test'

test('shared simulation warning is a real button and never clicks its job row', async ({ page }) => {
  await page.goto('/?doc=warning-button-readonly')
  await page.waitForFunction(() => document.readyState === 'complete')

  const result = await page.evaluate(async () => {
    const { renderJobRow } = await import('/src/ui/jobs_panel_render.js')
    const host = document.createElement('div')
    document.body.append(host)
    host.dataset.rowClicks = '0'
    host.dataset.warningClicks = '0'
    const row = renderJobRow({
      jobId: 'stale-job', depth: 0, indentPx: 0, selected: true,
      statusKey: 'namd-running', isActive: false, indexLabel: '', label: 'P1 Alpine',
      title: '', timeStr: '', sizeStr: '', archived: false, archivePath: '', stale: true,
      staleClass: 'job-stale-warning', staleTitle: 'Restore submitted design', tags: [],
      action: null, chevron: null, postLabelMarkers: [], symbolOverride: null,
      compactColumns: true, colors: { dim: '#888', warn: '#e0a800' },
    }, {
      onClick: () => { host.dataset.rowClicks = String(Number(host.dataset.rowClicks) + 1) },
      onWarning: () => { host.dataset.warningClicks = String(Number(host.dataset.warningClicks) + 1) },
    })
    host.append(row)
    const button = row.querySelector('button[type="button"]')
    return { tag: button?.tagName, type: button?.type, aria: button?.getAttribute('aria-label') }
  })

  expect(result).toEqual({ tag: 'BUTTON', type: 'button', aria: 'Restore submitted design' })
  const button = page.locator('.job-stale-warning')
  await expect(button).toBeVisible()
  await button.click()
  const counts = await page.locator('body > div:last-child').evaluate(host => ({
    row: host.dataset.rowClicks,
    warning: host.dataset.warningClicks,
  }))
  expect(counts).toEqual({ row: '0', warning: '1' })
})
