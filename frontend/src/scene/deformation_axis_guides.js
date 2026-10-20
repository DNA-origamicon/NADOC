import * as THREE from 'three'
import { nativeCorePaired } from '../shared/aptamer.js'
import { C } from './helix_renderer/palette.js'
import { segmentAxisSamples } from './native_axis_samples.js'

// Private sampled polylines; no molecular placement or live scene state.
export function deformationAxisPositions(topology, axes) {
  const positions = []
  for (const helix of topology.helices) {
    if (helix.id?.startsWith('__lnk__')
        || (helix.native_residues?.length && !nativeCorePaired(helix, topology))) continue
    const axis = axes[helix.id]
    if (!axis) throw new Error('Missing checked preview axis')
    const curved = axis.samples?.length > 2
    const paths = curved && axis.segments.length <= 1 ? [axis.samples]
      : axis.segments.map(segment => segmentAxisSamples(helix, segment,
        segment.samples ?? axis.samples, segment.start, segment.end))
    for (const path of paths)
      for (let i = 1; i < path.length; i++) positions.push(...path[i - 1], ...path[i])
  }
  return new Float32Array(positions)
}

export function buildDeformationAxisGuides(topology, axes) {
  let geometry = new THREE.BufferGeometry()
  const line = new THREE.LineSegments(geometry, new THREE.LineBasicMaterial({ color: C.axis }))
  line.name = 'axisLine'
  function update(axes) {
    const positions = deformationAxisPositions(topology, axes)
    const attribute = geometry.getAttribute('position')
    if (attribute?.array.length === positions.length) {
      attribute.array.set(positions); attribute.needsUpdate = true
    } else {
      // Disposal must see the old attribute to release its GPU buffer.
      if (attribute) {
        geometry.dispose()
        geometry = new THREE.BufferGeometry()
        line.geometry = geometry
      }
      geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    }
    geometry.computeBoundingBox(); geometry.computeBoundingSphere()
  }
  try { update(axes) } catch (error) {
    geometry.dispose(); line.material.dispose(); throw error
  }
  return { line, update }
}
