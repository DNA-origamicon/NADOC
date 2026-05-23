/**
 * Sphere impostors — vertex-load reduction for backbone beads & atoms.
 *
 * A real bead is a ~140-triangle SphereGeometry(r,10,8); at `full`/atomistic
 * representation an assembly is vertex-bound (millions of bead triangles), and
 * GPU instancing cut draw-calls but NOT vertex throughput. An impostor replaces
 * each sphere with a 2-triangle camera-facing quad whose fragment program
 * ray-paints a perfectly round, correctly-lit sphere and writes gl_FragDepth so
 * it occludes/intersects neighbours exactly like a real sphere. ~70x fewer
 * triangles; cost moves vertex -> fragment (which dynamic-resolution can later
 * reclaim). See memory/project_sphere_impostors.md.
 *
 * Strategy: patch a stock MeshPhongMaterial via onBeforeCompile rather than a
 * from-scratch ShaderMaterial, so Three.js Phong lighting + fog + per-instance
 * instanceColor keep matching the rest of the scene. We inject only the
 * billboarding (vertex) and the sphere ray-paint + depth (fragment).
 *
 * The per-instance matrix supplies ONLY the bead CENTER (translation) and a
 * uniform scale (for the animation fade); the sphere radius is a uniform. This
 * is what lets physics / deform-lerp / unfold / fade keep working unchanged —
 * they all move beads by rewriting that matrix's translation/scale.
 */

import * as THREE from 'three'

// ── Runtime flag (opt-in until validated, then flip default) ──────────────────
//   • `?impostors=1` in the URL (per-tab), or
//   • `localStorage.NADOC_IMPOSTORS = 'true'` (sticky), or
//   • `window.NADOC_IMPOSTORS = true` (console).
export function impostorsEnabled() {
  try {
    const p = new URLSearchParams(location.search).get('impostors')
    if (p === '1') return true
    if (p === '0') return false
    if (localStorage.getItem('NADOC_IMPOSTORS') === 'true') return true
    if (window.NADOC_IMPOSTORS === true) return true
  } catch { /* non-browser / SSR guard */ }
  return false
}

// Shared unit quad spanning [-1,1] in XY (2 triangles). position.xy is the
// corner offset used both to billboard (vertex) and as the disc coordinate
// (fragment). Tagged `userData.shared` so helix_renderer's dispose-traversal
// skips it (it's reused across every helixCtrl).
export const IMPOSTOR_QUAD = (() => {
  const g = new THREE.PlaneGeometry(2, 2)
  g.userData.shared = true
  return g
})()

// ── Composable GLSL snippets ──────────────────────────────────────────────────
// Bodies only (no chunk `#include`), so BOTH the design-view material below AND
// the assembly shared-instancing patch (assembly_renderer.js `_attachInstanceShader`)
// can compose them. The two paths differ only in how they compute the bead CENTER:
// design view reads `instanceMatrix`; the shared path composes it from the
// per-instance × per-bp DataTextures. Everything downstream (the disc test, the
// sphere normal, the depth write, the lit-normal handoff) is identical.

// Vertex `<common>` additions.
export const IMPOSTOR_VERT_UNIFORMS = /* glsl */`
uniform float u_impostorRadius;
varying vec2  v_corner;
varying vec3  v_centerView;
varying float v_impR;
`

// Fragment `<common>` additions. projectionMatrix is a separate compilation unit
// from the vertex shader; the renderer populates it when declared here.
export const IMPOSTOR_FRAG_UNIFORMS = /* glsl */`
uniform mat4  projectionMatrix;
varying vec2  v_corner;
varying vec3  v_centerView;
varying float v_impR;
`

// Inserted right AFTER `#include <clipping_planes_fragment>`: discard outside the
// disc, compute the view-space sphere normal `_imp_normal`, and write corrected
// gl_FragDepth so the painted sphere occludes real geometry (slabs, cylinders,
// arcs). Reads v_corner / v_centerView / v_impR set by the vertex stage.
export const IMPOSTOR_FRAG_SPHERE_BODY = /* glsl */`
  float _imp_r2 = dot(v_corner, v_corner);
  if (_imp_r2 > 1.0) discard;
  vec3 _imp_normal = vec3(v_corner, sqrt(1.0 - _imp_r2));   // view space, +z toward camera
  float _imp_viewZ = v_centerView.z + _imp_normal.z * v_impR;
  vec4  _imp_clip  = projectionMatrix * vec4(0.0, 0.0, _imp_viewZ, 1.0);
  gl_FragDepth = 0.5 + 0.5 * (_imp_clip.z / _imp_clip.w);
`

// Replaces `<normal_fragment_begin>` so Phong lights the painted sphere instead
// of the flat quad. Defines exactly what the stock chunk defines (`normal` +
// `nonPerturbedNormal`); `geometryNormal` is declared later by
// `<lights_fragment_begin>`, so declaring it here is a redefinition error.
export const IMPOSTOR_FRAG_NORMAL = /* glsl */`
  vec3 normal = _imp_normal;
  vec3 nonPerturbedNormal = normal;
`

// ── Design-view (instanceMatrix) compositions of the snippets above ───────────

const _VERT_DECL = `#include <common>\n${IMPOSTOR_VERT_UNIFORMS}`

// Replaces <project_vertex>. Center = the instance origin in VIEW space (design
// view stores it in instanceMatrix), then offset the corner camera-facing by the
// (fade-scaled) radius so the quad always faces the camera and covers the sphere.
const _VERT_PROJECT = /* glsl */`
#ifdef USE_INSTANCING
  vec4  _imp_center = modelViewMatrix * instanceMatrix * vec4(0.0, 0.0, 0.0, 1.0);
  float _imp_scale  = length(instanceMatrix[0].xyz);   // uniform fade-scale
#else
  vec4  _imp_center = modelViewMatrix * vec4(0.0, 0.0, 0.0, 1.0);
  float _imp_scale  = 1.0;
#endif
  v_impR = u_impostorRadius * _imp_scale;
  vec4 mvPosition = _imp_center;
  mvPosition.xy += position.xy * v_impR;
  gl_Position = projectionMatrix * mvPosition;
  v_corner     = position.xy;
  v_centerView = _imp_center.xyz;
`

const _FRAG_DECL   = `#include <common>\n${IMPOSTOR_FRAG_UNIFORMS}`
const _FRAG_SPHERE = `#include <clipping_planes_fragment>\n${IMPOSTOR_FRAG_SPHERE_BODY}`
const _FRAG_NORMAL = IMPOSTOR_FRAG_NORMAL

/**
 * Build an impostor-patched MeshPhongMaterial for a bead/atom InstancedMesh.
 * @param {object}  opts
 * @param {number}  opts.radius — sphere radius in the mesh's local units (nm).
 * @param {number} [opts.color=0xffffff] — base color (instanceColor multiplies it).
 */
export function makeImpostorPhongMaterial({ radius, color = 0xffffff }) {
  const mat = new THREE.MeshPhongMaterial({ color, side: THREE.DoubleSide })
  mat.onBeforeCompile = (shader) => {
    shader.uniforms.u_impostorRadius = { value: radius }
    shader.vertexShader = shader.vertexShader
      .replace('#include <common>', _VERT_DECL)
      .replace('#include <project_vertex>', _VERT_PROJECT)
    shader.fragmentShader = shader.fragmentShader
      .replace('#include <common>', _FRAG_DECL)
      .replace('#include <clipping_planes_fragment>', _FRAG_SPHERE)
      .replace('#include <normal_fragment_begin>', _FRAG_NORMAL)
    mat.userData.shader = shader
  }
  // Unique cache key per material so onBeforeCompile runs for each (otherwise
  // materials sharing a program never get their u_impostorRadius bound — the
  // exact bug the shared-instancing path hit, see assembly_renderer.js:3038).
  mat.customProgramCacheKey = () => 'impostorPhong_' + mat.uuid
  mat.userData.isImpostor = true
  mat.userData.impostorRadius = radius
  return mat
}

/**
 * Override an InstancedMesh's raycast with a ray-vs-sphere test against each
 * instance's center, so picking still returns the right `instanceId` even
 * though the geometry is a flat quad billboarded GPU-side. The built-in
 * InstancedMesh.raycast would hit the (CPU-side, un-billboarded) quad instead.
 * @param {THREE.InstancedMesh} mesh
 * @param {number} radius — base sphere radius (nm); selection happens at fade-scale 1.
 */
export function installSphereImpostorRaycast(mesh, radius) {
  const _inv     = new THREE.Matrix4()
  const _localRay = new THREE.Ray()
  const _m       = new THREE.Matrix4()
  const _sphere  = new THREE.Sphere()
  const _hit     = new THREE.Vector3()

  mesh.raycast = function (raycaster, intersects) {
    if (!mesh.visible || mesh.count === 0) return
    _inv.copy(mesh.matrixWorld).invert()
    _localRay.copy(raycaster.ray).applyMatrix4(_inv)
    _sphere.radius = radius
    for (let i = 0; i < mesh.count; i++) {
      mesh.getMatrixAt(i, _m)
      _sphere.center.setFromMatrixPosition(_m)
      if (!_localRay.intersectSphere(_sphere, _hit)) continue
      const worldPt = _hit.clone().applyMatrix4(mesh.matrixWorld)
      const distance = raycaster.ray.origin.distanceTo(worldPt)
      if (distance < raycaster.near || distance > raycaster.far) continue
      intersects.push({ distance, point: worldPt, instanceId: i, object: mesh })
    }
  }
}
