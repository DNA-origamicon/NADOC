import { bindSurfaceMotion } from './surface_motion.js'
import { zoomMotionFrame } from './zoom_volume_motion.js'

const packed = frame => Float64Array.from(frame.flatMap(n => [
  ...n.backbone_position, n.nx, n.ny, n.nz, n.tx, n.ty, n.tz,
]))

// Engines with exact job surfaces keep ownership. Other displays reuse the same
// nucleotide-frame skinning as trajectory playback and zoom views.
export function createSimulationSurface({ renderer, getSurfaceData, getGeometry, setCGVisible }) {
  let source = null, geometry = null, motion = null
  return {
    apply(updates, colors, liveEntries = []) {
      const mesh = getSurfaceData(), nextGeometry = getGeometry()
      if (!mesh?.vertices?.length || !nextGeometry?.length || !updates?.length) return false
      if (source !== mesh || geometry !== nextGeometry) {
        source = mesh; geometry = nextGeometry
        const rest = zoomMotionFrame(geometry, null)
        motion = bindSurfaceMotion(mesh, rest.map(n => [n.helix_id, n.bp_index, n.direction, n.copy]), packed(rest))
      }
      if (!motion) return false
      renderer.applyDeformedFrame(source, motion.deform(packed(zoomMotionFrame(geometry, updates, liveEntries))))
      if (colors) renderer.applyNucleotideScalarColors?.(colors)
      setCGVisible(false)
      return true
    },
    clear() {
      if (source && motion) renderer.applyDeformedFrame(source, source.vertices)
      source = geometry = motion = null
    },
  }
}
