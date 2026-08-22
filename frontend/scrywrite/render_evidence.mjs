import { chromium } from 'playwright'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const prefix = process.argv[2]
if (!prefix) {
  throw new Error('Usage: node render_evidence.mjs <output-prefix>')
}

const browser = await chromium.launch({ headless: true })
try {
  for (const [suffix, viewport] of [
    ['pov', { width: 1280, height: 720 }],
    ['topdown', { width: 1000, height: 800 }],
  ]) {
    const page = await browser.newPage({ viewport, deviceScaleFactor: 1 })
    const svgPath = path.resolve(`${prefix}_${suffix}.svg`)
    await page.goto(pathToFileURL(svgPath).href, { waitUntil: 'load' })
    await page.screenshot({ path: `${prefix}_${suffix}.png` })
    await page.close()
  }
} finally {
  await browser.close()
}
