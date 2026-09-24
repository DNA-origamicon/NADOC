import * as THREE from 'three'

const compiledUniforms = new WeakMap()

export function hullCutoutSpec(volumes = []) {
  return volumes.filter(v => v.enabled !== false).map(v => {
    const lo = new THREE.Vector3(...v.min_corner), hi = new THREE.Vector3(...v.max_corner)
    const inverse = new THREE.Matrix4().compose(lo.clone().add(hi).multiplyScalar(.5), new THREE.Quaternion(...(v.rotation ?? [0, 0, 0, 1])), new THREE.Vector3(1, 1, 1)).invert()
    return { inverse: inverse.toArray(), half: hi.sub(lo).multiplyScalar(.5).toArray(), hex: v.shape === 'hexagonal' }
  })
}
export function validateHullCutouts(value) {
  if (!Array.isArray(value) || value.length > 64 || value.some(v => !v ||
    !Array.isArray(v.inverse) || v.inverse.length !== 16 || !v.inverse.every(Number.isFinite) ||
    !Array.isArray(v.half) || v.half.length !== 3 || !v.half.every(x => Number.isFinite(x) && x > 0) || typeof v.hex !== 'boolean')) {
    throw new Error('Invalid hull volume cutouts (maximum 64)')
  }
}
export function pointInHullCutout(point, spec) {
  return spec.some(v => {
    const p = point.clone().applyMatrix4(new THREE.Matrix4().fromArray(v.inverse)), [x, y, z] = p.toArray().map(Math.abs), [hx, hy, hz] = v.half
    const r = Math.min(hx, hy)
    return z <= hz && (v.hex ? x <= r && y <= Math.sqrt(3) * r / 2 && Math.sqrt(3) * x + y <= Math.sqrt(3) * r : x <= hx && y <= hy)
  })
}
const uniforms = spec => ({
  hullInverse: { value: spec.map(v => new THREE.Matrix4().fromArray(v.inverse)) },
  hullHalf: { value: spec.map(v => new THREE.Vector3(...v.half)) },
  hullHex: { value: spec.map(v => v.hex ? 1 : 0) },
})
export function hullCutoutShader(shader) {
  const spec = this.userData.hullCutouts
  const held = compiledUniforms.get(this) ?? uniforms(spec)
  Object.assign(shader.uniforms, held)
  compiledUniforms.set(this, held)
  if (!spec?.length) return
  const varying = 'varying vec3 vHullOrigin; varying vec3 vHullDirection;\n'
  shader.vertexShader = varying + `mat3 hullInverse3(mat3 m) {
    vec3 a = cross(m[1], m[2]), b = cross(m[2], m[0]), c = cross(m[0], m[1]);
    return mat3(vec3(a.x,b.x,c.x), vec3(a.y,b.y,c.y), vec3(a.z,b.z,c.z)) / dot(m[0],a);
  }\n` + shader.vertexShader
  shader.vertexShader = shader.vertexShader.replace('#include <project_vertex>', `#include <project_vertex>
    vec4 hullPoint = vec4(transformed, 1.0);
    #ifdef USE_INSTANCING
      hullPoint = instanceMatrix * hullPoint;
    #endif
    mat3 hullViewInverse = hullInverse3(mat3(modelViewMatrix));
    vHullOrigin = hullViewInverse * ((isOrthographic ? vec3(mvPosition.xy, 0.0) : vec3(0.0)) - modelViewMatrix[3].xyz);
    vHullDirection = hullPoint.xyz - vHullOrigin;`)
  shader.fragmentShader = varying + `
    uniform mat4 hullInverse[${spec.length}];
    uniform vec3 hullHalf[${spec.length}];
    uniform float hullHex[${spec.length}];
    bool hullClip(vec3 n, float h, vec3 origin, vec3 dir, inout vec2 interval) {
      float speed = dot(n, dir), distance = h - dot(n, origin);
      if (abs(speed) < 0.00000001) return distance >= 0.0;
      float t = distance / speed;
      if (speed > 0.0) interval.y = min(interval.y, t); else interval.x = max(interval.x, t);
      return interval.x <= interval.y;
    }
    bool hullRay(vec3 origin, vec3 dir, vec3 halfSize, bool hexagonal) {
      float r = min(halfSize.x, halfSize.y);
      vec3 h = hexagonal ? vec3(r, 0.866025404 * r, halfSize.z) : halfSize;
      vec2 interval = vec2(0.0, 1.0e20);
      if (!hullClip(vec3(1,0,0), h.x, origin, dir, interval) || !hullClip(vec3(-1,0,0), h.x, origin, dir, interval) ||
          !hullClip(vec3(0,1,0), h.y, origin, dir, interval) || !hullClip(vec3(0,-1,0), h.y, origin, dir, interval) ||
          !hullClip(vec3(0,0,1), h.z, origin, dir, interval) || !hullClip(vec3(0,0,-1), h.z, origin, dir, interval)) return false;
      if (hexagonal) {
        if (!hullClip(vec3(1.732050808,1,0), 1.732050808*r, origin, dir, interval) || !hullClip(vec3(-1.732050808,1,0), 1.732050808*r, origin, dir, interval) ||
            !hullClip(vec3(1.732050808,-1,0), 1.732050808*r, origin, dir, interval) || !hullClip(vec3(-1.732050808,-1,0), 1.732050808*r, origin, dir, interval)) return false;
      }
      return true;
    }\n` + shader.fragmentShader
  shader.fragmentShader = shader.fragmentShader.replace('#include <clipping_planes_fragment>', `#include <clipping_planes_fragment>
    for (int i = 0; i < ${spec.length}; i++) {
      vec3 origin = (hullInverse[i] * vec4(vHullOrigin, 1.0)).xyz;
      vec3 dir = mat3(hullInverse[i]) * vHullDirection;
      if (hullRay(origin, dir, hullHalf[i], hullHex[i] > 0.5)) discard;
    }`)

}
export function applyHullCutouts(material, spec) {
  validateHullCutouts(spec)
  const previous = material.userData.hullCutouts
  if (!previous && !spec.length) return
  material.userData.hullCutouts = spec
  // Uniform values update during drags without recompiling the shader.
  const held = compiledUniforms.get(material)
  if (held) {
    const next = uniforms(spec)
    for (const key of Object.keys(next)) held[key].value = next[key].value
  }
  material.onBeforeCompile = hullCutoutShader
  material.customProgramCacheKey = function () { return `hull-cutout-v1:${this.userData.hullCutouts?.length ?? 0}` }
  if (previous?.length !== spec.length) material.needsUpdate = true
}

/** Only the hull's display materials change; molecular coordinates stay untouched. */
export function initHullVolumeCutouts({ getRoots, store, events = window }) {
  const owners = new WeakMap()
  let volumes = store.getState().currentDesign?.view_volumes ?? []
  function refresh() {
    const spec = hullCutoutSpec(volumes)
    for (const root of getRoots()) {
      root.updateMatrixWorld(true)
      root.traverse(o => {
        if (!o.isMesh && !o.isLine) return
        const local = spec.map(v => ({ ...v, inverse: new THREE.Matrix4().fromArray(v.inverse).multiply(o.matrixWorld).toArray() }))
        const apply = material => {
          if (owners.has(material) && owners.get(material) !== o) material = material.clone()
          owners.set(material, o); applyHullCutouts(material, local); return material
        }
        if (Array.isArray(o.material)) o.material = o.material.map(apply)
        else if (o.material) o.material = apply(o.material)
      })
    }
  }

  const changed = event => { volumes = (event.detail?.layers ?? []).filter(layer => layer.keys?.length).map(layer => layer.volume).filter(Boolean); refresh() }
  events.addEventListener('nadoc:view-volume-layers', changed)
  return { refresh, dispose() { events.removeEventListener('nadoc:view-volume-layers', changed) } }
}
