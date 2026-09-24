import { decodeContainer, encodeContainer } from './package_container.js'
import { sceneChannels, encodeFrame, gzipFrame, CLIP_LIMIT, FRAME_COUNT_LIMIT } from './trajectory_clip.js'

/** Explicit, bounded capture through the existing display controller. Restores the inspected frame. */
export async function prepareTrajectory({ prepared, source, store, from, to, step = 1, fps = 8, signal, onProgress = () => {} }) {
  const { controller, companion, pause } = source ?? {}, info = controller?.trajectoryInfo()
  if (!info || !controller.isActive()) throw new Error('Load a recorded NAMD trajectory in the Dynamics panel first')
  if (![from, to, step].every(Number.isSafeInteger) || from < 0 || to >= info.total || to <= from || step < 1 || Math.floor((to - from) / step) + 1 < 2 || Math.floor((to - from) / step) + 1 > FRAME_COUNT_LIMIT || !Number.isFinite(fps) || fps < 1 || fps > 30) throw new Error('Choose 2–120 frames within the loaded trajectory, at 1–30 samples/s')
  const state = store.getState(), document = state.currentDesign, job = controller.activeJobId(), spec = controller.trajSpec(), alignment = controller.alignment?.()
  if (from < (spec.frameStart ?? 0) || (spec.frameEnd != null && to > spec.frameEnd)) throw new Error('Choose frames inside the loaded trajectory interval')
  if (state.assemblyActive || state.surfaceMode !== 'off' && state.surfaceMode != null) throw new Error('Trajectory clips support part views in Full, VDW, ball-and-stick or stick. Turn off surface/assembly views before preparing.')
  const representation = [state.atomisticMode, state.surfaceMode]
  const sameRepresentation = () => store.getState().atomisticMode === representation[0] && store.getState().surfaceMode === representation[1] && !store.getState().assemblyActive
  const atomistic = state.atomisticMode != null && state.atomisticMode !== 'off'
  if (atomistic && !controller.showFrameForExport) throw new Error('This trajectory controller cannot prepare exact atomic frames')
  const showFrame = async index => {
    if (controller.showFrameForExport) await controller.showFrameForExport(index)
    else controller.showFrame(index)
  }
  if (prepared.captureView().pane) throw new Error('Prepare the trajectory in the main 3D view; multi-view trajectory capture is not available yet')
  if (companion?.plan()?.water) throw new Error('Turn off water before sharing a trajectory')
  const live = () => !signal?.aborted && sameRepresentation() && store.getState().currentDesign === document && controller.activeJobId() === job && controller.isActive() && controller.alignment?.() === alignment && JSON.stringify(controller.trajSpec()) === JSON.stringify(spec)
  const sameSource = () => sameRepresentation() && store.getState().currentDesign === document && controller.activeJobId() === job && controller.isActive() && controller.alignment?.() === alignment && JSON.stringify(controller.trajSpec()) === JSON.stringify(spec)
  const check = () => { if (!live()) throw new Error('Trajectory preparation cancelled because the design or trajectory changed'); if (companion?.plan()?.water) throw new Error('Turn off water before sharing a trajectory') }
  const sourceFrames = [], frames = []; let first, firstExport, base, size = 0
  pause?.()
  try {
    for (let index = from; index <= to; index += step) {
      check()
      if (await controller.ensureTrajectoryFrame(index - (spec.frameStart ?? 0)) === false) throw new Error('Could not prepare the requested trajectory frame')
      check(); await showFrame(index); check()
      if (companion && !await companion.settleFrame(index)) throw new Error('Could not prepare graphene/ion coordinates for this frame')
      check()
      const result = await prepared.exportView(); check()
      if (!result) throw new Error('Another export is in progress')
      const data = decodeContainer(result.buffer), next = sceneChannels(data)
      if (!first) { first = data; firstExport = result; base = next }
      const frame = new Uint8Array(await gzipFrame(encodeFrame(base, next)))
      size += frame.byteLength
      if (size > CLIP_LIMIT) throw new Error('Clip exceeds 128 MiB. Select fewer frames or increase the interval.')
      frames.push(frame); sourceFrames.push(index)
      onProgress(frames.length, Math.floor((to - from) / step) + 1, size)
      await new Promise(resolve => setTimeout(resolve, 0))
    }
    check()
    first.trajectory = { version: 1, encoding: 'absolute-render-patch-gzip', fps, sourceFrames, frames,
      source: { engine: 'namd', job, spec, alignment, water: false }, fidelity: 'Exact exported display coordinates; temporal sampling only' }
    return { ...firstExport, buffer: encodeContainer(first), trajectory: true }
  } finally {
    if (sameSource()) {
      const ready = await controller.ensureTrajectoryFrame(info.frame - 1 - (spec.frameStart ?? 0))
      if (sameSource()) {
        if (ready === false) throw new Error('Could not restore the inspected source frame. Seek to it again in the Dynamics panel.')
        await showFrame(info.frame - 1); await companion?.settleFrame(info.frame - 1)
      }
    }
  }
}
