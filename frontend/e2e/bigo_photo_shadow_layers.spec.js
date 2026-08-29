import { test, expect } from '@playwright/test'
import { existsSync } from 'node:fs'
import { resolve } from 'node:path'

const PART = resolve(process.cwd(), '..', 'workspace', 'BigO.nadoc')
const ASSEMBLY = resolve(process.cwd(), '..', 'workspace', 'BigO-poly.nass')
test.skip(!existsSync(PART) || !existsSync(ASSEMBLY), 'BigO strict-parity fixtures are missing')

async function openBigO(page, kind) {
  const assembly = kind === 'assembly'
  await page.goto(`/?doc=__e2e__bigo-shadow-${kind}&open=${assembly ? 'BigO-poly.nass' : 'BigO.nadoc'}&open-type=${assembly ? 'assembly' : 'design'}`)
  await page.waitForFunction(expected => {
    const state = window.__NADOC_DBG__?.store.getState()
    return expected === 'assembly'
      ? state?.assemblyActive && (state.currentAssembly?.instances?.length ?? state.currentAssembly?.instances_v2?.length) === 1
      : !state?.assemblyActive && (state?.currentGeometry?.length ?? 0) > 0
  }, kind, { timeout: 60_000 })
  if (!assembly) {
    await page.evaluate(async () => window.__nadocTest.setRepresentation('cylinders'))
    await page.waitForTimeout(750)
  }
  // Colour is an input to every lighting contribution. Pin it explicitly so a
  // remembered UI mode cannot be misdiagnosed as a shadow-path difference.
  await page.evaluate(() => {
    const store = window.__NADOC_DBG__.store
    store.setState({ coloringMode: 'base' })
    store.setState({ coloringMode: 'strand' })
  })
  await page.waitForTimeout(750)
  await page.locator('#photo-tab-btn').click()
  await page.waitForFunction(() => window.__photoMode?.getDiagnostics?.().active)
  await page.evaluate(() => {
    const p = window.__photoMode
    p.setBackground('color', '#ffffff')
    p.setOutline(false)
    p.setDepthCue(false)
    p.setPinLights(true)
    p.setKeyShadowMapSize(1024)
  })
}

async function setPose(page, pose = null) {
  return page.evaluate(input => {
    const p = window.__photoMode
    const d = p.getDiagnostics()
    const { camera, controls } = window.__NADOC_DBG__
    const center = input?.center ?? d.bounds.center
    const radius = input?.radius ?? d.bounds.radius
    controls.target.fromArray(center)
    camera.position.set(center[0] + radius * 1.45, center[1] + radius * 0.8, center[2] + radius * 2.8)
    camera.lookAt(controls.target)
    controls.update()
    p._syncFrame()
    return { center, radius }
  }, pose)
}

async function configureLayer(page, layer) {
  await page.evaluate(name => {
    const p = window.__photoMode
    p.setFloor(false)
    p.setStudioEnvironment(false)
    p.setKeyShadow(false)
    p.setFillIntensity(0)
    p.setAmbientIntensity(0)
    p.setKeyIntensity(0)
    if (name === 'ambient') p.setAmbientIntensity(0.15)
    if (name === 'key-unshadowed') { p.setAmbientIntensity(0.15); p.setKeyIntensity(2) }
    if (name === 'key-shadowed' || name === 'floor-shadow') {
      p.setAmbientIntensity(0.15); p.setKeyIntensity(2); p.setKeyShadow(true)
    }
    if (name === 'floor-shadow') p.setFloor(true)
    if (name === 'studio') p.setStudioEnvironment(true)
  }, layer)
  await page.waitForTimeout(500)
}

async function captureCanvas(page) {
  const box = await page.locator('#canvas').boundingBox()
  return page.screenshot({ clip: box })
}

async function imageDelta(page, a, b) {
  return page.evaluate(async ([a64, b64]) => {
    const decode = async b64 => {
      const bmp = await createImageBitmap(await (await fetch(`data:image/png;base64,${b64}`)).blob())
      const canvas = new OffscreenCanvas(bmp.width, bmp.height)
      const ctx = canvas.getContext('2d')
      ctx.drawImage(bmp, 0, 0)
      return ctx.getImageData(0, 0, bmp.width, bmp.height)
    }
    const [ia, ib] = await Promise.all([decode(a64), decode(b64)])
    let sum = 0, changed = 0, max = 0
    for (let i = 0; i < ia.data.length; i += 4) {
      const delta = Math.max(
        Math.abs(ia.data[i] - ib.data[i]),
        Math.abs(ia.data[i + 1] - ib.data[i + 1]),
        Math.abs(ia.data[i + 2] - ib.data[i + 2]),
      )
      sum += delta
      max = Math.max(max, delta)
      if (delta > 2) changed++
    }
    const pixels = ia.width * ia.height
    return { pixels, changed, changedFraction: changed / pixels, meanMaxChannelDelta: sum / pixels, max }
  }, [a.toString('base64'), b.toString('base64')])
}

test('isolates every BigO photomode lighting and shadow contribution', async ({ browser }, testInfo) => {
  test.setTimeout(600_000)
  const pages = {}
  const shots = { design: {}, assembly: {} }
  const report = { diagnostics: {}, crossPath: {}, contribution: {} }
  let commonPose

  for (const kind of ['design', 'assembly']) {
    const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
    const page = await context.newPage()
    pages[kind] = { page, context }
    await openBigO(page, kind)
    commonPose = await setPose(page, commonPose)
    report.diagnostics[kind] = await page.evaluate(() => window.__photoMode.getDiagnostics())
    report.diagnostics[kind].colorBuffers = await page.evaluate(() => {
      const rows = []
      window.__NADOC_DBG__.scene.traverse(object => {
        const data = object.userData?.sharedSegmentColorData ?? object.instanceColor?.array
        if (!data || !object.visible || object.count <= 0) return
        let sum = 0, min = Infinity, max = -Infinity
        const stride = object.userData?.sharedSegmentColorData ? 4 : 3
        const n = Math.min(object.count, Math.floor(data.length / stride))
        for (let i = 0; i < n; i++) for (let c = 0; c < 3; c++) {
          const value = data[i * stride + c]
          sum += value; min = Math.min(min, value); max = Math.max(max, value)
        }
        rows.push({ name: object.name, count: n, mean: sum / Math.max(1, n * 3), min, max })
      })
      return rows
    })
    for (const layer of ['unlit', 'ambient', 'key-unshadowed', 'key-shadowed', 'floor-shadow', 'studio']) {
      await configureLayer(page, layer)
      shots[kind][layer] = await captureCanvas(page)
    }
  }

  for (const layer of Object.keys(shots.design)) {
    report.crossPath[layer] = await imageDelta(pages.design.page, shots.design[layer], shots.assembly[layer])
  }
  for (const kind of ['design', 'assembly']) {
    report.contribution[kind] = {
      ambient: await imageDelta(pages[kind].page, shots[kind].unlit, shots[kind].ambient),
      keyLight: await imageDelta(pages[kind].page, shots[kind].ambient, shots[kind]['key-unshadowed']),
      keyShadow: await imageDelta(pages[kind].page, shots[kind]['key-unshadowed'], shots[kind]['key-shadowed']),
      floor: await imageDelta(pages[kind].page, shots[kind]['key-shadowed'], shots[kind]['floor-shadow']),
      studio: await imageDelta(pages[kind].page, shots[kind].unlit, shots[kind].studio),
    }
  }

  await testInfo.attach('bigo-shadow-layer-audit.json', {
    body: JSON.stringify(report, null, 2), contentType: 'application/json',
  })
  console.log('BIGO_SHADOW_LAYER_AUDIT', JSON.stringify({
    crossPath: report.crossPath, contribution: report.contribution,
    colors: Object.fromEntries(Object.entries(report.diagnostics)
      .map(([kind, value]) => [kind, value.colorBuffers])),
  }))
  expect(report.contribution.design.keyShadow.changed).toBeGreaterThan(0)
  expect(report.contribution.assembly.keyShadow.changed).toBeGreaterThan(0)
  for (const [layer, delta] of Object.entries(report.crossPath)) {
    expect(delta.changedFraction, `${layer} changed-pixel fraction`).toBeLessThan(0.01)
    expect(delta.meanMaxChannelDelta, `${layer} mean channel delta`).toBeLessThan(0.75)
  }
  for (const contribution of ['ambient', 'keyLight', 'keyShadow', 'floor', 'studio']) {
    const design = report.contribution.design[contribution].meanMaxChannelDelta
    const assembly = report.contribution.assembly[contribution].meanMaxChannelDelta
    const relative = Math.abs(design - assembly) / Math.max(design, assembly, 1e-6)
    expect(relative, `${contribution} relative contribution mismatch`).toBeLessThan(0.10)
  }

  await Promise.all(Object.values(pages).map(({ context }) => context.close()))
})
