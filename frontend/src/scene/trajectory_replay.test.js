import { expect, it, vi } from 'vitest'
import { initOxdnaDisplay } from '../ui/oxdna_display.js'
import { initTrajectoryKeyframes } from './trajectory_keyframes.js'

// Use the real progressive controller: a retained frame count alone cannot prove
// its page stream survived release (the old mock controller missed this).
it('replays a completed progressive trajectory and can load a new page after release', async () => {
  const total = 50
  const api = {
    progressiveTrajectory: true,
    getTrajectoryMeta: async () => ({ n_frames: total }),
    getOxdnaTrajectory: vi.fn(async (_job, { frameStart = 0, frameEnd = total - 1 }) => ({
      ready: true, n_frames: frameEnd - frameStart + 1, total_n_frames: total,
      frame_start: frameStart, keys: [['h', 0, 'FORWARD']],
      frames: Array.from({ length: frameEnd - frameStart + 1 }, (_, i) => [frameStart + i, 0, 0, 1, 0, 0]),
    })),
  }
  const renderer = { applyFemPositions: vi.fn(), clearScalarColors: vi.fn() }
  const ctrl = initOxdnaDisplay({ designRenderer: renderer, api })
  const tk = initTrajectoryKeyframes({ getController: () => ctrl })
  const animation = { keyframes: [{ trajectory_job_id: 'replay', trajectory_engine: 'namd', trajectory_stride: 20 }] }
  try {
    await tk.prepare(animation, { strict: true })
    expect(await ctrl.ensureTrajectoryFrame(49)).toBe(true)
    tk.show('replay', 'namd', 49)
    tk.release()
    expect(ctrl.isActive()).toBe(false)
    for (let play = 0; play < 2; play++) {
      await tk.prepare(animation, { strict: true })
      expect(await ctrl.ensureTrajectoryFrame(25)).toBe(true)
      tk.show('replay', 'namd', 25)
      expect(renderer.applyFemPositions.mock.lastCall[0][0].backbone_position).toEqual([25, 0, 0])
      tk.release()
    }
    expect(api.getOxdnaTrajectory.mock.calls.filter(([, spec]) => spec.frameStart === 0 && spec.frameEnd === 7)).toHaveLength(1)
  } finally { tk.release(); ctrl.discardForDocumentReset() }
})
