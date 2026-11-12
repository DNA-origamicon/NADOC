import { test, expect } from '@playwright/test'

// Browser-only fixture: real UI, trajectory controller, companions, Three.js and GIF
// encoder; simulated coordinate responses. No user documents or jobs are modified.
test('trajectory scrubber and collapsed/expanded transport share bounded playback and companions', async ({ page }) => {
  test.setTimeout(90000)
  await page.route('**/__animation-test', route => route.fulfill({ contentType: 'text/html', body: `
    <div id="animation-panel"><div id="animation-panel-heading"><span id="animation-panel-arrow"></span></div>
    <div id="animation-panel-body"><select id="animation-select"></select><div id="animation-kf-list"></div>
    <button id="anim-playpause-btn">▶</button><span id="anim-time-display"></span><input id="anim-scrub" type="range"></div></div>
    <div id="md-jobs-solvent-opts"></div><input id="md-jobs-water-toggle" type="checkbox"><input id="md-jobs-ions-toggle" type="checkbox">
    <input id="md-jobs-box-toggle" type="checkbox"><div id="md-jobs-solvent-status"></div>` }))
  await page.goto('/__animation-test')
  await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const { initAnimationPanel } = await import('/src/ui/animation_panel.js')
    const { initAnimationPlayer } = await import('/src/scene/animation_player.js')
    const { initTrajectoryKeyframes } = await import('/src/scene/trajectory_keyframes.js')
    const { initOxdnaDisplay } = await import('/src/ui/oxdna_display.js')
    const { initMdSolventControls } = await import('/src/ui/md_solvent_controls.js')
    const { initMdSolventOverlay } = await import('/src/scene/md_solvent_overlay.js')
    const { exportVideo } = await import('/src/scene/export_video.js')
    const kf = { id: 'k', is_trajectory: true, trajectory_job_id: 'A', trajectory_engine: 'namd',
      trajectory_stride: 1, trajectory_frame_start: 10, trajectory_frame_end: 12,
      hold_duration_s: 2, transition_duration_s: 0, feature_log_index: null, easing: 'linear' }
    const animation = { id: 'anim', name: 'Trajectory', fps: 10, keyframes: [kf] }
    const design = { animations: [animation], helices: [], strands: [], clusters: [], camera_poses: [],
      feature_log: [], feature_log_cursor: -1, overhangs: [] }
    const proof = window.proof = { downloads: [], companionRequests: [], frames: [], boxFrames: 0 }
    const scene = new THREE.Scene()
    scene.background = new THREE.Color('black')
    scene.add(new THREE.AmbientLight(0xffffff, 3))
    const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 100)
    camera.position.set(0, 0, 4)
    const renderer = new THREE.WebGLRenderer({ preserveDrawingBuffer: true })
    renderer.setSize(128, 128)
    document.body.append(renderer.domElement)
    const overlay = initMdSolventOverlay(scene)
    function pack(ids, options) {
      const n = options.ions ? 1 : 0
      const h = { frame_ids: ids, atomistic: false, n_waters_total: 0, n_ions: n, n_ions_total: 1,
        has_box: !!options.box, shell_nm: null, capped: false, species_table: ['NA'], ion_species: n ? [0] : [],
        per_frame_nw: ids.map(() => 0), n_serials: 0 }
      const hb = new TextEncoder().encode(JSON.stringify(h)), offset = (20 + hb.length + 3) & ~3
      const width = n * 3 + (options.box ? 24 : 0)
      const buf = new ArrayBuffer(offset + ids.length * width * 4), dv = new DataView(buf)
      dv.setUint32(0, 0x4E534C56, true); dv.setUint32(4, 2, true)
      dv.setUint32(8, ids.length, true); dv.setUint32(16, hb.length, true)
      new Uint8Array(buf, 20, hb.length).set(hb)
      const floats = new Float32Array(buf, offset)
      ids.forEach((id, i) => { if (n) floats.set([(id - 11) * 0.15, 0, 0], i * width) })
      return buf
    }
    const companion = initMdSolventControls({ getCurrentRepr: () => 'full',
      getSolventOverlay: () => overlay,
      getBoxOverlay: () => ({ setCorners() { proof.boxFrames++ }, hide() {} }),
      api: {
        getMdSolventMeta: async () => ({ ready: true, n_waters: 0, n_ions: 1, species: { NA: 1 } }),
        getMdFramesSolventBin: async (_job, ids, options) => {
          proof.companionRequests.push({ ids, ions: options.ions, box: options.box })
          if (window.holdCompanion) await new Promise(resolve => { window.finishCompanion = () => { window.holdCompanion = false; resolve() } })
          return pack(ids, options)
        },
      },
    })
    const dr = { clearScalarColors() {}, applyFemPositions(updates) {
      if (updates?.length) proof.frames.push(updates[0].backbone_position[0])
    } }
    const ctrl = initOxdnaDisplay({ designRenderer: dr, api: {
      getOxdnaTrajectory: async (_job, spec) => {
        proof.downloads.push({ start: spec.frameStart, end: spec.frameEnd })
        if (window.holdTrajectory) await new Promise(resolve => { window.finishTrajectory = resolve })
        return { ready: true, n_frames: 3, total_n_frames: 100, frame_start: 10,
          keys: [['h', 0, 'FORWARD']], frames: [10, 11, 12].map(x => [x, 0, 0, 1, 0, 0]) }
      },
    } })
    window.companion = companion
    const trajectories = initTrajectoryKeyframes({ getController: e => e === 'namd' ? ctrl : null,
      getCompanion: e => e === 'namd' ? companion : null,
      pollLoadProgress: async () => ({ active: true, done: 50, total: 100 }), pollMs: 20 })
    let panel
    const controls = { target: new THREE.Vector3(), update() {} }
    const player = initAnimationPlayer({ camera, controls,
      getDesign: () => design, getCameraPoses: () => [], getClusterTransforms: () => [],
      getDesignRenderer: () => dr, getHelixCtrl: () => null,
      getAtomisticRenderer: () => ({ getMode: () => 'off' }), getSurfaceRenderer: () => ({ getMode: () => 'off' }),
      onFetchGeometryBatch: async () => ({ '-1': { nucleotides: [], helix_axes: [] } }),
      trajectoryKeyframes: trajectories, onEvent: event => panel?.onPlayerEvent(event) })
    player.setBounce(false)
    panel = initAnimationPanel({ getState: () => ({ currentDesign: design }), subscribeSlice() {} }, {
      player, renderer, scene, camera, controls,
      captureCurrentCamera: () => ({ position: camera.position.toArray(), up: camera.up.toArray(), target: controls.target.toArray(), fov: camera.fov }),
      trajectoryKeyframes: trajectories, getWorkspacePath: () => 'fixture.nadoc', api: {
        listOxdnaJobs: async () => [], listMdJobs: async () => [{ job_id: 'A', design_source_path: 'fixture.nadoc', status: 'completed' }],
        getMdTrajectoryMeta: async () => ({ ready: true, n_frames: 100 }),
        updateKeyframe: async (_anim, _id, patch) => { Object.assign(kf, patch) },
      } })
    window.exportProof = async () => {
      let blob
      const createURL = URL.createObjectURL, click = HTMLAnchorElement.prototype.click
      URL.createObjectURL = value => { blob = value; return createURL(value) }
      HTMLAnchorElement.prototype.click = () => {}
      try { await exportVideo({ animation, renderer, scene, camera, player, options: { format: 'gif', fps: 10 } }) }
      finally { URL.createObjectURL = createURL; HTMLAnchorElement.prototype.click = click }
      const bitmap = await createImageBitmap(blob)
      const canvas = document.createElement('canvas'); canvas.width = bitmap.width; canvas.height = bitmap.height
      const ctx = canvas.getContext('2d'); ctx.drawImage(bitmap, 0, 0)
      const pixels = ctx.getImageData(0, 0, canvas.width, canvas.height).data
      let colored = 0
      for (let i = 0; i < pixels.length; i += 4) if (pixels[i] > 30 && pixels[i + 2] > 30) colored++
      bitmap.close()
      return { bytes: blob.size, colored, magic: new TextDecoder().decode((await blob.arrayBuffer()).slice(0, 6)) }
    }
  })
  await expect(page.locator('[data-role="trajectory-frame-end"]')).toHaveValue('12')
  expect(await page.evaluate(() => window.proof.downloads)).toEqual([])
  const preview = page.locator('[data-role="trajectory-play"]')
  const header = page.locator('[data-role="trajectory-header-play"]')
  await expect(header).toBeHidden()
  expect(await page.locator('[data-role="trajectory-timeline"]').evaluate(el => el.previousElementSibling === el.parentElement.firstElementChild)).toBe(true)
  const scrub = await page.locator('[data-role="trajectory-scrubber"]').boundingBox()
  const buttons = await page.locator('.trajectory-transport').boundingBox()
  expect(buttons.y).toBeGreaterThanOrEqual(scrub.y + scrub.height)
  const readiness = page.locator('[data-role="animation-readiness"] [role="progressbar"]')
  await page.evaluate(() => { window.holdTrajectory = true })
  await preview.click()
  await expect(readiness).toHaveAttribute('data-loading-percent', '50')
  await expect(readiness).toHaveAttribute('aria-valuenow', '50')
  await page.evaluate(() => { window.holdTrajectory = false; window.finishTrajectory() })
  await expect(readiness).toHaveAttribute('data-ready-percent', '100')
  await expect.poll(() => page.evaluate(() => window.proof.frames.at(-1))).toBe(12)
  expect(await page.evaluate(() => [...new Set(window.proof.frames)].sort())).toEqual([10, 11, 12])
  await expect(preview).toHaveAttribute('aria-label', 'Play trajectory')
  expect(await page.evaluate(() => window.proof.downloads)).toEqual([{ start: 10, end: 12 }])
  await page.evaluate(() => { window.proof.frames = [] })
  await preview.click()
  await expect.poll(() => page.evaluate(() => window.proof.frames.at(-1))).toBe(12)
  expect(await page.evaluate(() => [...new Set(window.proof.frames)].sort())).toEqual([10, 11, 12])
  await expect(preview).toHaveAttribute('aria-label', 'Play trajectory')
  expect(await page.evaluate(() => window.proof.downloads)).toHaveLength(1)
  // Pause expanded, resume collapsed, then stop and seek using the same playhead.
  await preview.click()
  await expect(preview).toHaveAttribute('aria-label', 'Pause trajectory')
  await preview.click()
  const paused = await page.evaluate(() => window.proof.frames.at(-1))
  await page.waitForTimeout(200)
  expect(await page.evaluate(() => window.proof.frames.at(-1))).toBe(paused)
  await page.getByTitle('Collapse keyframe', { exact: true }).click()
  await expect(preview).toBeHidden(); await expect(header).toBeVisible()
  await header.click(); await expect(header).toHaveAttribute('aria-label', 'Pause trajectory')
  await page.getByTitle('Collapse keyframe', { exact: true }).click()
  await expect(preview).toHaveAttribute('aria-label', 'Pause trajectory')
  await page.locator('[data-role="trajectory-stop"]').click()
  await expect.poll(() => page.evaluate(() => window.proof.frames.at(-1))).toBe(10)
  await page.locator('[data-role="trajectory-last"]').click()
  await expect.poll(() => page.evaluate(() => window.proof.frames.at(-1))).toBe(12)
  await page.locator('[data-role="trajectory-first"]').click()
  await expect.poll(() => page.evaluate(() => window.proof.frames.at(-1))).toBe(10)
  await page.locator('[data-role="trajectory-scrubber"]').focus()
  await page.keyboard.press('ArrowRight')
  await expect.poll(() => page.evaluate(() => window.proof.frames.at(-1))).toBe(11)
  await page.locator('[data-role="trajectory-frame-start"]').fill('11')
  await page.locator('[data-role="trajectory-frame-start"]').press('Tab')
  await page.locator('[data-role="trajectory-first"]').click()
  await expect.poll(() => page.evaluate(() => window.proof.frames.at(-1))).toBe(11)
  await page.locator('[data-role="trajectory-stop"]').click()
  await expect.poll(() => page.evaluate(() => window.proof.frames.at(-1))).toBe(11)
  await page.locator('[data-role="trajectory-frame-start"]').fill('10')
  await page.locator('[data-role="trajectory-frame-start"]').press('Tab')
  await page.locator('[data-role="trajectory-first"]').click()
  await expect.poll(() => page.evaluate(() => window.proof.frames.at(-1))).toBe(10)
  for (const label of ['Ions', 'Bounding box']) {
    await page.evaluate(() => { window.holdCompanion = true })
    await page.locator('#animation-kf-list').getByLabel(label, { exact: true }).check()
    await expect(page.locator('[data-role="trajectory-download-status"]')).toContainText(/Preparing|Loading/)
    await page.evaluate(() => window.finishCompanion())
    await expect(page.locator('[data-role="trajectory-download-status"]')).toContainText('Preview paused')
  }
  await page.evaluate(() => { window.proof.frames = []; window.proof.boxFrames = 0 })
  await preview.click()
  await expect.poll(() => page.evaluate(() => window.proof.frames.at(-1))).toBe(12)
  expect(await page.evaluate(() => window.proof.boxFrames)).toBeGreaterThan(0)
  expect(await page.evaluate(() => window.proof.companionRequests.some(r => r.ions && r.box))).toBe(true)
  const held = await page.evaluate(() => window.proof.frames.length)
  await page.waitForTimeout(400)
  expect(await page.evaluate(() => window.proof.frames.length)).toBe(held)
  const gif = await page.evaluate(() => window.exportProof())
  expect(gif.magic).toMatch(/^GIF8[79]a$/)
  expect(gif.bytes).toBeGreaterThan(100)
  expect(gif.colored).toBeGreaterThan(10)
  // Smooth playback uses the same controller, and compilation must capture subframes.
  await page.getByLabel('Smooth playback', { exact: true }).check()
  await page.evaluate(() => { window.proof.frames = [] })
  await page.getByRole('button', { name: 'Play trajectory', exact: true }).filter({ visible: true }).click()
  await expect.poll(() => page.evaluate(() => window.proof.frames.some(x => x > 10 && x < 12 && !Number.isInteger(x)))).toBe(true)
  await page.getByRole('button', { name: 'Stop trajectory', exact: true }).click()
  await expect.poll(() => page.evaluate(() => window.proof.frames.at(-1))).toBe(10)
  await page.evaluate(() => { window.proof.frames = [] })
  // Compile the selected trajectory interval through the real encoder as well.
  await page.getByLabel('Compiled video size').selectOption('720p')
  await page.getByRole('button', { name: 'Compile this trajectory keyframe', exact: true }).click()
  await expect(page.locator('.compile-summary')).toContainText('Keyframe ready', { timeout: 60000 })
  await expect(page.locator('.compile-preview-result')).toBeVisible()
  await expect(page.locator('[data-role="keyframe-compiled-status"]')).toHaveAttribute('data-compiled', 'ready')
  await expect(page.locator('[data-role="animation-compiled-readiness"] [data-keyframe-id="k"]')).toHaveAttribute('data-compiled', 'ready')
  expect(await page.evaluate(() => window.proof.frames.some(x => x > 10 && x < 12 && !Number.isInteger(x)))).toBe(true)
  await page.getByRole('button', { name: 'Play compiled keyframe', exact: true }).click()
  const clipPreview = page.frameLocator('iframe[title="Compiled presentation"]')
  await expect(clipPreview.locator('#jump option')).toHaveCount(1)
  await page.getByRole('button', { name: 'Inspect in 3D', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Return to presentation', exact: true })).toBeVisible()
  await page.getByRole('button', { name: 'Close presentation', exact: true }).click()
  await page.locator('#anim-compile-presentation-btn').click()
  await expect(page.locator('.compile-summary')).toContainText('Ready', { timeout: 60000 })
  const compiled = await page.locator('.compile-download').evaluate(async link => (await fetch(link.href)).text())
  expect(compiled).toContain('data:video/webm;base64,')
  expect(compiled).toContain("connect-src 'none'")
  expect(compiled).toContain('trajectory_smooth_playback')
  await page.getByRole('button', { name: 'Play compiled', exact: true }).click()
  const embedded = page.frameLocator('iframe[title="Compiled presentation"]')
  await embedded.locator('#replay').click()
  await expect(embedded.locator('#status')).toContainText('Held')
  await page.getByRole('button', { name: 'Inspect in 3D', exact: true }).click()
  await expect(page.getByRole('button', { name: 'Return to presentation', exact: true })).toBeVisible()
  expect(await page.evaluate(() => window.proof.frames.at(-1))).toBe(12)
  await page.getByRole('button', { name: 'Return to presentation', exact: true }).click()
  await expect(embedded.locator('#status')).toContainText('Held')
  await page.getByRole('button', { name: 'Close presentation', exact: true }).click()
  const proof = await page.evaluate(() => window.proof)
  expect(proof.downloads.every(r => r.start >= 10 && r.end <= 12)).toBe(true)
  expect(proof.companionRequests.flatMap(r => r.ids).every(i => i >= 10 && i <= 12)).toBe(true)
  expect(proof.frames.every(x => x >= 10 && x <= 12)).toBe(true)
  expect(proof.boxFrames).toBeGreaterThan(0)
  await page.getByLabel('Smooth playback', { exact: true }).uncheck()
  await expect(page.locator('[data-role="keyframe-compiled-status"]')).toHaveAttribute('data-compiled', 'stale')
  await page.evaluate(() => { window.proof.frames = [] })
  await page.locator('[data-role="trajectory-play"]').click()
  await expect.poll(() => page.evaluate(() => window.proof.frames.at(-1))).toBe(12)
  expect(await page.evaluate(() => window.proof.frames.every(Number.isInteger))).toBe(true)
})
