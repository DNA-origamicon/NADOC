import { expect, it, vi } from 'vitest'
import { initAnimationPanel } from './animation_panel.js'
it('shows selected trajectory readiness before the job discovery requests finish', async () => {
  document.body.innerHTML = `<div id="animation-panel"><div id="animation-panel-heading"><span id="animation-panel-arrow"></span></div><div id="animation-panel-body"><select id="animation-select"></select><div id="animation-kf-list"></div><button id="anim-playpause-btn"></button><span id="anim-time-display"></span><input id="anim-scrub" type="range"></div></div>`
  const kf = { id: 'k', is_trajectory: true, trajectory_job_id: 'a', trajectory_engine: 'oxdna', trajectory_scope: 'job', hold_duration_s: 2, transition_duration_s: 0 }
  const design = { animations: [{ id: 'anim', name: 'Animation', fps: 30, keyframes: [kf] }], helices: [], strands: [], clusters: [], camera_poses: [], feature_log: [], feature_log_cursor: -1, overhangs: [] }
  let release
  const pending = new Promise(resolve => { release = resolve })
  const api = { listOxdnaJobs: vi.fn(() => pending), listMdJobs: vi.fn(() => pending), getOxdnaTrajectoryMeta: vi.fn(async () => ({ ready: true, n_frames: 3 })) }
  const player = new Proxy({}, { get: () => () => false })
  const trajectories = { prefetch: vi.fn(async (_anim, { onProgress } = {}) => {
    onProgress?.({ jobId: 'a', phase: 'ready', done: 3, total: 3 })
    return [{ ok: true, n_frames: 3 }]
  }) }
  initAnimationPanel({ getState: () => ({ currentDesign: design }), subscribeSlice() {} }, { api, player, trajectoryKeyframes: trajectories })
  try {
    await vi.waitFor(() => expect(document.querySelector('[data-role="trajectory-download-status"]').textContent).toBe('Trajectory preview frames ready'))
    expect(api.getOxdnaTrajectoryMeta).toHaveBeenCalled()
    expect(api.listOxdnaJobs).toHaveBeenCalledWith({ waitForIdle: false })
    expect(api.listMdJobs).toHaveBeenCalledWith({ waitForIdle: false })
    expect(document.body.textContent).toContain('Loading jobs')
  } finally { release([]); await pending }
})
