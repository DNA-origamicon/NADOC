import { test, expect } from '@playwright/test'

// Isolated browser UI fixture. Only Vite modules are read; all job/design APIs are
// in-memory fakes. No workspace/session/job files, exports or downloads are created.
// Playwright's configured reporter/teardown handles its own artifacts on failure.
test('three keyframes prepare in order and expose the playable prefix', async ({ page }) => {
  const errors = []
  page.on('pageerror', error => { errors.push(error.message); console.log('Browser error:', error.message) })
  await page.route('**/__animation-test', route => route.fulfill({
    contentType: 'text/html', body: `<div id="animation-panel">
      <div id="animation-panel-heading"><span id="animation-panel-arrow"></span></div>
      <div id="animation-panel-body"><select id="animation-select"></select>
      <div id="animation-kf-list"></div><button id="anim-playpause-btn">▶</button>
      <span id="anim-time-display"></span><input id="anim-scrub" type="range"></div>
      </div><canvas id="proof"></canvas>`,
  }))
  await page.route('http://127.0.0.1:5175/api/**', route => route.abort())
  await page.goto('/__animation-test')
  await page.evaluate(async () => {
    const THREE = await import('/node_modules/three/build/three.module.js')
    const { initAnimationPanel } = await import('/src/ui/animation_panel.js')
    const { initAnimationPlayer } = await import('/src/scene/animation_player.js')
    const { initTrajectoryKeyframes } = await import('/src/scene/trajectory_keyframes.js')
    const { initOxdnaDisplay } = await import('/src/ui/oxdna_display.js')
    const kf = { id: 'k', is_trajectory: true, trajectory_job_id: 'A',
      trajectory_engine: 'namd', trajectory_stride: 1, trajectory_frame_start: 0,
      trajectory_frame_end: 2, hold_duration_s: 0.3, transition_duration_s: 0,
      feature_log_index: null, easing: 'linear' }
    const animation = { id: 'anim', name: 'Trajectory', fps: 10, keyframes: ['A', 'B', 'C'].map(job => ({ ...kf, id: job, trajectory_job_id: job, hold_duration_s: 2 })) }
    const design = { animations: [animation], helices: [], strands: [], clusters: [],
      camera_poses: [], feature_log: [], feature_log_cursor: -1, overhangs: [] }
    window.proof = { downloads: 0, jobs: [], frames: [], events: [] }
    const renderer = { applyFemPositions: updates => {
      if (!updates?.length) return
      const x = updates[0].backbone_position[0]
      window.proof.frames.push(x)
      const canvas = document.getElementById('proof')
      const ctx = canvas.getContext('2d')
      ctx.clearRect(0, 0, canvas.width, canvas.height)
      ctx.fillRect(x * 20, 10, 10, 10)
    }, clearScalarColors() {} }
    const ctrl = initOxdnaDisplay({ designRenderer: renderer, api: {
      getOxdnaTrajectory: async (jobId) => {
        window.proof.jobs.push(jobId)
        window.proof.downloads++
        await new Promise(resolve => { window.finishDownload = resolve })
        return { ready: true, n_frames: 3, keys: [['h', 0, 'FORWARD']],
          frames: [1, 2, 3].map(x => [x, 0, 0, 1, 0, 0]) }
      },
    } })
    const trajectories = initTrajectoryKeyframes({ getController: e => e === 'namd' ? ctrl : null,
      pollLoadProgress: async () => ({ active: true, done: window.loadDone || 0, total: 100 }), pollMs: 50 })
    let panel
    const player = initAnimationPlayer({
      camera: new THREE.PerspectiveCamera(55, 1, 0.1, 100),
      controls: { target: new THREE.Vector3(), update() {} },
      getDesign: () => design, getCameraPoses: () => [], getClusterTransforms: () => [],
      getDesignRenderer: () => renderer, getHelixCtrl: () => null,
      getAtomisticRenderer: () => ({ getMode: () => 'off' }),
      getSurfaceRenderer: () => ({ getMode: () => 'off' }),
      onFetchGeometryBatch: async () => ({ '-1': { nucleotides: [], helix_axes: [] } }),
      trajectoryKeyframes: trajectories,
      onEvent: event => { if (event.type === 'baking_done') window.proof.frames = []; window.proof.events.push(event.type); panel?.onPlayerEvent(event) },
    })
    panel = initAnimationPanel({ getState: () => ({ currentDesign: design }), subscribeSlice() {} }, {
      player, trajectoryKeyframes: trajectories, getWorkspacePath: () => 'fixture.nadoc',
      api: {
        listOxdnaJobs: async () => [],
        listMdJobs: async () => [{ job_id: 'A', design_source_path: 'fixture.nadoc', status: 'completed' }],
        getMdTrajectoryMeta: async () => ({ ready: true, n_frames: 3 }),
        updateKeyframe: async (_animation, _id, patch) => { Object.assign(kf, patch) },
      },
    })
    player.setBounce(false)
    window.player = player
    window.keyframe = kf
  })
  const segments = page.locator('[data-role="animation-readiness"] [role="progressbar"]')
  await expect(segments).toHaveCount(3)
  await expect.poll(() => page.evaluate(() => window.proof.jobs)).toEqual(['A'])
  await expect(segments.nth(1)).toHaveAttribute('data-phase', 'queued')
  for (const percent of [25, 50, 75]) {
    await page.evaluate(value => { window.loadDone = value }, percent)
    await expect(segments.nth(0)).toHaveAttribute('aria-valuenow', String(percent))
    await expect(segments.nth(0)).toContainText(`${percent}% loading`)
  }
  await page.evaluate(() => { window.loadDone = 0; window.finishDownload() })
  await expect(segments.nth(0)).toHaveAttribute('aria-valuenow', '100')
  await expect.poll(() => page.evaluate(() => window.proof.jobs)).toEqual(['A', 'B'])
  await expect(segments.nth(1)).toHaveAttribute('aria-valuenow', '0')
  await expect(segments.nth(2)).toHaveAttribute('data-phase', 'queued')
  await page.locator('#anim-playpause-btn').click()
  await expect.poll(() => page.evaluate(() => window.proof.events.includes('baking_done'))).toBe(true)
  await expect.poll(() => page.evaluate(() => window.proof.frames.length)).toBeGreaterThan(0)
  await page.evaluate(() => window.player.pause())
  await page.evaluate(() => window.finishDownload())
  await expect(segments.nth(1)).toHaveAttribute('aria-valuenow', '100')
  await expect.poll(() => page.evaluate(() => window.proof.jobs)).toEqual(['A', 'B', 'C'])
  await page.evaluate(() => window.finishDownload())
  await expect(segments.nth(2)).toHaveAttribute('aria-valuenow', '100')
  expect(errors).toEqual([])
})
