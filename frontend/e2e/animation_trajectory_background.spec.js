import { test, expect } from '@playwright/test'

// Isolated browser UI fixture. Only Vite modules are read; all job/design APIs are
// in-memory fakes. No workspace/session/job files, exports or downloads are created.
// Playwright's configured reporter/teardown handles its own artifacts on failure.
test('bottom Play waits for background frames without pressing Preview', async ({ page }) => {
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
    const animation = { id: 'anim', name: 'Trajectory', fps: 10, keyframes: [kf] }
    const design = { animations: [animation], helices: [], strands: [], clusters: [],
      camera_poses: [], feature_log: [], feature_log_cursor: -1, overhangs: [] }
    window.proof = { downloads: 0, frames: [], events: [] }
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
      getOxdnaTrajectory: async () => {
        window.proof.downloads++
        await new Promise(resolve => { window.finishDownload = resolve })
        return { ready: true, n_frames: 3, keys: [['h', 0, 'FORWARD']],
          frames: [1, 2, 3].map(x => [x, 0, 0, 1, 0, 0]) }
      },
    } })
    const trajectories = initTrajectoryKeyframes({ getController: e => e === 'namd' ? ctrl : null })
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
  await expect.poll(() => page.evaluate(() => window.proof.downloads)).toBe(1)
  expect(await page.evaluate(() => window.proof.frames)).toEqual([])
  await page.locator('#anim-playpause-btn').click()
  await expect(page.locator('#anim-playpause-btn')).toBeDisabled()
  expect(await page.evaluate(() => window.proof.frames)).toEqual([])
  await page.evaluate(() => window.finishDownload())
  await expect.poll(() => page.evaluate(() => [...window.proof.events, document.body.textContent])).toContain('finished')
  expect(await page.evaluate(() => [...new Set(window.proof.frames)])).toEqual([1, 2, 3])
  expect(await page.evaluate(() => window.proof.downloads)).toBe(1)
  // Changing only the trajectory range must rebuild the bottom player's schedule.
  await page.evaluate(() => { window.player.seekTo(0.1); window.keyframe.trajectory_frame_end = 1; window.proof.frames = [] })
  await page.locator('#anim-playpause-btn').click()
  await expect.poll(() => page.evaluate(() => window.proof.events.filter(x => x === 'finished').length)).toBe(2)
  expect(await page.evaluate(() => [...new Set(window.proof.frames)])).toEqual([1, 2])
  expect(errors).toEqual([])
})
