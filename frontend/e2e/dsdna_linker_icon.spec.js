/**
 * Visual verification of the dsDNA linker connection-type icons.
 *
 * Extracts the SVG generator functions from overhangs_manager_popup.js,
 * runs them in Node to get the SVG strings, then renders them in the
 * browser at small (in-app) and large (debug) sizes for visual comparison
 * with the user's reference image.
 */

import { test } from '@playwright/test'
import fs from 'node:fs'
import path from 'node:path'

const SRC = fs.readFileSync(
  path.resolve(import.meta.dirname, '../src/ui/overhangs_manager_popup.js'),
  'utf8'
)

function extractFn(name) {
  // Match `function NAME(...) { ... }` allowing any parameter list.
  const re = new RegExp(`function ${name}\\([^)]*\\)\\s*\\{[\\s\\S]*?\\n\\}`, 'm')
  const m = SRC.match(re)
  if (!m) throw new Error(`Could not find function ${name}`)
  return m[0]
}

const helpers = [
  extractFn('_polarityMarker'),
  extractFn('_oppPolarity'),
  extractFn('_warningOverlay'),
].join('\n')

function runFn(code, name, args = '') {
  // Bundle helpers (marker / polarity flip / warning overlay) so SVG
  // generators that reference them work in this isolated eval context.
  // eslint-disable-next-line no-new-func
  return new Function(`${helpers}\n${code}\nreturn ${name}(${args});`)()
}

const svgRoot = runFn(extractFn('_ctRootToRootDsdnaLinkerSvg'), '_ctRootToRootDsdnaLinkerSvg')
const svgEnd  = runFn(extractFn('_ctEndToEndDsdnaLinkerSvg'),   '_ctEndToEndDsdnaLinkerSvg')

// 3'/3' variant (triangle markers on both ends) for visual check.
const svgRoot3p = runFn(extractFn('_ctRootToRootDsdnaLinkerSvg'), '_ctRootToRootDsdnaLinkerSvg', `'3p', '3p'`)

const BLUE = '#4a78b8'

function makeHtml(title, svg) {
  return `<!DOCTYPE html>
<html><head><meta charset="utf-8"/><title>${title}</title>
<style>
  body { margin: 0; padding: 16px; background: #222; font: 14px sans-serif; color: #ddd; }
  h2 { margin: 6px 0 14px; }
  .tile { background: ${BLUE}; display: inline-flex; align-items: center; justify-content: center; margin: 8px 16px 8px 0; vertical-align: top; }
  .tile svg { display: block; width: 86%; height: 70%; }
  .small { width: 150px; height: 80px; }
  .large { width: 600px; height: 260px; }
</style></head>
<body>
  <h2>${title}</h2>
  <div class="tile small">${svg}</div>
  <div class="tile large">${svg}</div>
</body></html>`
}

test('root-to-root dsDNA linker — screenshot', async ({ page }) => {
  await page.setContent(makeHtml('Root-to-Root dsDNA Linker', svgRoot))
  await page.locator('.large svg').waitFor()
  await page.locator('.large').screenshot({ path: 'e2e/screenshots/dsdna_linker_root_to_root.png' })
})

test('end-to-end dsDNA linker — screenshot', async ({ page }) => {
  await page.setContent(makeHtml('End-to-End dsDNA Linker', svgEnd))
  await page.locator('.large svg').waitFor()
  await page.locator('.large').screenshot({ path: 'e2e/screenshots/dsdna_linker_end_to_end.png' })
})

test('root-to-root dsDNA linker — 3p polarity (triangles)', async ({ page }) => {
  await page.setContent(makeHtml('R-to-R dsDNA Linker (3prime/3prime)', svgRoot3p))
  await page.locator('.large svg').waitFor()
  await page.locator('.large').screenshot({ path: 'e2e/screenshots/dsdna_linker_root_to_root_3p.png' })
})

test('linker markers + warnings — full matrix screenshot', async ({ page }) => {
  // Render every linker icon in both valid and forbidden polarity states.
  const cases = [
    ['root-to-root-indirect',     'R2R-Indirect',   '_ctRootToRootIndirectSvg'],
    ['end-to-end-indirect',       'E2E-Indirect',   '_ctEndToEndIndirectSvg'],
    ['root-to-root-ssdna-linker', 'R2R-ssDNA',      '_ctRootToRootSsdnaLinkerSvg'],
    ['end-to-end-ssdna-linker',   'E2E-ssDNA',      '_ctEndToEndSsdnaLinkerSvg'],
    ['root-to-root-dsdna-linker', 'R2R-dsDNA',      '_ctRootToRootDsdnaLinkerSvg'],
    ['end-to-end-dsdna-linker',   'E2E-dsDNA',      '_ctEndToEndDsdnaLinkerSvg'],
  ]
  const isForbidden = (type, L, R) => {
    if (type.includes('dsdna')) return L !== R
    return L === R
  }
  let html = `<!DOCTYPE html><html><head><style>
    body { margin: 0; padding: 12px; background: #222; font: 12px sans-serif; color: #ddd; }
    table { border-collapse: collapse; }
    td { padding: 4px; vertical-align: top; }
    .lbl { font-size: 11px; color: #aaa; margin-bottom: 3px; }
    .tile { background: #4a78b8; width: 160px; height: 100px; display: flex; align-items: center; justify-content: center; }
    .tile svg { width: 88%; height: 80%; display: block; }
  </style></head><body><table><tr>
    <th></th><th>5'/5'</th><th>5'/3'</th><th>3'/5'</th><th>3'/3'</th>
  </tr>`
  for (const [type, label, fnName] of cases) {
    const fnCode = extractFn(fnName)
    html += `<tr><td><b>${label}</b></td>`
    for (const [L, R] of [['5p','5p'], ['5p','3p'], ['3p','5p'], ['3p','3p']]) {
      const warn = isForbidden(type, L, R)
      const svg = runFn(fnCode, fnName, `'${L}', '${R}', ${warn}`)
      const tag = warn ? '⚠ FORBIDDEN' : '✓ valid'
      html += `<td><div class="lbl">${L}/${R} ${tag}</div><div class="tile">${svg}</div></td>`
    }
    html += `</tr>`
  }
  html += `</table></body></html>`
  await page.setContent(html)
  await page.locator('table').waitFor()
  await page.screenshot({ path: 'e2e/screenshots/linker_polarity_matrix.png', fullPage: true })
})
