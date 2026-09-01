/**
 * Crossover-arc bookkeeping across an animation.
 *
 * The rest of animation_player.js is untested (1200 LOC of Three.js scene mutation), but
 * this slice is worth pinning because it broke silently and the symptom appeared far from
 * the cause: `applyPositionLerp` — the feature-log geometry lerp — moved every bead and
 * never touched a crossover arc, so playback dragged the structure out from under
 * stationary arcs, and `stop()` never put the beads back at all. Exporting an animation
 * from photo mode then left the arcs welded to the animation's last frame, because
 * `_restoreBaseClusters` recomputes arc endpoints FROM live bead positions.
 *
 * The fakes below model only what the player calls on them.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'
import * as THREE from 'three'

import { initAnimationPlayer } from './animation_player.js'

const HELICES = ['h0', 'h1']

/** One feature-log position's worth of compact geometry, offset so different indices
 *  are distinguishable when they land on the beads. */
function geoAt(pos) {
  const compact = {}
  for (const [hi, h] of HELICES.entries()) {
    compact[h] = { fwd: { bp: [0, 1], bb: [[hi, 0, pos], [hi, 1, pos]], bn: [[0, 0, 1], [0, 0, 1]], sid: ['s0', 's0'] } }
  }
  // helix_axes is an ARRAY of {helix_id, start, end} — an object here makes
  // _bakedFromGeo throw and the bake silently produces nothing.
  const helix_axes = HELICES.map((h, hi) => ({ helix_id: h, start: [hi, 0, pos], end: [hi, 1, pos] }))
  return { nucleotides_compact: compact, helix_axes }
}

function makeHarness({ design, clusterTransforms = [], cameraPoses = [] } = {}) {
  const calls = { arc: [], extArc: [], xover: [], lerp: [], order: [] }

  const helixCtrl = {
    applyPositionLerp: vi.fn((from, to, t, exclude) => {
      calls.lerp.push({ t, exclude: exclude ? [...exclude] : null, from, to })
      calls.order.push('lerp')
    }),
    applyClusterTransform: vi.fn(),
    captureClusterBase: vi.fn(),
    getNucLivePos: () => new THREE.Vector3(),
    getExtParentHelixId: () => null,
  }
  const unfoldView = {
    applyClusterArcUpdate:    vi.fn((ids) => { calls.arc.push([...ids]); calls.order.push('arc') }),
    applyClusterExtArcUpdate: vi.fn((ids) => calls.extArc.push([...ids])),
  }
  const designRenderer = {
    applyClusterCrossoverUpdate: vi.fn((ids) => calls.xover.push([...ids])),
  }
  const trajectoryKeyframes = {
    prepare: vi.fn(async () => new Map()),
    suspend: vi.fn(), setPlaying: vi.fn(), cancel: vi.fn(), invalidate: vi.fn(),
    frameCount: () => 0,
    show: vi.fn(),
    release: vi.fn(() => { calls.order.push('trajRelease') }),
  }

  const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 1000)
  const controls = { target: new THREE.Vector3(), update: vi.fn() }

  const player = initAnimationPlayer({
    camera,
    controls,
    getCameraPoses:       () => cameraPoses,
    getDesign:            () => design,
    getClusterTransforms: () => clusterTransforms,
    getHelixCtrl:         () => helixCtrl,
    getBluntEnds:         () => null,
    getUnfoldView:        () => unfoldView,
    getDesignRenderer:    () => designRenderer,
    getOverhangLinkArcs:  () => null,
    getOverhangUnzipOverlay:    () => null,
    getMultiOverhangStrandAnim: () => null,
    getDesignGeometry:    () => null,
    onFetchGeometryBatch: async (positions) =>
      Object.fromEntries(positions.map(p => [String(p), geoAt(p)])),
    trajectoryKeyframes,
    onFetchAtomisticBatch: null,
    getAtomisticRenderer:  () => ({ getMode: () => 'off' }),
    onFetchSurfaceBatch:   null,
    getSurfaceRenderer:    () => ({ getMode: () => 'off' }),
    onEvent: () => {},
    onTextOverlayUpdate: () => {},
  })

  return { player, calls, helixCtrl, unfoldView, designRenderer, trajectoryKeyframes, camera, controls }
}

describe('independent pose + spin camera channels', () => {
  it('uses the selected pose as the spin perspective instead of clearing/ignoring it', async () => {
    const pose = { id: 'perspective', position: [10, 0, 0], target: [0, 0, 0], up: [0, 1, 0], fov: 30 }
    const h = makeHarness({ design: design(0), cameraPoses: [pose] })
    const animation = {
      id: 'a', name: 'A', fps: 30, loop: false,
      keyframes: [{
        id: 'k', camera_pose_id: 'perspective', feature_log_index: 0,
        transition_duration_s: 1, hold_duration_s: 1, easing: 'linear',
        spin_axis: 'z', spin_rotations: 0.25, spin_invert: false,
      }],
    }

    await h.player.play(animation)
    h.player.seekTo(2)

    // Baked centroid is [0.5, 0.5, 0]. A quarter-turn of the selected pose
    // around it produces these values; spinning the live/default camera cannot.
    expect(h.camera.position.x).toBeCloseTo(1, 5)
    expect(h.camera.position.y).toBeCloseTo(10, 5)
    expect(h.controls.target.x).toBeCloseTo(1, 5)
    expect(h.controls.target.y).toBeCloseTo(0, 5)
    expect(h.camera.fov).toBeCloseTo(30, 5)
    h.player.stop()
  })
})

function design(cursor = 3) {
  return {
    helices: HELICES.map(id => ({ id })),
    feature_log: [],
    feature_log_cursor: cursor,
    cluster_transforms: [],
    strands: [],
    overhang_connections: [],
  }
}

const kf = (extra = {}) => ({
  id: `kf${Math.random()}`.slice(0, 8),
  camera_pose_id: null, feature_log_index: null,
  hold_duration_s: 1, transition_duration_s: 1, easing: 'linear',
  joint_values: {}, binding_states: {}, strand_anim_phi: {},
  ...extra,
})

describe('crossover arcs follow the feature-log lerp', () => {
  let h
  beforeEach(() => { h = makeHarness({ design: design(3) }) })

  it('re-seats the arcs on the beads on every frame the lerp moves them', async () => {
    await h.player.play({ id: 'a', name: 'A', fps: 30, loop: false,
                          keyframes: [kf(), kf({ feature_log_index: 0 })] })
    h.calls.arc.length = 0
    h.calls.xover.length = 0

    h.player.seekTo(1.0)

    // The bug: applyPositionLerp ran and no arc call followed it, so the arcs stayed
    // where they were while the structure moved.
    expect(h.helixCtrl.applyPositionLerp).toHaveBeenCalled()
    expect(h.calls.arc.length).toBeGreaterThan(0)
    expect(h.calls.arc.at(-1)).toEqual(expect.arrayContaining(HELICES))
    expect(h.calls.xover.at(-1)).toEqual(expect.arrayContaining(HELICES))
  })

  it('syncs the arcs ONCE per frame, not once per mover', async () => {
    await h.player.play({ id: 'a', name: 'A', fps: 30, loop: false,
                          keyframes: [kf(), kf({ feature_log_index: 0 })] })
    h.calls.arc.length = 0
    h.player.seekTo(1.0)
    // unfold_view rewrites its whole arc vertex buffer per call — two passes a frame is
    // pure waste at export resolution.
    expect(h.calls.arc.length).toBe(1)
  })

  it('does not sync arcs on a frame where nothing moved the beads', async () => {
    // No keyframe pins a feature-log index and there are no clusters, so the lerp still
    // runs (base state against itself) — the sync is keyed on the lerp having run, which
    // is the honest signal that bead positions were written.
    const bare = makeHarness({ design: design(3) })
    await bare.player.play({ id: 'a', name: 'A', fps: 30, loop: false, keyframes: [kf(), kf()] })
    bare.calls.arc.length = 0
    bare.player.seekTo(1.0)
    expect(bare.calls.arc.length).toBe(1)
  })
})

describe('stop() returns the model to the loaded state', () => {
  it('re-applies the base feature-log state to the beads and re-seats the arcs', async () => {
    const h = makeHarness({ design: design(3) })
    await h.player.play({ id: 'a', name: 'A', fps: 30, loop: false,
                          keyframes: [kf(), kf({ feature_log_index: 0 })] })
    h.player.seekTo(2.0)          // land on the pinned index, away from the loaded state
    h.calls.lerp.length = 0
    h.calls.arc.length = 0

    h.player.stop()

    // Exactly one restoring lerp, and it is the LOADED state (cursor 3) against itself —
    // a set-to-that-state, not an interpolation toward it.
    expect(h.calls.lerp.length).toBe(1)
    const restore = h.calls.lerp[0]
    expect(restore.t).toBe(0)
    expect(restore.from).toBe(restore.to)
    expect(restore.from.posMap.get('h0:0:fwd').z).toBe(3)
    // …and the arcs were told about it, or they would still be on the animated beads.
    expect(h.calls.arc.at(-1)).toEqual(expect.arrayContaining(HELICES))
  })

  it('hands the trajectory controllers back BEFORE restoring the beads', async () => {
    // applyFemPositions(null) reverts the beads to the renderer's base positions; running
    // it after the feature-log restore would overwrite it.
    const h = makeHarness({ design: design(3) })
    await h.player.play({ id: 'a', name: 'A', fps: 30, loop: false,
                          keyframes: [kf(), kf({ feature_log_index: 0 })] })
    h.calls.order.length = 0
    h.player.stop()
    expect(h.calls.order.indexOf('trajRelease')).toBeLessThan(h.calls.order.indexOf('lerp'))
  })

  it('is a no-op when nothing was ever played', () => {
    const h = makeHarness({ design: design(3) })
    h.player.stop()
    expect(h.helixCtrl.applyPositionLerp).not.toHaveBeenCalled()
    expect(h.calls.arc.length).toBe(0)
  })

  it('does not restore twice when stop() is called again', async () => {
    const h = makeHarness({ design: design(3) })
    await h.player.play({ id: 'a', name: 'A', fps: 30, loop: false,
                          keyframes: [kf(), kf({ feature_log_index: 0 })] })
    h.player.stop()
    h.calls.lerp.length = 0
    h.player.stop()
    expect(h.calls.lerp.length).toBe(0)
  })
})

/**
 * `trajectoryKeyframes` is SHARED with the Animations panel's authoring preview, and
 * main.js calls `animPlayer.stop()` on every departure from the Animations tab — even
 * when nothing ever played. Releasing there tore down the user's preview and snapped the
 * model back to design positions, with the panel's needle still claiming frame N.
 */
describe('trajectory ownership — stop() releases only what it took', () => {
  const trajKf = () => kf({ is_trajectory: true, trajectory_job_id: 'J1',
                            trajectory_engine: 'oxdna', trajectory_scope: 'job',
                            trajectory_frame_start: 0, trajectory_frame_end: 9 })

  it('does not release a hold it never took (no play at all)', () => {
    const h = makeHarness({ design: design(3) })
    h.player.stop()
    expect(h.trajectoryKeyframes.release).not.toHaveBeenCalled()
  })

  it('does not release when the animation had no trajectory keyframe', async () => {
    const h = makeHarness({ design: design(3) })
    // prepare() returns an EMPTY map — nothing was loaded, so nothing is owned, even
    // though the panel may be previewing a job through the same module.
    await h.player.play({ id: 'a', name: 'A', fps: 30, loop: false,
                          keyframes: [kf(), kf({ feature_log_index: 0 })] })
    h.player.stop()
    expect(h.trajectoryKeyframes.release).not.toHaveBeenCalled()
  })

  it('DOES release after playing an animation whose bake loaded a job', async () => {
    const h = makeHarness({ design: design(3) })
    h.trajectoryKeyframes.prepare = vi.fn(async () => new Map([['J1', 10]]))
    await h.player.play({ id: 'a', name: 'A', fps: 30, loop: false,
                          keyframes: [trajKf(), kf()] })
    h.player.stop()
    expect(h.trajectoryKeyframes.release).toHaveBeenCalledTimes(1)
  })

  it('releases at most once — a second stop() does not double-release', async () => {
    const h = makeHarness({ design: design(3) })
    h.trajectoryKeyframes.prepare = vi.fn(async () => new Map([['J1', 10]]))
    await h.player.play({ id: 'a', name: 'A', fps: 30, loop: false,
                          keyframes: [trajKf(), kf()] })
    h.player.stop()
    h.player.stop()
    expect(h.trajectoryKeyframes.release).toHaveBeenCalledTimes(1)
  })

  it('still releases BEFORE the feature-log restore when it does own the hold', async () => {
    // The ownership guard must not disturb stop()'s load-bearing order: the trajectory
    // restore is applyFemPositions(null), which the feature-log restore would overwrite.
    const h = makeHarness({ design: design(3) })
    h.trajectoryKeyframes.prepare = vi.fn(async () => new Map([['J1', 10]]))
    await h.player.play({ id: 'a', name: 'A', fps: 30, loop: false,
                          keyframes: [trajKf(), kf({ feature_log_index: 0 })] })
    h.calls.order.length = 0
    h.player.stop()
    expect(h.calls.order.indexOf('trajRelease')).toBeGreaterThanOrEqual(0)
    expect(h.calls.order.indexOf('trajRelease')).toBeLessThan(h.calls.order.indexOf('lerp'))
  })
})
