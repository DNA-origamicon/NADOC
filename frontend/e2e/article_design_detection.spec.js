/** PDFs/CSVs exist only as in-memory buffers; no design, download or capture.
 * Isolated backend disables sessions; global teardown removes its bridge key. */
import { test, expect } from '@playwright/test'
import { execFileSync } from 'node:child_process'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('../../', import.meta.url))
function fixture(expression) {
  return JSON.parse(execFileSync('uv', ['run', 'python', '-c', `import json,base64\nfrom tests.test_article_design_detection import routing_pdf,calibrated_pdf\n${expression}`], { cwd: root, encoding: 'utf8' }))
}
async function open(page) {
  await page.goto('/'); await page.waitForFunction(() => !!window.__nadocTest)
  await page.locator('.menu-item').filter({ hasText: 'Help' }).first().hover()
  await page.locator('#menu-help-experimental').hover(); await page.locator('#menu-help-image-evaluation').click()
}

test('detects two figures with the real API and allows separate design/list selections', async ({ page }) => {
  const errors = []; page.on('pageerror', error => errors.push(error.message))
  const pdf = fixture("print(json.dumps(base64.b64encode(routing_pdf()).decode()))")
  await open(page)
  await page.locator('[data-paper]').setInputFiles({ name: 'paper.pdf', mimeType: 'application/pdf', buffer: Buffer.from(pdf, 'base64') })
  await page.locator('[data-staple-lists]').setInputFiles([
    { name: 'Pointer.csv', mimeType: 'text/csv', buffer: Buffer.from('ACGTCAGTACGTACGA\nTGACGTCAGTACGTAC') },
    { name: 'Barrel.csv', mimeType: 'text/csv', buffer: Buffer.from('ATGCTGACGTCAGTCA\nGTCAGTCAGTACGTCA') },
  ])
  await page.locator('[data-analyze]').click()
  await expect(page.locator('.article-design-card')).toHaveCount(2)
  const cards = page.locator('.article-design-card')
  await cards.nth(0).locator('input[type="checkbox"]').check()
  await cards.nth(1).locator('input[type="checkbox"]').check()
  await expect(page.locator('[data-selection-status]')).toContainText('2 detected design(s) selected')
  await cards.nth(0).locator('select').selectOption({ index: 1 })
  await expect(cards.nth(0).locator('[data-pairing-evidence]')).toContainText('shared caption/list labels only')
  await expect(cards.nth(0).locator('select')).toContainText('Pointer.csv')
  await expect(cards.nth(0).locator('select')).not.toContainText('Barrel.csv')
  await page.locator('[data-scaffold]').fill('ACGTACGTACGT')
  await expect(page.locator('.article-design-card')).toHaveCount(0)
  expect(errors).toEqual([])
})

test('extracts vector paths and shows competing sequence-supported orientations', async ({ page }) => {
  const fixtureData = fixture("p,s,t=calibrated_pdf()\nprint(json.dumps({'pdf':base64.b64encode(p).decode(),'scaffold':s,'staples':'\\n'.join(t)}))")
  await open(page)
  await page.locator('[data-paper]').setInputFiles({ name: 'diagram.pdf', mimeType: 'application/pdf', buffer: Buffer.from(fixtureData.pdf, 'base64') })
  await page.locator('[data-staple-lists]').setInputFiles({ name: 'anonymous.csv', mimeType: 'text/csv', buffer: Buffer.from(fixtureData.staples) })
  await page.locator('[data-scaffold]').fill(fixtureData.scaffold)
  await page.locator('[data-analyze]').click()
  await expect(page.locator('.article-design-card')).toHaveCount(1)
  await page.locator('.article-design-card select').selectOption({ index: 1 })
  await expect(page.locator('[data-pairing-evidence]')).toContainText('12/12 staples matched')
  await expect(page.locator('[data-pairing-evidence]')).toContainText('Direction or register unresolved')
  await expect(page.locator('[data-pairing-evidence] details')).toHaveCount(6)
  await expect(page.locator('[data-reconstruct]')).toBeDisabled()
})

test('blind Pointer image extraction recovers 161 directed staples through the real API', async ({ page }) => {
  const pointer = JSON.parse(execFileSync('uv', ['run', 'python', '-c', `
import base64,gzip,json
from pathlib import Path
from tools.design_archive.pointer_image_benchmark import render_reference
source=json.loads(gzip.decompress(Path('tests/fixtures/cadnano_dietz_pointer.json.gz').read_bytes()))
staples=json.loads(Path('tests/fixtures/dietz_pointer_2017_staples.json').read_text())['sequences']
print(json.dumps({'pdf':base64.b64encode(render_reference(source)).decode(),'staples':staples}))
`], { cwd: root, encoding: 'utf8', maxBuffer: 8 * 1024 * 1024 }))
  await open(page)
  await page.locator('[data-paper]').setInputFiles({ name: 'pointer-image.pdf', mimeType: 'application/pdf', buffer: Buffer.from(pointer.pdf, 'base64') })
  await page.locator('[data-staple-lists]').setInputFiles({ name: 'staples.json', mimeType: 'application/json', buffer: Buffer.from(JSON.stringify(pointer.staples)) })
  await page.locator('[data-analyze]').click()
  await expect(page.locator('.article-design-card')).toHaveCount(1, { timeout: 30000 })
  await page.locator('.article-design-card select').selectOption({ index: 1 })
  await expect(page.locator('[data-routing-recovered]')).toContainText('1 scaffold(s), 161 staples, 1 deletion')
  await expect(page.locator('[data-pairing-evidence]')).toContainText('161/161 staples matched')
  await expect(page.locator('[data-reconstruct]')).toBeDisabled()
})

test('recovers original publication paths and pairs two designs with their tables', async ({ page }) => {
  const published = JSON.parse(execFileSync('uv', ['run', 'python', '-c', `
import base64,json,pymupdf
from pathlib import Path
source=Path('experiments/origami_publication_catalog/assets/sources/twist-supp.pdf')
if not source.exists():
 print('null')
else:
 with pymupdf.open(source) as original, pymupdf.open() as selected:
  for index in (18,19,36,38):selected.insert_pdf(original,from_page=index,to_page=index)
  print(json.dumps(base64.b64encode(selected.tobytes()).decode()))
`], { cwd: root, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 }))
  test.skip(!published, 'Local publication corpus not installed')
  const errors = []; page.on('pageerror', error => errors.push(error.message))
  await open(page)
  await page.locator('[data-paper]').setInputFiles({ name: 'original-publication-pages.pdf', mimeType: 'application/pdf', buffer: Buffer.from(published, 'base64') })
  await page.locator('[data-analyze]').click()
  await expect(page.locator('.article-design-card')).toHaveCount(2, { timeout: 30000 })
  const cards = page.locator('.article-design-card')
  await cards.nth(0).locator('input[type="checkbox"]').check()
  await cards.nth(1).locator('input[type="checkbox"]').check()
  await cards.nth(0).locator('select').selectOption({ label: 'original-publication-pages.pdf · page 3 · 217 oligos · published endpoints and image paths' })
  await cards.nth(1).locator('select').selectOption({ label: 'original-publication-pages.pdf · page 4 · 209 oligos · published endpoints and image paths' })
  await expect(cards.nth(0).locator('[data-publication-routing]')).toContainText('217/217 published staple endpoint pairs')
  await expect(cards.nth(0).locator('[data-publication-routing]')).toContainText('360 unit insertions resolved')
  await expect(cards.nth(0).locator('[data-sequence-search]')).toContainText('16128 direction/shift candidates tested')
  await expect(cards.nth(0).locator('[data-sequence-search]')).toContainText('0 mismatches across 7919 paired bases')
  await expect(cards.nth(1).locator('[data-publication-routing]')).toContainText('209/209 published staple endpoint pairs')
  await expect(cards.nth(1).locator('[data-sequence-search]')).toContainText('p7704: 15408 direction/shift candidates tested')
  await expect(cards.nth(1).locator('[data-sequence-search]')).toContainText('0 mismatches across 7658 paired bases')
  await expect(page.locator('[data-selection-status]')).toContainText('2 detected design(s) selected')
  await expect(page.locator('[data-reconstruct]')).toBeDisabled()
  expect(errors).toEqual([])
})

test('validates monolith and square nut and reports penalized railed bridge loops', async ({ page }) => {
  const published = JSON.parse(execFileSync('uv', ['run', 'python', '-c', `
import base64,json,pymupdf
from pathlib import Path
source=Path('experiments/origami_publication_catalog/assets/sources/shapes-supp.pdf')
if not source.exists():
 print('null')
else:
 with pymupdf.open(source) as original, pymupdf.open() as selected:
  for index in (3,4,5,11,12,13):selected.insert_pdf(original,from_page=index,to_page=index)
  print(json.dumps(base64.b64encode(selected.tobytes()).decode()))
`], { cwd: root, encoding: 'utf8', maxBuffer: 16 * 1024 * 1024 }))
  test.skip(!published, 'Local publication corpus not installed')
  const errors = []; page.on('pageerror', error => errors.push(error.message))
  await open(page)
  await page.locator('[data-paper]').setInputFiles({ name: 'shapes.pdf', mimeType: 'application/pdf', buffer: Buffer.from(published, 'base64') })
  await page.locator('[data-analyze]').click()
  const cards = page.locator('.article-design-card')
  await expect(cards).toHaveCount(3, { timeout: 30000 })
  for (const [index, tablePage, count] of [[0, 4, 144], [1, 5, 148], [2, 6, 197]]) {
    await cards.nth(index).locator('select').selectOption({ label: `shapes.pdf · page ${tablePage} · ${count} oligos · published endpoints and image paths` })
  }
  await expect(cards.nth(0).locator('[data-sequence-search]')).toContainText('0 mismatches across 5880 paired bases')
  await expect(cards.nth(1).locator('[data-sequence-search]')).toContainText('0 mismatches across 4977 paired bases')
  await expect(cards.nth(0).locator('[data-sequence-search]')).toContainText('length-matched library hypotheses')
  await expect(cards.nth(2).locator('[data-sequence-search]')).toContainText('0 mismatches across 6686 paired bases')
  await expect(cards.nth(2).locator('[data-scaffold-loops]')).toContainText('helix 30, base 119: 39 inserted bases')
  await expect(cards.nth(2).locator('[data-scaffold-loops]')).toContainText('helix 42, base 119: 39 inserted bases')
  await expect(cards.nth(2).locator('[data-sequence-confidence]')).toContainText('80.96/100')
  await expect(cards.nth(2).locator('[data-sequence-confidence]')).toContainText('one-base scaffold length discrepancy: −10.00 points')
  await expect(cards.nth(2).locator('[data-length-discrepancy]')).toContainText('7703 bases; sequence: 7704 bases')
  await expect(page.locator('[data-reconstruct]')).toBeDisabled()
  expect(errors).toEqual([])
})
