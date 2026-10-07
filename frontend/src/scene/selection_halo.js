import * as THREE from 'three'
import { markAttributeRange } from './attribute_updates.js'

// A single point primitive per selected position. The fragment shader shapes
// its square footprint into a soft disc; no sphere meshes or bloom pass needed.
export function selectionHaloShader(shader) {
  // Use a world-space diameter for both perspective and orthographic views.
  shader.vertexShader = shader.vertexShader.replace('gl_PointSize = size;',
    'gl_PointSize = size * projectionMatrix[1][1];')
  shader.vertexShader = shader.vertexShader.replace('if ( isPerspective ) gl_PointSize *= ( scale / - mvPosition.z );',
    'gl_PointSize *= isPerspective ? ( scale / - mvPosition.z ) : scale;')
  shader.fragmentShader = shader.fragmentShader.replace('#include <alphatest_fragment>', `
    vec2 haloUV = gl_PointCoord * 2.0 - 1.0;
    float haloRadius2 = dot(haloUV, haloUV);
    if (haloRadius2 >= 1.0) discard;
    float haloFade = 1.0 - smoothstep(0.04, 1.0, haloRadius2);
    diffuseColor.a *= haloFade * haloFade;
    #include <alphatest_fragment>
  `)
}

export function installSelectionHalo(material) {
  material.onBeforeCompile = selectionHaloShader
  material.customProgramCacheKey = () => 'nadoc-selection-halo-v1'
  material.needsUpdate = true
  return material
}

export function createSelectionHaloMaterial() {
  return installSelectionHalo(new THREE.PointsMaterial({
    color: 0x48f58a, size: .65, sizeAttenuation: true,
    transparent: true, opacity: .7, blending: THREE.AdditiveBlending,
    depthTest: true, depthWrite: false, toneMapped: false,
  }))
}

export const MAX_SELECTION_HALO_POINTS = 20000

// One bounded 240 KB position buffer, allocated once. Selection edits and motion
// reuse it; drawRange hides unused slots, with no geometry or GPU buffer rebuilds.
export function updateSelectionHaloPositions(geometry, points, stride = 1) {
  const count = Math.ceil(points.length / stride)
  let attr = geometry.getAttribute('position')
  if (count > MAX_SELECTION_HALO_POINTS) throw new RangeError('Selection halo point budget exceeded')
  if (!attr) {
    const capacity = MAX_SELECTION_HALO_POINTS
    attr = new THREE.Float32BufferAttribute(new Float32Array(capacity * 3), 3)
    attr.setUsage(THREE.DynamicDrawUsage)
    geometry.setAttribute('position', attr)
  }
  let first = Infinity, last = -1
  for (let i = 0; i < count; i++) {
    const p = points[i * stride], offset = i * 3
    const x = Math.fround(p.x), y = Math.fround(p.y), z = Math.fround(p.z)
    if (attr.array[offset] !== x || attr.array[offset + 1] !== y || attr.array[offset + 2] !== z) {
      attr.array[offset] = x; attr.array[offset + 1] = y; attr.array[offset + 2] = z
      first = Math.min(first, offset); last = offset + 2
    }
  }
  if (last >= 0) markAttributeRange(attr, first, last - first + 1)
  geometry.setDrawRange(0, count)
  return count
}
