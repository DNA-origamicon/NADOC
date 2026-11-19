// No authored structures, files or jobs: wizard inputs are count-only API stand-ins.
// Session caching is disabled by the dedicated Playwright backend. Report artifacts
// are removed by artifact-cleanup-reporter; no other persistent output is created.
import { test, expect } from '@playwright/test'
for (const engine of ['snupi', 'mrdna']) {
  for (const target of ['alpine', 'runpod']) {
    test(engine + '/' + target + ': scrollable resources enforce limits and review', async ({ page }) => {
      await page.goto('/?doc=__e2e__solver_resource_wizard')
      await page.waitForSelector('#canvas')
      await page.evaluate(async ({ engine, target }) => {
        const { solverResourceWizard } = await import('/src/ui/solver_resource_wizard.js')
        window.__wizardResult = 'pending'
        const common = { cuda: true, max_cores: 64, mem_per_core_gb: 4, qos: [{ name: 'gpu-normal', minutes: 60 }], on_demand: 1, stock: 'High', availability: { gpus_free: 2, gpus_total: 4, wait_min: 10, wait_basis: 'recent queue history' } }
        void solverResourceWizard({ engine, target,
          need: { runtime: { seconds: 3600, basis: 'Reference hardware estimate' }, ram_gib: 40, vram_gib: engine === 'snupi' ? 0 : 20, disk_gib: 3, min_ram_gib: 50, min_vram_gb: engine === 'snupi' ? 0 : 26 },
          rows: [{ ...common, id: 'small', vram_gb: 24, max_ram_gib: 32 }, { ...common, id: 'large', vram_gb: 48, max_ram_gib: 256 }, ...Array.from({ length: 10 }, (_, i) => ({ ...common, id: 'GPU ' + i, vram_gb: 80, max_ram_gib: 256 }))],
          initial: { python: '/env/bin/python', arbd: '/bin/arbd' },
        }).then(value => { window.__wizardResult = value })
      }, { engine, target })
      const dialog = page.getByRole('dialog')
      await expect(dialog).toBeVisible()
      await expect(dialog.getByText('Back', { exact: true })).toBeHidden()
      await expect(dialog.getByText('Re-check availability', { exact: true })).toBeHidden()
      expect(await dialog.locator('.solver-resource-list').evaluate(n => n.scrollWidth <= n.clientWidth)).toBe(true)
      if (target === 'alpine' || engine === 'mrdna') await expect(dialog.locator('input[value="small"]')).toHaveJSProperty('disabled', true)
      const styles = await dialog.evaluate(node => {
        const style = selector => {
          const s = getComputedStyle(node.querySelector(selector))
          return { color: s.color, background: s.backgroundColor, font: s.fontFamily }
        }
        return { number: style('input[type="number"]'), text: style('input[type="text"]'), row: style('.solver-resource-list__row[data-selected="false"]'),
          buttons: [...node.querySelectorAll('.modal__actions button')].map(b => b.className) }
      })
      expect(styles.number.background).toBe('rgb(13, 17, 23)')
      expect(styles.number.color).toBe('rgb(230, 237, 243)')
      expect(styles.number.font).toContain('monospace')
      expect(styles.number.color).not.toBe(styles.number.background)
      expect(styles.text.color).toBe(styles.number.color)
      expect(styles.row.background).toBe(styles.number.background)
      await expect(dialog.getByRole('button', { name: 'Cancel', exact: true })).toHaveClass(/btn/)
      await expect(dialog.getByRole('button', { name: 'Review resources' })).toHaveClass(/btn--primary/)
      await expect(dialog.getByText('Est. completion', { exact: true })).toBeVisible()
      expect(await dialog.locator('.solver-resource-list__scroll').evaluate(n => n.scrollHeight > n.clientHeight)).toBe(true)
      await dialog.getByRole('radio', { name: 'GPU 9', exact: true }).check()
      await expect(dialog.getByRole('radio', { name: 'GPU 9', exact: true })).toBeChecked()
      if (process.env.NADOC_SOLVER_SCREENSHOT && engine === 'snupi' && target === 'runpod') {
        await dialog.screenshot({ path: process.env.NADOC_SOLVER_SCREENSHOT })
      }
      const ram = dialog.getByRole('spinbutton', { name: 'RAM allocation (GiB)' })
      await ram.fill('49')
      await expect(dialog.getByRole('button', { name: 'Review resources' })).toBeDisabled()
      await ram.fill('50')
      await dialog.getByRole('button', { name: 'Review resources' }).click()
      expect(await page.evaluate(() => window.__wizardResult)).toBe('pending')
      await expect(dialog.getByRole('button', { name: 'Back', exact: true })).toHaveClass(/btn/)
      await dialog.getByRole('button', { name: 'Back', exact: true }).click()
      await dialog.getByRole('button', { name: 'Review resources' }).click()
      await dialog.getByRole('button', { name: target === 'alpine' ? 'Submit job' : 'Rent pod and start' }).click()
      await expect(dialog).toHaveCount(0)
      expect(await page.evaluate(() => window.__wizardResult.execution_target)).toBe(target)
      expect(await page.evaluate(target => window.__wizardResult[target === 'alpine' ? 'cluster_settings' : 'runpod_settings'][target === 'alpine' ? 'partition' : 'gpu_id'], target)).toBe('GPU 9')
    })
  }
}
