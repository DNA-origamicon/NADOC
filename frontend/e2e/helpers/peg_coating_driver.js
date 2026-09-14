import { expect } from '@playwright/test'

/** Drive real sidebar controls; callers own their isolated fixture and launch interception. */
export class PegCoatingDriver {
  constructor(page) { this.page = page }

  async configure(values) {
    const fields = {
      segments: 'segments', bondLengthNm: 'bond', beadDiameterNm: 'diameter',
      terminalChargeE: 'charge', sizeNm: 'size', densityPerUm2: 'density',
      offsetXNm: 'offx', offsetYNm: 'offy', seed: 'seed',
    }
    for (const [name, value] of Object.entries(values)) {
      if (name === 'shape') await this.page.locator('#oxdna-peg-shape').selectOption(value)
      else {
        if (!fields[name]) throw new Error(`Unknown PEG field: ${name}`)
        await this.page.locator(`#oxdna-peg-${fields[name]}`).fill(String(value))
      }
    }
    return this
  }

  async review() {
    const responsePromise = this.page.waitForResponse('**/api/oxdna/peg/setup')
    await this.page.locator('#oxdna-peg-review').click()
    const response = await responsePromise
    expect(response.ok()).toBe(true)
    return response.json()
  }
}
