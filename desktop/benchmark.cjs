/** Installed-app acceptance runner. All mutable state is inside an owned temp
 * directory; original inputs are byte-copied and hashed, never authored/rewritten.
 * Run under scripts/validation_guard.sh. No simulation services are started.
 */
const { _electron: electron } = require('../frontend/node_modules/playwright')
const fs = require('node:fs/promises')
const path = require('node:path')
const crypto = require('node:crypto')
const os = require('node:os')
const { execFileSync } = require('node:child_process')

const argv = process.argv.slice(2)
function arg(name, fallback) { const i = argv.indexOf(name); return i < 0 ? fallback : argv[i + 1] }
const source = path.resolve(arg('--workspace', '.nadoc-workspace'))
const output = path.resolve(arg('--output', '.development-artifacts/desktop-milestones/baseline.json'))
const scratch = process.env.NADOC_TEST_SCRATCH_ROOT || process.env.TMPDIR || os.tmpdir()
const fixture = arg('--fixture', '18hb.nadoc')
const executablePath = arg('--executable', require('electron'))
const packaged = argv.includes('--packaged')
const iterations = Number(arg('--iterations', '3'))
const requireUsefulView = argv.includes('--require-useful-view')
const workflows = argv.includes('--workflows')
const normalLifespan = argv.includes('--normal-lifespan')
const sha = bytes => crypto.createHash('sha256').update(bytes).digest('hex')

async function mirror(relative, workspace, originals) {
  const full = path.resolve(source, relative)
  if (!full.startsWith(source + path.sep)) throw new Error('Fixture dependency escapes source workspace')
  if (originals[relative]) return
  const bytes = await fs.readFile(full)
  originals[relative] = sha(bytes)
  const dest = path.join(workspace, relative)
  await fs.mkdir(path.dirname(dest), { recursive: true })
  await fs.writeFile(dest, bytes)
  const data = JSON.parse(bytes)
  const sources = Object.values(data.sources || {}).concat((data.instances || []).map(i => i.source))
  for (const item of sources) if (item?.type === 'file' && item.path) await mirror(item.path, workspace, originals)
}

async function checkPhoto(page, output, i) {
          await page.evaluate(() => {
            window.__photoOriginals = []
            window.__NADOC_DBG__.scene.traverse(mesh => {
              if (mesh.name === 'backboneSpheres' && mesh.count > 0) {
                const data = mesh.userData.sharedBpXformData || mesh.instanceMatrix.array
                window.__photoOriginals.push({ mesh, geometry: mesh.geometry, material: mesh.material, data, before: data.slice() })
              }
            })
            if (!window.__photoOriginals.length) throw new Error('No backbone meshes for photo check')
            const input = document.getElementById('photo-lighting-enabled')
            input.checked = true; input.dispatchEvent(new Event('change', { bubbles: true }))
          })
          await page.waitForFunction(() => window.__photoMode.isActive() && window.__photoOriginals.every(({ mesh }) => mesh.geometry.type === 'SphereGeometry' && mesh.material.isMeshPhysicalMaterial))
          const photo = await page.evaluate(() => window.nadocDesktopDiagnostics.snapshot())
          await fs.writeFile(output.replace(/\.json$/, `-${i}-photo.png`), Buffer.from(photo.png.split(',')[1], 'base64'))
          await page.evaluate(() => {
            const input = document.getElementById('photo-lighting-enabled')
            input.checked = false; input.dispatchEvent(new Event('change', { bubbles: true }))
            for (const x of window.__photoOriginals) {
              if (x.mesh.geometry !== x.geometry || x.mesh.material !== x.material || !x.data.every((v, j) => Object.is(v, x.before[j]))) throw new Error('Photo exit changed geometry, material or molecular transforms')
            }
            delete window.__photoOriginals
          })
          return true
}

async function run() {
  await fs.mkdir(path.dirname(output), { recursive: true })
  const report = { schema: 1, fixture, source, executablePath, packaged, normalLifespan, iterations, started: new Date().toISOString(),
    platform: { platform: os.platform(), arch: os.arch(), cpu: os.cpus()[0]?.model, memory: os.totalmem() },
    scope: 'Fresh application/profile/backend per sample; OS file cache not flushed. Isolated workspace contains no jobs; validation disables lifespan unless normalLifespan is true (remote autoconnect disabled). Submitted frame plus screenshot, not input-to-photon latency.', samples: [] }
  let failed = false
  for (let i = 0; i < iterations; i++) {
    const owned = await fs.mkdtemp(path.join(scratch, '__e2e__nadoc-desktop-'))
    const workspace = path.join(owned, '__e2e__workspace'), profile = path.join(owned, 'profile')
    const originals = {}, sample = { index: i, fixtureHashes: originals, errors: [], requests: [] }
    report.samples.push(sample)
    let app, memoryTimer
    try {
      await mirror(fixture, workspace, originals)
      const started = performance.now()
      const launchEnv = { ...process.env, NADOC_SHARE_AUTOSTART: '0', NADOC_RUNPOD_AUTOCONNECT: '0' }
      delete launchEnv.ELECTRON_RUN_AS_NODE
      app = await electron.launch({ executablePath, args: [
        ...(!packaged ? [__dirname] : []), ...(argv.includes('--standard-spheres') ? ['--standard-spheres'] : []), ...(!normalLifespan ? ['--validation'] : []), '--workspace', workspace, '--profile', profile,
      ], timeout: 120000, env: launchEnv })
      const page = await app.firstWindow({ timeout: 120000 })
      page.setDefaultTimeout(180000)
      page.on('dialog', dialog => dialog.accept().catch(() => {}))
      page.on('pageerror', e => sample.errors.push(e.message))
      page.on('response', response => { if (response.url().includes('/api/')) sample.requests.push({ url: new URL(response.url()).pathname, status: response.status() }) })
      await page.waitForFunction(() => window.nadocDesktopDiagnostics)
      sample.launchToReadyMs = performance.now() - started
      sample.backendCapabilities = await page.evaluate(() => fetch('/api/desktop/ready').then(r => r.json()))
      if (argv.includes('--require-native') && !sample.backendCapabilities.native_domain_acceleration) throw new Error('Bundled native kernel unavailable')
      sample.electronWorkingSetPeakKiB = 0
      memoryTimer = setInterval(async () => {
        try {
          const value = await app.evaluate(({ app }) => app.getAppMetrics().reduce((sum, p) => sum + p.memory.workingSetSize, 0))
          sample.electronWorkingSetPeakKiB = Math.max(sample.electronWorkingSetPeakKiB, value)
        } catch { /* Closing. */ }
      }, 500)
      await page.evaluate(() => {
        window.__desktopRequests = []
        window.addEventListener('nadoc:api-request', e => window.__desktopRequests.push(e.detail))
        window.__desktopLongTasks = []
        new PerformanceObserver(list => { window.__desktopLongTasks.push(...list.getEntries().map(e => ({ startTime: e.startTime, duration: e.duration }))) }).observe({ type: 'longtask', buffered: false })
      })
      if (argv.includes('--impostors')) await page.evaluate(() => { window.NADOC_IMPOSTORS = true })
      let profiler
      if (argv.includes('--profile-js')) {
        profiler = await page.context().newCDPSession(page)
        await profiler.send('Profiler.enable')
        await profiler.send('Profiler.start')
      }
      const opened = performance.now()
      await page.evaluate(f => window.nadocDesktopDiagnostics.open(f), fixture)
      await page.waitForFunction(() => window.nadocDesktopDiagnostics.loads().current?.status === 'Completed')
      sample.openToUncoveredMs = performance.now() - opened
      if (profiler) {
        const { profile } = await profiler.send('Profiler.stop')
        const byId = new Map(profile.nodes.map(n => [n.id, n.callFrame]))
        const totals = new Map()
        for (let j = 0; j < (profile.samples || []).length; j++) {
          const frame = byId.get(profile.samples[j])
          const key = `${frame.functionName || '(anonymous)'} ${frame.url}:${frame.lineNumber + 1}`
          totals.set(key, (totals.get(key) || 0) + profile.timeDeltas[j])
        }
        sample.openCpuSelfMs = [...totals].sort((a, b) => b[1] - a[1]).slice(0, 30).map(([frame, us]) => ({ frame, ms: us / 1000 }))
        await profiler.detach()
      }
      sample.loads = await page.evaluate(() => window.nadocDesktopDiagnostics.loads())
      sample.inspection = await page.evaluate(() => window.nadocDesktopDiagnostics.inspect())
      sample.gpu = await page.evaluate(() => {
        const gl = document.getElementById('canvas').getContext('webgl2')
        const extension = gl.getExtension('WEBGL_debug_renderer_info')
        return extension ? gl.getParameter(extension.UNMASKED_RENDERER_WEBGL) : null
      })
      sample.apiPhases = await page.evaluate(() => window.__desktopRequests)
      sample.longTasks = await page.evaluate(() => window.__desktopLongTasks)
      // Outside measured interval. The whole-window image proves overlays really
      // disappeared; the canvas image is separately inspected for molecular content.
      const imagePath = output.replace(/\.json$/, `-${i}.png`)
      await page.evaluate(() => window.nadocDesktopDiagnostics.snapshot())
      await page.screenshot({ path: imagePath })
      const nativeImage = await app.evaluate(async ({ BrowserWindow }) => (await BrowserWindow.getAllWindows()[0].webContents.capturePage()).toPNG().toString('base64'))
      await fs.writeFile(output.replace(/\.json$/, `-${i}-window.png`), Buffer.from(nativeImage, 'base64'))
      sample.screenshot = imagePath
      const snapshot = await page.evaluate(() => window.nadocDesktopDiagnostics.snapshot())
      const canvasPath = output.replace(/\.json$/, `-${i}-canvas.png`)
      await fs.writeFile(canvasPath, Buffer.from(snapshot.png.split(',')[1], 'base64'))
      sample.canvasScreenshot = canvasPath
      sample.pixelEvidence = JSON.parse(execFileSync(path.resolve(__dirname, '../.venv/bin/python'), ['-c',
        'from PIL import Image; import sys,json; im=Image.open(sys.argv[1]).convert("RGB"); bg=im.getpixel((0,0)); pts=[(i%im.width,i//im.width) for i,p in enumerate(im.getdata()) if max(abs(a-b) for a,b in zip(p,bg))>25]; print(json.dumps({"pixels":len(pts),"span_x":max((p[0] for p in pts),default=0)-min((p[0] for p in pts),default=0),"span_y":max((p[1] for p in pts),default=0)-min((p[1] for p in pts),default=0)}))', canvasPath], { encoding: 'utf8' }))
      sample.usefulView = sample.pixelEvidence.pixels >= 100 && Math.max(sample.pixelEvidence.span_x, sample.pixelEvidence.span_y) >= 80
      if (requireUsefulView && !sample.usefulView) throw new Error('Rendered scene is blank or too small to inspect')
      // Actual camera gesture, with before/after pose evidence.
      const before = sample.inspection.camera
      const canvas = page.locator('#canvas')
      const box = await canvas.boundingBox()
      await page.mouse.move(box.x + box.width * .85, box.y + box.height * .2)
      await page.mouse.down({ button: 'right' }); await page.mouse.move(box.x + box.width * .65, box.y + box.height * .35, { steps: 8 }); await page.mouse.up({ button: 'right' })
      await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
      sample.cameraMoved = JSON.stringify(before) !== JSON.stringify((await page.evaluate(() => window.nadocDesktopDiagnostics.inspect())).camera)
      if (!sample.cameraMoved) throw new Error('Actual camera gesture did not change camera')
      const reference = arg('--reference-view') ? JSON.parse(await fs.readFile(arg('--reference-view'), 'utf8')).samples[0] : null
      if (argv.includes('--matched-camera')) {
        await page.evaluate(pose => {
          const { camera, controls } = window.__NADOC_DBG__
          controls.target.fromArray(pose.target); camera.position.fromArray(pose.position)
          camera.up.fromArray(pose.up); camera.lookAt(controls.target); controls.update()
        }, reference?.inspection.camera || before)
      }
      if (workflows && /\.nass$/i.test(fixture)) {
        sample.workflows = {}
        await page.evaluate(() => {
          window.__nextAssemblyBuild = new Promise(resolve => window.__NADOC_DBG__.assemblyRenderer.onRebuildComplete(() =>
            requestAnimationFrame(() => requestAnimationFrame(resolve))))
        })
        const fullStart = performance.now()
        await page.keyboard.press('F4')
        await page.evaluate(() => window.__nextAssemblyBuild)
        await page.waitForFunction(() => window.__NADOC_DBG__.store.getState().currentAssembly.instances.every(i => i.representation === 'full'))
        sample.workflows.fullChoiceToFrameMs = performance.now() - fullStart
        sample.workflows.fullInspection = await page.evaluate(() => window.nadocDesktopDiagnostics.inspect())
        sample.workflows.frameSample = await page.evaluate(() => window.__NADOC_DBG__.sampleFps(1000))
        await page.screenshot({ path: output.replace(/\.json$/, `-${i}-full.png`) })
        if (argv.includes('--detail-view')) {
          await page.evaluate(({ referencePose, distanceFactor }) => {
            const { camera, controls, assemblyRenderer, THREE } = window.__NADOC_DBG__
            const centers = assemblyRenderer.getInstanceCenters()
            const center = centers[Math.floor(centers.length / 2)].center
            const size = assemblyRenderer.getBoundingBox().getSize(new THREE.Vector3()).length() / centers.length
            controls.target.copy(center)
            camera.position.copy(center).add(new THREE.Vector3(1, .65, 1).normalize().multiplyScalar(size * distanceFactor))
            camera.up.set(0, 1, 0)
            if (referencePose) { controls.target.fromArray(referencePose.target); camera.position.fromArray(referencePose.position); camera.up.fromArray(referencePose.up) }
            camera.lookAt(controls.target); controls.update()
          }, { referencePose: reference?.workflows.detailInspection.camera, distanceFactor: Number(arg('--detail-distance', '2')) })
          sample.workflows.detailInspection = await page.evaluate(() => window.nadocDesktopDiagnostics.inspect())
          sample.workflows.detailFrames = await page.evaluate(() => window.__NADOC_DBG__.sampleFps(1500))
          const detail = await page.evaluate(() => window.nadocDesktopDiagnostics.snapshot())
          await fs.writeFile(output.replace(/\.json$/, `-${i}-detail.png`), Buffer.from(detail.png.split(',')[1], 'base64'))
        }
        if (argv.includes('--photo-check')) sample.workflows.photoRestore = await checkPhoto(page, output, i)
        const row = page.locator('#assembly-instance-list [data-instance-id]').first()
        const instanceId = await row.getAttribute('data-instance-id')
        const selectStart = performance.now()
        await row.click({ position: { x: 120, y: 10 } })
        await page.waitForFunction(id => window.__NADOC_DBG__.store.getState().activeInstanceId === id, instanceId)
        sample.workflows.selectMs = performance.now() - selectStart
        // A reversible display edit, then the real assembly undo shortcut.
        await row.locator('button[title="Hide"]').click()
        await page.waitForFunction(id => window.__NADOC_DBG__.store.getState().currentAssembly.instances.find(i => i.id === id).visible === false, instanceId)
        await page.keyboard.press('Control+z')
        await page.waitForFunction(id => window.__NADOC_DBG__.store.getState().currentAssembly.instances.find(i => i.id === id).visible !== false, instanceId)
        sample.workflows.hideUndo = true
        await page.locator('#menu-item-view > button').click()
        await page.locator('#menu-item-view .submenu-item').filter({ hasText: 'Coloring' }).hover()
        await page.locator('#menu-view-coloring-strand').click()
        await page.waitForFunction(() => window.__NADOC_DBG__.store.getState().coloringMode === 'strand')
        sample.workflows.recolor = true
        const saved = page.waitForResponse(r => new URL(r.url()).pathname === '/api/assembly/save' && r.request().method() === 'POST' && r.ok())
        await page.keyboard.press('Control+s')
        await saved
        const stored = JSON.parse(await fs.readFile(path.join(workspace, fixture), 'utf8'))
        if (stored.instances_v2.length !== 30 || !stored.feature_log.length) throw new Error('Saved assembly lost instances/history')
        await page.evaluate(f => window.nadocDesktopDiagnostics.open(f), fixture)
        await page.waitForFunction(() => window.__NADOC_DBG__.store.getState().currentAssembly.instances.length === 30)
        sample.workflows.saveReopen = true
      }
      if (workflows && /\.nadoc$/i.test(fixture)) {
        sample.workflows = {}
        const hit = await page.evaluate(() => {
          const { camera, designRenderer } = window.__NADOC_DBG__
          const rect = document.getElementById('canvas').getBoundingClientRect()
          const points = designRenderer.getBackboneEntries().filter(e => e.instMesh.name === 'backboneSpheres').map(e => e.pos.clone().project(camera)).filter(p => Math.abs(p.x) < .8 && Math.abs(p.y) < .8 && p.z > -1 && p.z < 1).sort((a, b) => a.z - b.z)
          if (!points.length) throw new Error('No visible backbone target')
          return { x: rect.x + (points[0].x + 1) * rect.width / 2, y: rect.y + (1 - points[0].y) * rect.height / 2 }
        })
        await page.mouse.click(hit.x, hit.y)
        await page.waitForFunction(() => window.__NADOC_DBG__.store.getState().selection.items.length > 0)
        sample.workflows.backbonePick = true
        if (argv.includes('--photo-check')) sample.workflows.photoRestore = await checkPhoto(page, output, i)
      }
      if (argv.includes('--cancel-check')) {
        let releaseResponse, reachedResponse
        const held = new Promise(resolve => { releaseResponse = resolve })
        const reached = new Promise(resolve => { reachedResponse = resolve })
        const endpoint = /\.nass$/i.test(fixture) ? '**/api/library/open-assembly' : '**/api/library/open-part'
        await page.route(endpoint, async route => {
          reachedResponse()
          await held
          await route.continue()
        })
        try {
          await page.evaluate(f => { window.__cancelOpen = window.nadocDesktopDiagnostics.open(f).catch(e => ({ error: e.message })) }, fixture)
          await Promise.race([reached, new Promise((_, reject) => setTimeout(() => reject(new Error('No held open response')), 10000))])
          await page.locator('#flp-cancel').click()
          const settledResponse = page.waitForResponse(r => r.url().endsWith(endpoint.slice(2)) && r.request().method() === 'POST')
          releaseResponse()
          if (!(await settledResponse).ok()) throw new Error('Cancelled import did not finish successfully before discard')
          await page.evaluate(() => window.__cancelOpen)
          await page.waitForFunction(() => window.nadocDesktopDiagnostics.loads().current?.status === 'Cancelled')
          await page.waitForFunction(() => !document.getElementById('welcome-screen').classList.contains('hidden') && !window.__NADOC_DBG__.store.getState().currentAssembly)
          sample.cancelledOpen = true
        } finally { releaseResponse(); await page.unroute(endpoint) }
      }
      if (sample.errors.length) throw new Error('Renderer exceptions: ' + sample.errors.join('; '))
      sample.passed = true
    } catch (error) {
      sample.failure = error.stack
      failed = true
    } finally {
      clearInterval(memoryTimer)
      await fs.writeFile(output, JSON.stringify(report, null, 2))
      if (app) {
        // App close must exercise the host's graceful backend shutdown.
        const backendPids = app.process().pid
        sample.hostPid = backendPids
        if (normalLifespan) await app.evaluate(({ dialog }) => { dialog.showMessageBoxSync = () => 1 })
        await app.close().catch(error => { sample.shutdownError = error.message; failed = true })
      }
      for (const [relative, hash] of Object.entries(originals)) {
        if (sha(await fs.readFile(path.join(source, relative))) !== hash) { sample.sourceChanged = relative; failed = true }
      }
      const logPath = path.join(profile, 'logs', 'desktop.log')
      try {
        const log = await fs.readFile(logPath, 'utf8')
        sample.cleanShutdown = log.includes('shutdown-complete')
        const pids = [...log.matchAll(/"event":"backend-started","pid":(\d+)/g)].map(m => Number(m[1]))
        sample.backendStopped = pids.every(pid => { try { process.kill(pid, 0); return false } catch (e) { return e.code === 'ESRCH' } })
        if (!sample.cleanShutdown || !sample.backendStopped) failed = true
        if (!sample.passed) await fs.writeFile(output.replace(/\.json$/, `-${i}.log`), log)
      } catch (e) { sample.logError = e.message; failed = true }
      await fs.rm(owned, { recursive: true, force: true })
      sample.cleaned = !(await fs.stat(owned).catch(() => null))
      await fs.writeFile(output, JSON.stringify(report, null, 2))
    }
  }
  report.finished = new Date().toISOString()
  report.passed = !failed
  await fs.writeFile(output, JSON.stringify(report, null, 2))
  console.log(JSON.stringify({ output, passed: report.passed, samples: report.samples.map(s => ({ openMs: s.openToUncoveredMs, failure: s.failure })) }))
  if (failed) process.exitCode = 1
}
run().catch(error => { console.error(error); process.exitCode = 1 })
