/**
 * Shared-instancing assembly renderer (path-to-thousands Phase 3b/3c onward).
 *
 * Split out of assembly_renderer.js, which held two complete and independent
 * renderers in one file. This is the DEFAULT path (see memory/project_path_to_
 * thousands.md); the legacy per-instance renderer stays in assembly_renderer.js
 * and both are selected between by `createAssemblyRenderer({useShared})` there.
 *
 * One reason to change: how one helixCtrl-per-unique-SOURCE is instanced across
 * many PartInstances (transform textures, per-bp shader patching, the LOD ladder).
 *
 * Satisfies the AssemblyRenderer interface documented at the top of
 * assembly_renderer.js. Methods not yet implemented on this path degrade to a
 * benign default via `_SHARED_RENDERER_STUB_DEFAULTS` below.
 */
import * as THREE from 'three'
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js'
import { buildHelixObjects, buildStapleColorMap, CG_LOD } from './helix_renderer.js'
import { nucleotideLocalBox } from './selection_bbox.js'
import {
  IMPOSTOR_QUAD,
  IMPOSTOR_VERT_UNIFORMS,
  IMPOSTOR_FRAG_UNIFORMS,
  IMPOSTOR_FRAG_SPHERE_BODY,
  IMPOSTOR_FRAG_NORMAL,
} from './impostor_material.js'
import { ELEMENTS, DEFAULT_ELEMENT, BALL_RADIUS } from './atomistic_renderer/atom_palette.js'
import { C, STAPLE_PALETTE, buildClusterLookup, buildClusterColorLookup } from './helix_renderer/palette.js'
import { buildOverhangMarkers } from './joint_renderer.js'
import { buildCrossoverConnections } from './crossover_connections.js'
import {
  computeInstanceBluntEnds as _computeInstanceBluntEnds,
  bendCenterRecordToWorld as _bendCenterRecordToWorld,
} from './blunt_end_connectors.js'
import { clusterMemberFilter as _clusterMemberFilter } from './cluster_entries.js'
import { _hullGeoForSource } from './assembly_hull_geometry.js'
import { _rebuildLinkerHelices } from './assembly_linker_render.js'
import {
  _OVHG_SPRITE_HEIGHT_BASE, _makeOverhangNameTexture, _overhangLabelAnchorsLocal,
} from './assembly_overhang_labels.js'

// bp-texture tile width.  Per-bp matrices and colors are packed into a 2D
// DataTexture of width = 4*W (matrices) or W (colors), height = ceil(N/W).
// At W=256 a single texture row holds 256 bp slots, so even a 65k-bp source
// fits in 256 texture rows — well under WebGL's 16384 MAX_TEXTURE_SIZE.
const _BP_TEX_TILE_W = 256
const _XOVER_ARC_SEGS = 20

function _buildSharedCrossoverArcs(connections, instances, matrixFromValues, showPeriodic = false) {
  if (!connections?.length || !instances?.length) return null

  const normal = connections.filter(c => !c.isPeriodicSeam)
  const buckets = [
    ['scaffold', normal.filter(c => c.fromNuc?.strand_type === 'scaffold')],
    ['staple', normal.filter(c => c.fromNuc?.strand_type !== 'scaffold')],
    ['periodic', connections.filter(c => c.isPeriodicSeam)],
  ]
  const root = new THREE.Group()
  root.name = 'sharedCrossoverArcs'
  root.userData.instanceGroups = new Map()

  for (const inst of instances) {
    const group = new THREE.Group()
    group.name = `sharedInstanceXoverArcs_${inst.id}`
    group.userData.assemblyInstance = inst.id
    group.matrixAutoUpdate = false
    group.matrix.copy(matrixFromValues(inst.transform?.values))
    group.visible = inst.visible !== false && (inst.representation === 'full' || inst.representation === 'beads')

    for (const [arcType, conns] of buckets) {
      if (!conns.length) continue
      const vertexCount = conns.length * (_XOVER_ARC_SEGS + 1)
      const positions = new Float32Array(vertexCount * 3)
      const colors = new Float32Array(vertexCount * 3)
      const indexCount = conns.length * _XOVER_ARC_SEGS * 2
      const indices = vertexCount > 65535 ? new Uint32Array(indexCount) : new Uint16Array(indexCount)
      const color = new THREE.Color()
      for (let a = 0; a < conns.length; a++) {
        const { from, to } = conns[a]
        color.setHex(conns[a].color ?? 0x00ccff)
        const base = a * (_XOVER_ARC_SEGS + 1)
        for (let s = 0; s < _XOVER_ARC_SEGS; s++) {
          indices[(a * _XOVER_ARC_SEGS + s) * 2] = base + s
          indices[(a * _XOVER_ARC_SEGS + s) * 2 + 1] = base + s + 1
        }
        for (let v = 0; v <= _XOVER_ARC_SEGS; v++) {
          const t = v / _XOVER_ARC_SEGS
          const p = (base + v) * 3
          positions[p] = from.x + (to.x - from.x) * t
          positions[p + 1] = from.y + (to.y - from.y) * t
          positions[p + 2] = from.z + (to.z - from.z) * t
          colors[p] = color.r; colors[p + 1] = color.g; colors[p + 2] = color.b
        }
      }
      const geometry = new THREE.BufferGeometry()
      geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
      geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
      geometry.setIndex(new THREE.BufferAttribute(indices, 1))
      const material = new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.85 })
      const line = new THREE.LineSegments(geometry, material)
      line.name = `instanceXoverArc_${arcType}`
      line.frustumCulled = false
      line.userData.arcConnections = conns
      if (arcType === 'periodic') {
        line.userData.isPeriodicSeam = true
        line.visible = showPeriodic
      }
      group.add(line)
    }
    if (group.children.length) {
      root.add(group)
      root.userData.instanceGroups.set(inst.id, group)
    }
  }
  return root.children.length ? root : null
}

// Per-instance representation → shared-renderer LOD floor.  Returns the
// MINIMUM bucket an instance may occupy regardless of camera distance:
//   0 — close (bp-detail) ok
//   1 — mid (cylinders) min — cylinders rep never draws bp meshes
//   3 — hull (extrusion-box solid) — distance-independent; the dedicated hull
//       InstancedMesh draws these instances at all zooms (bucket 4 = hidden).
//       Also the floor for reprs not yet supported on the shared path
//       (vdw/ballstick/surface) — they render as a hull placeholder.
// (There is no billboard tier: a static camera-facing sprite misrepresents a
//  structure under a moving camera, so far-away cylinders/bp collapse to the
//  hull solid instead.)
function _repToLodCap(repr) {
  if (repr === 'cylinders') return 1
  if (repr === 'full' || repr === 'beads') return 0
  return 3
}

// Methods that intentionally throw "out of plan scope" on the shared-instancing
// path. Pickers, joint-drag at scale, debug introspection, hull / linker /
// photo paths are deferred until later phases or until the user toggles the
// flag OFF.
/**
 * Methods on the shared-instancing path that aren't implemented yet. Each
 * maps to a default-return factory (called per invocation) so callers get a
 * benign value instead of a thrown error. The shared path is rAF-hot and the
 * old behavior — throw on every call — turned every per-frame call site or
 * pointerdown into a stack trace. Now: silent fallback + one-time console.warn
 * per method name so a developer notices what's missing without spamming.
 *
 * Phase 3d / 3e will replace specific entries with real implementations
 * (visibility / color / joint picking / linker rendering). Until then, the
 * feature degrades gracefully: no linker meshes, no per-instance pick, etc.
 */
const _SHARED_RENDERER_STUB_DEFAULTS = {
  // setLiveTransform / getLiveTransform / pickInstance now implemented
  // on the shared path; kept out of the stub list.
  // pickInstanceCluster / captureInstanceClusterBase / applyInstanceClusterTransform
  // implemented on the shared path (Phase 7c) — cluster articulation via a
  // materialized active instance. pickPartJoint (the ring-grab affordance) is
  // still stubbed: the cluster-panel-select → drag path (Priority 2b in
  // main.js) articulates without it; part-joint ring indicators are deferred.
  pickPartJoint:                  () => null,
  // getInstanceDesign / getInstanceRenderData / getInstanceBackboneEntries
  // implemented on the shared path (Phase 7a) — they read the source's shared
  // Design + helixCtrl.backboneEntries (source-local) plus the per-instance
  // world matrix from xformData. Callers apply the matrix themselves.
  getLabelTable:                  () => [],   // debug-only console helper; left stubbed (no per-instance label sprites on shared path)
  // getInstanceBluntEnds / getConnectorClusterId / getConnectorClusterIds
  // implemented on the shared path (blunt-end connectors for Define Mate).
  auditInstanceBox:               () => undefined,
  // rebuildLinkers implemented on the shared path (Phase 7b) — cross-part
  // linker helices into a dedicated group via the module-level
  // `_rebuildLinkerHelices` (VSC dashed lines still deferred there).
  // setPhotoMode implemented on the shared path (Phase 7d) — hides the
  // selection outline; photo_renderer re-applies the instancing patch to the
  // PBR materials it swaps in via userData.applySharedInstancing.
}
const _SHARED_RENDERER_STUB_METHODS = new Set(Object.keys(_SHARED_RENDERER_STUB_DEFAULTS))

/**
 * Shared-instancing assembly renderer (Phase 3b + 3c).
 *
 * Architectural shift:
 *  - Old path: one helixCtrl per PartInstance → ~4 InstancedMesh trees per
 *    instance → for 500 copies of one source = ~2000+ draw calls/frame.
 *  - New path: one helixCtrl per UNIQUE SOURCE. Each per-bp InstancedMesh.count
 *    is multiplied by num_instances_of_this_source (e.g. 60000 bp × 500
 *    = 30 M slots, but still ONE draw call per mesh). The vertex shader
 *    composes `world = instTransform[gl_InstanceID / num_bp] × instanceMatrix
 *    × position` by sampling a DataTexture of per-instance transforms.
 *
 * Tradeoffs honoured by this implementation:
 *  - Pickers (raycast / cluster picking) are intentionally not supported at
 *    scale (the per-instance-on-the-cpu data isn't kept). User toggles the
 *    flag OFF if they need to pick.
 *  - applyInlineGeometry → re-derives the affected instances' transforms
 *    and dirties their texture rows.
 *  - invalidateInstance → triggers a full rebuild on the next external
 *    rebuild call (acceptable per the spec).
 *
 * @param {object} opts
 * @param {THREE.Scene} opts.scene
 * @param {object}      opts.store
 * @param {object}      opts.api
 */
export function _createSharedInstancingRenderer({ scene, store, api }) {
  // ── Per-source render data ─────────────────────────────────────────────────
  // key  = source_key (mirrors `/assembly/geometry`'s sources map; computed
  //         from PartInstance.source via `_sharedSourceKey`).
  // value = {
  //   helixCtrl,                 // returned by buildHelixObjects (count multiplied)
  //   design,                    // shared Design dict
  //   nucleotides,               // decoded nucleotide list
  //   helixAxes,                 // helix axes dict
  //   numBpPerInstance,          // count divisor used by the shader
  //   instanceIds,               // ordered [id, id, ...] — index = row in texture
  //   instanceIndex,             // id → row index
  //   visibility,                // Float32Array (one per instance, 0 or 1)
  //   xformTex,                  // THREE.DataTexture (4 × N RGBA32F)
  //   xformData,                 // backing Float32Array (4 texels × 4 channels × N)
  //   activeMeshes,              // InstancedMesh[] whose materials carry our uniforms
  //   uActiveIdxUniform,         // shared { value: -1 } object across activeMeshes
  //   dirtyRows,                 // Set<number> of instance indices needing GPU re-upload
  //   instBoundingBox,           // THREE.Box3 (per-source local bbox)
  // }
  const _sources = new Map()

  // id → source_key (lookup for setActiveInstance / applyInlineGeometry)
  const _instToSrc = new Map()

  // Backend-computed bend center-of-curvature connectors per instance, in
  // instance-LOCAL frame. Populated lazily by getInstanceBendCenters() on
  // Define-Mate; cleared on rebuild (shared path rebuilds on invalidate).
  const _bendCentersLocalCache = new Map() // instId → Array<{...}>

  // Stash for applyInlineGeometry (mirrors the old path)
  const _prefetchedByPath = new Map()

  // Rebuild-complete subscribers (parity with old path).
  const _onRebuildCompleteCbs = []

  // Cross-part linker geometry lives in its own group (linkers are few, per
  // overhang-connection, not per-bp instanced — no instancing needed). Shared
  // with the legacy path via the module-level `_rebuildLinkerHelices`.
  const _linkerGroup = new THREE.Group()
  _linkerGroup.name = 'assembly_linkers'
  scene.add(_linkerGroup)

  // Local copy of the legacy `_axesArrayToMap` (pure; see initAssemblyRenderer).
  function _axesArrayToMap(raw) {
    if (!raw?.length) return null
    const map = {}
    for (const ax of raw) map[ax.helix_id] = { start: ax.start, end: ax.end, samples: ax.samples ?? null, ovhgAxes: ax.ovhg_axes ?? null }
    return map
  }

  // ── Public: rebuildLinkers (Phase 7b) ──────────────────────────────────────
  // Renders the cross-part linker helices. The legacy path additionally draws
  // `__vsc__` virtual-scaffold dashed lines; those need per-instance world-axis
  // caches the shared path doesn't keep, so they're deferred here (a separate
  // feature, not part of cross-part linkers).
  async function rebuildLinkers(assembly) {
    // rebuild() calls dispose() at its top, which detaches _linkerGroup from the
    // scene; main.js runs rebuild().then(rebuildLinkers), so re-attach here or
    // the freshly-built linker meshes would live in an orphaned group (invisible).
    if (!_linkerGroup.parent) scene.add(_linkerGroup)
    await _rebuildLinkerHelices({
      assembly, api, linkerGroup: _linkerGroup, axesToMap: _axesArrayToMap,
    })
  }

  // The active instance id — surfaced as a per-source uniform so the shader
  // can brighten the matching instance's slots.
  let _activeInstanceId = null

  // ── Source-key helper (mirror of `_sourceKey` in initAssemblyRenderer) ────
  function _sharedSourceKey(inst) {
    if (!inst?.source) return 'none'
    const ov = JSON.stringify(inst.cluster_transform_overrides ?? [])
    if (inst.source.type === 'file') return `file:${inst.source.path ?? ''}:ct:${ov}`
    return `inline:${inst.source.design?.id ?? ''}:ct:${ov}`
  }

  // ── Transform helper: row-major 16-float → THREE.Matrix4 (column-major) ───
  function _instMat4(values) {
    const m = new THREE.Matrix4()
    if (values?.length === 16) {
      m.fromArray(values)
      m.transpose()
    }
    return m
  }

  // ── Pack a Matrix4 into 16 floats (row-major), write into rowOut ──────────
  // Texture layout: width=4 texels, height=N rows. Texel (j, i) holds
  // (m[i*16 + j*4 + 0..3]) — i.e. row j of instance i's matrix in row-major.
  // The shader reads with `texelFetch(u_instanceXform, ivec2(j, i), 0)` and
  // composes mat4(r0, r1, r2, r3) which in GLSL is COLUMN-major. So when we
  // sample row-major rows and put them into a `mat4()` whose arguments are
  // columns, GLSL produces the TRANSPOSE of what we want. To compensate we
  // store the matrix's COLUMNS as the texel rows. Concretely we want, for a
  // row-major matrix M:
  //   texel(0, i) = column 0 of M = [M[0], M[4], M[8],  M[12]]
  //   texel(1, i) = column 1 of M = [M[1], M[5], M[9],  M[13]]
  //   texel(2, i) = column 2 of M = [M[2], M[6], M[10], M[14]]
  //   texel(3, i) = column 3 of M = [M[3], M[7], M[11], M[15]]
  // Then `mat4(c0, c1, c2, c3)` in GLSL gives us the right matrix.
  function _packMatrixIntoRow(m, rowOut, offset) {
    const e = m.elements  // THREE stores column-major: e[0..3] = col0, etc.
    // Texel 0 = col 0
    rowOut[offset + 0]  = e[0]
    rowOut[offset + 1]  = e[1]
    rowOut[offset + 2]  = e[2]
    rowOut[offset + 3]  = e[3]
    // Texel 1 = col 1
    rowOut[offset + 4]  = e[4]
    rowOut[offset + 5]  = e[5]
    rowOut[offset + 6]  = e[6]
    rowOut[offset + 7]  = e[7]
    // Texel 2 = col 2
    rowOut[offset + 8]  = e[8]
    rowOut[offset + 9]  = e[9]
    rowOut[offset + 10] = e[10]
    rowOut[offset + 11] = e[11]
    // Texel 3 = col 3
    rowOut[offset + 12] = e[12]
    rowOut[offset + 13] = e[13]
    rowOut[offset + 14] = e[14]
    rowOut[offset + 15] = e[15]
  }

  // ── Build / resize a per-source transform texture ─────────────────────────
  // Float32 RGBA, width=4, height=N. One row of texels per instance.
  function _makeXformTexture(N) {
    const w = 4
    const h = Math.max(1, N)
    const data = new Float32Array(w * h * 4)
    const tex = new THREE.DataTexture(
      data, w, h, THREE.RGBAFormat, THREE.FloatType,
    )
    tex.minFilter = THREE.NearestFilter
    tex.magFilter = THREE.NearestFilter
    tex.generateMipmaps = false
    tex.needsUpdate = true
    return { tex, data }
  }

  // ── Shader injection ──────────────────────────────────────────────────────
  // Patch a material's onBeforeCompile so the vertex stage applies BOTH the
  // per-instance source transform (from one per-source DataTexture) AND the
  // per-bp local transform (from one per-mesh DataTexture). Also adds a
  // fragment brightening for the selected instance.
  //
  // Two textures so per-bp matrices are stored ONCE per source (not N tiles):
  //   - u_instanceXform: per-source-instance 4×4 matrix (N rows).
  //   - u_bpXform:       per-bp 4×4 matrix (bp_count rows).
  // World position: `world = instTransform * bpMat * position`. The standard
  // `<project_vertex>` chunk still runs `instanceMatrix * mvPosition`, but
  // we've collapsed `instanceMatrix` to a single identity row via
  // meshPerAttribute (see `_patchSharedMeshes`) so that multiply is a no-op.
  //
  // `numBpPerInstance` is set as a uniform (so the divisor varies per mesh).
  // `u_activeInstanceIdx` is shared so a single `.value = N` write per
  // selection change updates every mesh in the source.
  // `u_bpXform` is PER-MESH (each InstancedMesh has its own bp count and
  // bp matrix set), supplied via `uBpTex` in the uniforms bundle.
  function _attachInstanceShader(material, uniformsBundle, numBpPerInstance) {
    // Compose with any pre-existing onBeforeCompile (Phase 7d: photo mode's
    // fluorophore-emissive preset patches the fragment) instead of clobbering
    // it. For the normal build-time path the material has none → no-op.
    const _priorOnBeforeCompile = material.onBeforeCompile
    // Impostor bead/atom meshes (Phase B): their material carries the impostor
    // patch, but its `<project_vertex>` billboards around `instanceMatrix` —
    // which the shared path collapses to identity (the center lives in the
    // instance×bp textures). So we DON'T run the material's own patch; instead
    // we compose the bead center from the textures and billboard it ourselves,
    // reusing the shared impostor GLSL snippets for the fragment sphere paint.
    const _isImpostor = !!material.userData?.isImpostor
    material.onBeforeCompile = (shader) => {
      if (!_isImpostor) _priorOnBeforeCompile?.(shader)
      shader.uniforms.u_instanceXform   = uniformsBundle.uXform
      shader.uniforms.u_numBpPerInstance = { value: numBpPerInstance }
      shader.uniforms.u_activeInstanceIdx = uniformsBundle.uActiveIdx
      shader.uniforms.u_visibilityTex   = uniformsBundle.uVis
      shader.uniforms.u_bpXform         = uniformsBundle.uBpTex
      if (uniformsBundle.hasBpColor) {
        shader.uniforms.u_bpColor = uniformsBundle.uBpColorTex
      }
      if (_isImpostor) {
        shader.uniforms.u_impostorRadius = { value: material.userData.impostorRadius ?? 0.1 }
      }
      // Diagnostic: confirm both vertex-shader replaces actually matched. If
      // `<begin_vertex>` is absent (e.g. material uses a custom shader instead
      // of Three.js's standard chunks), the bp meshes will render at the
      // source origin without per-instance positioning — exactly the symptom
      // we're seeing in dev. One-time log per material kind.
      const hadCommon = shader.vertexShader.includes('#include <common>')
      const hadBeginVertex = shader.vertexShader.includes('#include <begin_vertex>')
      if (!hadCommon || !hadBeginVertex) {
        console.warn(
          `[shared_renderer] shader patch FAILED — material ${material.type ?? '(unknown)'} ` +
          `(name=${material.name ?? '(none)'}) missing chunks: ` +
          `common=${hadCommon} begin_vertex=${hadBeginVertex}. ` +
          `bp mesh will render at source origin without per-instance transforms.`,
        )
      }

      // Vertex: prepend uniform + varying; compose final `transformed` via
      // full chunk replacement of `<begin_vertex>` (option (a) from the
      // chunk spec). `instanceMatrix` is collapsed to identity via
      // meshPerAttribute, so the auto-injection in `<project_vertex>`
      // becomes a no-op without further patching there.
      shader.vertexShader = shader.vertexShader
        .replace(
          '#include <common>',
          `
          #include <common>
          #define BP_TILE_W ${_BP_TEX_TILE_W}
          uniform sampler2D u_instanceXform;
          uniform sampler2D u_visibilityTex;
          uniform sampler2D u_bpXform;
          uniform float u_numBpPerInstance;
          uniform float u_activeInstanceIdx;
          flat varying int v_instanceIdx;
          varying float v_visible;
          ${uniformsBundle.hasBpColor ? 'uniform sampler2D u_bpColor;\n          varying vec3 v_bpColor;' : ''}
          ${_isImpostor ? IMPOSTOR_VERT_UNIFORMS : ''}
          `,
        )
        .replace(
          '#include <beginnormal_vertex>',
          `
          #include <beginnormal_vertex>
          int normalInstanceIdx = int(floor(float(gl_InstanceID) / max(u_numBpPerInstance, 1.0)));
          int normalBpIdx = gl_InstanceID - normalInstanceIdx * int(u_numBpPerInstance);
          int normalBpCol = normalBpIdx % BP_TILE_W;
          int normalBpRow = normalBpIdx / BP_TILE_W;
          mat4 normalInstTransform = mat4(
            texelFetch(u_instanceXform, ivec2(0, normalInstanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(1, normalInstanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(2, normalInstanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(3, normalInstanceIdx), 0)
          );
          mat4 normalBpTransform = mat4(
            texelFetch(u_bpXform, ivec2(normalBpCol * 4 + 0, normalBpRow), 0),
            texelFetch(u_bpXform, ivec2(normalBpCol * 4 + 1, normalBpRow), 0),
            texelFetch(u_bpXform, ivec2(normalBpCol * 4 + 2, normalBpRow), 0),
            texelFetch(u_bpXform, ivec2(normalBpCol * 4 + 3, normalBpRow), 0)
          );
          objectNormal = transpose(inverse(mat3(normalInstTransform * normalBpTransform))) * objectNormal;
          #ifdef USE_TANGENT
            objectTangent = mat3(normalInstTransform * normalBpTransform) * objectTangent;
          #endif
          `,
        )
        .replace(
          '#include <begin_vertex>',
          `
          // Compute instance index from the InstancedMesh's gl_InstanceID:
          // every group of u_numBpPerInstance consecutive instances belongs
          // to one source-instance.
          int instanceIdx = int(floor(float(gl_InstanceID) / max(u_numBpPerInstance, 1.0)));
          int bpIdx       = gl_InstanceID - instanceIdx * int(u_numBpPerInstance);
          int bpCol       = bpIdx % BP_TILE_W;
          int bpRow       = bpIdx / BP_TILE_W;
          v_instanceIdx = instanceIdx;
          v_visible = texelFetch(u_visibilityTex, ivec2(0, instanceIdx), 0).r;
          // Per-source instance matrix. 4 RGBA texels (4 floats each) = one
          // mat4. Texture layout: column-major (texel j of row i = column j
          // of matrix i). mat4(c0,c1,c2,c3) is column-major in GLSL.
          mat4 instTransform = mat4(
            texelFetch(u_instanceXform, ivec2(0, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(1, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(2, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(3, instanceIdx), 0)
          );
          // Per-bp local matrix from the 2D-tiled bp texture: bpIdx packs
          // along the row (4 RGBA texels per matrix) and wraps every
          // BP_TILE_W slots to a new row.
          mat4 bpMat = mat4(
            texelFetch(u_bpXform, ivec2(bpCol * 4 + 0, bpRow), 0),
            texelFetch(u_bpXform, ivec2(bpCol * 4 + 1, bpRow), 0),
            texelFetch(u_bpXform, ivec2(bpCol * 4 + 2, bpRow), 0),
            texelFetch(u_bpXform, ivec2(bpCol * 4 + 3, bpRow), 0)
          );
          // Non-impostor: transform the actual vertex. Impostor: transform only
          // the bead CENTER (origin); the quad corner is billboarded in <project_vertex>.
          vec3 transformed = ${_isImpostor
            ? '(instTransform * bpMat * vec4(0.0, 0.0, 0.0, 1.0)).xyz'
            : '(instTransform * bpMat * vec4(position, 1.0)).xyz'};
          ${uniformsBundle.hasBpColor ? 'v_bpColor = texelFetch(u_bpColor, ivec2(bpCol, bpRow), 0).rgb;' : ''}
          `,
        )

      // Impostor billboard: center → view space, offset the quad corner
      // camera-facing by the radius, and set the impostor fragment varyings.
      if (_isImpostor) {
        shader.vertexShader = shader.vertexShader.replace(
          '#include <project_vertex>',
          `
          vec4 mvPosition = modelViewMatrix * vec4(transformed, 1.0);
          v_centerView = mvPosition.xyz;
          v_impR = u_impostorRadius;
          mvPosition.xy += position.xy * u_impostorRadius;
          gl_Position = projectionMatrix * mvPosition;
          v_corner = position.xy;
          `,
        )
      }

      // Fragment: discard if instance is hidden; brighten if active.
      shader.fragmentShader = shader.fragmentShader
        .replace(
          '#include <common>',
          `
          #include <common>
          uniform float u_activeInstanceIdx;
          flat varying int v_instanceIdx;
          varying float v_visible;
          ${uniformsBundle.hasBpColor ? 'varying vec3 v_bpColor;' : ''}
          ${_isImpostor ? IMPOSTOR_FRAG_UNIFORMS : ''}
          `,
        )
        .replace(
          '#include <color_fragment>',
          `
          #include <color_fragment>
          ${uniformsBundle.hasBpColor ? 'diffuseColor.rgb *= v_bpColor;' : ''}
          `,
        )
        .replace(
          '#include <dithering_fragment>',
          `
          if (v_visible < 0.5) discard;
          if (u_activeInstanceIdx >= 0.0 && abs(float(v_instanceIdx) - u_activeInstanceIdx) < 0.5) {
            gl_FragColor.rgb = mix(gl_FragColor.rgb, vec3(1.0, 1.0, 1.0), 0.35);
          }
          #include <dithering_fragment>
          `,
        )

      // Impostor sphere paint + corrected depth (reused from impostor_material.js).
      // Different chunks than the common/dithering replaces above, so separate.
      if (_isImpostor) {
        shader.fragmentShader = shader.fragmentShader
          .replace('#include <clipping_planes_fragment>',
            `#include <clipping_planes_fragment>\n${IMPOSTOR_FRAG_SPHERE_BODY}`)
          .replace('#include <normal_fragment_begin>', IMPOSTOR_FRAG_NORMAL)
      }
    }
    // Each material gets a UNIQUE cache key so Three.js's program cache
    // doesn't make 13 materials share the first material's compiled program.
    // With a static key, only the first material's `onBeforeCompile` ran;
    // the rest had their custom uniforms (`u_bpXform`, etc.) never bound,
    // so their bp meshes rendered as if unpatched (all stacked at the
    // source origin — symptom: "only one hinge visible / only axis lines").
    // material.uuid is unique per material instance and stable for cache.
    const cacheKey = 'sharedInstanced_' + material.uuid
    material.customProgramCacheKey = () => cacheKey
    // Stash the patched shader on userData for future diagnostics (Three.js
    // doesn't auto-stash this for stock materials).
    const userBeforeCompile = material.onBeforeCompile
    material.onBeforeCompile = (shader) => {
      userBeforeCompile(shader)
      material.userData.shader = shader
    }
  }

  // Build a per-mesh "bp transform" DataTexture from the original per-bp
  // instanceMatrix data. Width=4 RGBA texels (one per matrix column),
  // height=bp_count. Texel (j, i) holds column j of the bp-i local matrix.
  // THREE stores `instanceMatrix.array` column-major (consecutive 16 floats
  // per slot are c0|c1|c2|c3), so we can do a direct typed-array copy.
  function _makeBpXformTexture(srcArray, bpCount) {
    // 2D tiling: pack bp slots in a 4*W × ceil(N/W) texture so even sources
    // with > MAX_TEXTURE_SIZE bp slots fit.  Byte layout is preserved because
    // each row holds W bp matrices = 16*W floats, so bp i still lives at
    // float offset i*16 in the underlying typed array.  The shader recovers
    // (col, row) via `ivec2((bpIdx % W) * 4 + col, bpIdx / W)`.
    const tileW = _BP_TEX_TILE_W
    const h = Math.max(1, Math.ceil(bpCount / tileW))
    const texW = 4 * tileW
    const data = new Float32Array(texW * h * 4)  // = 16 * tileW * h floats
    const n = Math.min(srcArray.length, bpCount * 16)
    data.set(srcArray.subarray(0, n), 0)
    const tex = new THREE.DataTexture(
      data, texW, h, THREE.RGBAFormat, THREE.FloatType,
    )
    tex.minFilter = THREE.NearestFilter
    tex.magFilter = THREE.NearestFilter
    tex.generateMipmaps = false
    tex.needsUpdate = true
    return { tex, data }
  }

  // ── Phase C: atomistic atom-impostor batch ──────────────────────────────────
  // Atomistic reps (vdw/ballstick) on the shared path render each atom as a 2-tri
  // impostor quad (like the CG beads), composed through the SAME per-source
  // instance-transform + visibility textures. The per-atom "local transform" is
  // just a source-local POSITION (vec3) — atoms are points, no rotation — so
  // instead of a per-bp 4×4 texture we store a vec3-per-atom texture and the
  // shader does `world = instTransform[instanceIdx] × atomPos[atomIdx]`.

  // 2D-tiled RGBA-float texture of source-local atom positions (xyz in RGB).
  // atomIdx → ivec2(atomIdx % W, atomIdx / W); .xyz = local position.
  function _makeAtomPosTexture(posFlat, numAtoms) {
    const tileW = _BP_TEX_TILE_W
    const h = Math.max(1, Math.ceil(numAtoms / tileW))
    const data = new Float32Array(tileW * h * 4)
    for (let i = 0; i < numAtoms; i++) {
      data[i * 4 + 0] = posFlat[i * 3 + 0]
      data[i * 4 + 1] = posFlat[i * 3 + 1]
      data[i * 4 + 2] = posFlat[i * 3 + 2]
      data[i * 4 + 3] = 1.0
    }
    const tex = new THREE.DataTexture(data, tileW, h, THREE.RGBAFormat, THREE.FloatType)
    tex.minFilter = THREE.NearestFilter
    tex.magFilter = THREE.NearestFilter
    tex.generateMipmaps = false
    tex.needsUpdate = true
    return { tex, data }
  }

  // Per-atom RGB color texture (same 2D tiling as the position texture).
  function _makeAtomColorTexture(rgbFlat, numAtoms) {
    const tileW = _BP_TEX_TILE_W
    const h = Math.max(1, Math.ceil(numAtoms / tileW))
    const data = new Float32Array(tileW * h * 4)
    for (let i = 0; i < numAtoms; i++) {
      data[i * 4 + 0] = rgbFlat[i * 3 + 0]
      data[i * 4 + 1] = rgbFlat[i * 3 + 1]
      data[i * 4 + 2] = rgbFlat[i * 3 + 2]
      data[i * 4 + 3] = 1.0
    }
    const tex = new THREE.DataTexture(data, tileW, h, THREE.RGBAFormat, THREE.FloatType)
    tex.minFilter = THREE.NearestFilter
    tex.magFilter = THREE.NearestFilter
    tex.generateMipmaps = false
    tex.needsUpdate = true
    return { tex, data }
  }

  // ── Atomistic coloring ──────────────────────────────────────────────────────
  // Modes supported for atomistic on the shared path. Anything else → 'cpk'.
  const _ATOM_COLOR_MODES = new Set(['cpk', 'strand', 'cluster', 'source'])
  const _atomColorMode = (m) => (_ATOM_COLOR_MODES.has(m) ? m : 'cpk')

  // Deterministic per-source tint (order-independent) for 'source' coloring.
  function _srcColorHex(srcKey) {
    let h = 0
    for (let i = 0; i < (srcKey || '').length; i++) h = (h * 31 + srcKey.charCodeAt(i)) | 0
    return STAPLE_PALETTE[Math.abs(h) % STAPLE_PALETTE.length]
  }

  // One atom's color (hex int) for a mode — mirrors helix_renderer.applyColoring
  // so atoms match the CG bead/cylinder colors.  ctx: { stapleColorMap, customColors,
  // clusterFn, strandType: Map<strand_id,type>, sourceColor }.
  function _atomColorHex(atom, mode, ctx) {
    if (mode === 'source') return ctx.sourceColor
    if (mode === 'cpk')    return ELEMENTS[atom.element]?.color ?? DEFAULT_ELEMENT.color
    const sid = atom.strand_id
    const strandHex = () => {
      if (!sid) return C.unassigned
      if (ctx.strandType.get(sid) === 'scaffold') return C.scaffold_backbone
      if (ctx.customColors[sid] != null) return ctx.customColors[sid]
      return ctx.stapleColorMap.get(sid) ?? C.unassigned
    }
    if (mode === 'cluster') {
      const ci = ctx.clusterFn({ helix_id: atom.helix_id, strand_id: sid })
      return ci != null ? STAPLE_PALETTE[ci % STAPLE_PALETTE.length] : strandHex()
    }
    return strandHex()   // 'strand'
  }

  function _computeAtomColorRGB(atomList, mode, ctx) {
    const out = new Float32Array(atomList.length * 3)
    for (let i = 0; i < atomList.length; i++) {
      const hex = _atomColorHex(atomList[i], mode, ctx)
      out[i * 3 + 0] = ((hex >> 16) & 255) / 255
      out[i * 3 + 1] = ((hex >> 8) & 255) / 255
      out[i * 3 + 2] = (hex & 255) / 255
    }
    return out
  }

  // Recompute + re-upload an atomistic source's per-atom color textures in place.
  function _recolorAtomBatch(srcEntry, mode) {
    if (!srcEntry?.atomBatch || !srcEntry._atomCtx) return
    const m = _atomColorMode(mode)
    for (const b of srcEntry.atomBatch) {
      const rgb = _computeAtomColorRGB(b.atomList, m, srcEntry._atomCtx)
      const data = b.colorTex.image.data
      for (let i = 0; i < b.atomList.length; i++) {
        data[i * 4 + 0] = rgb[i * 3 + 0]
        data[i * 4 + 1] = rgb[i * 3 + 1]
        data[i * 4 + 2] = rgb[i * 3 + 2]
      }
      b.colorTex.needsUpdate = true
    }
  }

  // ── Surface coloring (assembly) ─────────────────────────────────────────────
  // Surface vertices carry only a strand_id (vertex_strand_index → table); we
  // recolor client-side (no re-fetch) by mapping each vertex's strand to a hex.
  const _SURFACE_COLOR_MODES = new Set(['strand', 'cluster', 'source'])
  const _surfaceColorMode = (m) => (_SURFACE_COLOR_MODES.has(m) ? m : 'strand')

  // strand_id → hex for a surface coloring mode (mirrors _atomColorHex's strand
  // path; cluster uses the strand's cluster, source the per-source tint).
  function _surfaceStrandHex(sid, mode, ctx) {
    if (mode === 'source') return ctx.sourceColor
    if (mode === 'cluster') {
      const ci = ctx.strandCluster.get(sid)
      if (ci != null) return STAPLE_PALETTE[ci % STAPLE_PALETTE.length]
      // else fall through to strand color
    }
    if (!sid) return C.unassigned
    if (ctx.strandType.get(sid) === 'scaffold') return C.scaffold_backbone
    if (ctx.customColors[sid] != null) return ctx.customColors[sid]
    return ctx.stapleColorMap.get(sid) ?? C.unassigned
  }

  // Recompute the surface mesh's per-vertex `color` attribute in place.
  function _recolorSurface(srcEntry, mode) {
    const sm = srcEntry.surfaceMesh
    const ctx = srcEntry._surfaceCtx
    if (!sm?.geo || !ctx || !sm.vertexStrandIdx) return
    const m = _surfaceColorMode(mode)
    // Per-table hex (small) → expand to per-vertex.
    const tblHex = sm.strandTable.map(sid => _surfaceStrandHex(sid, m, ctx))
    const idx = sm.vertexStrandIdx
    const colors = new Float32Array(idx.length * 3)
    for (let v = 0; v < idx.length; v++) {
      const hex = tblHex[idx[v]] ?? C.unassigned
      colors[v * 3 + 0] = ((hex >> 16) & 255) / 255
      colors[v * 3 + 1] = ((hex >> 8) & 255) / 255
      colors[v * 3 + 2] = (hex & 255) / 255
    }
    sm.geo.setAttribute('color', new THREE.BufferAttribute(colors, 3))
    sm.geo.attributes.color.needsUpdate = true
    if (!sm.mat.vertexColors) { sm.mat.vertexColors = true; sm.mat.color.setHex(0xffffff); sm.mat.needsUpdate = true }
  }

  // Patch a per-element MeshPhongMaterial into an atom impostor: vertex composes
  // the atom's world center from the instance-transform texture + the atom-pos
  // texture, then billboards the quad; fragment reuses the shared impostor
  // sphere-paint + the per-instance visibility/active-highlight logic.
  function _attachAtomImpostorShader(material, bundle) {
    material.onBeforeCompile = (shader) => {
      shader.uniforms.u_instanceXform       = bundle.uXform
      shader.uniforms.u_visibilityTex       = bundle.uVis
      shader.uniforms.u_activeInstanceIdx   = bundle.uActiveIdx
      shader.uniforms.u_atomPos             = bundle.uAtomPos
      shader.uniforms.u_atomColor           = bundle.uAtomColor
      shader.uniforms.u_numAtomsPerInstance = { value: bundle.numAtoms }
      shader.uniforms.u_impostorRadius      = { value: bundle.radius }

      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', `
          #include <common>
          #define ATOM_TILE_W ${_BP_TEX_TILE_W}
          uniform sampler2D u_instanceXform;
          uniform sampler2D u_visibilityTex;
          uniform sampler2D u_atomPos;
          uniform sampler2D u_atomColor;
          uniform float u_numAtomsPerInstance;
          uniform float u_activeInstanceIdx;
          flat varying int v_instanceIdx;
          varying float v_visible;
          varying vec3 v_atomColor;
          ${IMPOSTOR_VERT_UNIFORMS}
        `)
        .replace('#include <begin_vertex>', `
          int instanceIdx = int(floor(float(gl_InstanceID) / max(u_numAtomsPerInstance, 1.0)));
          int atomIdx = gl_InstanceID - instanceIdx * int(u_numAtomsPerInstance);
          v_instanceIdx = instanceIdx;
          v_visible = texelFetch(u_visibilityTex, ivec2(0, instanceIdx), 0).r;
          v_atomColor = texelFetch(u_atomColor, ivec2(atomIdx % ATOM_TILE_W, atomIdx / ATOM_TILE_W), 0).rgb;
          mat4 instTransform = mat4(
            texelFetch(u_instanceXform, ivec2(0, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(1, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(2, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(3, instanceIdx), 0)
          );
          vec3 atomLocal = texelFetch(u_atomPos, ivec2(atomIdx % ATOM_TILE_W, atomIdx / ATOM_TILE_W), 0).xyz;
          vec3 transformed = (instTransform * vec4(atomLocal, 1.0)).xyz;
        `)
        .replace('#include <project_vertex>', `
          vec4 mvPosition = modelViewMatrix * vec4(transformed, 1.0);
          v_centerView = mvPosition.xyz;
          v_impR = u_impostorRadius;
          mvPosition.xy += position.xy * u_impostorRadius;
          gl_Position = projectionMatrix * mvPosition;
          v_corner = position.xy;
        `)

      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', `
          #include <common>
          uniform float u_activeInstanceIdx;
          flat varying int v_instanceIdx;
          varying float v_visible;
          varying vec3 v_atomColor;
          ${IMPOSTOR_FRAG_UNIFORMS}
        `)
        .replace('#include <clipping_planes_fragment>',
          `#include <clipping_planes_fragment>\n${IMPOSTOR_FRAG_SPHERE_BODY}`)
        .replace('#include <normal_fragment_begin>', IMPOSTOR_FRAG_NORMAL)
        .replace('#include <color_fragment>', `
          #include <color_fragment>
          diffuseColor.rgb *= v_atomColor;
        `)
        .replace('#include <dithering_fragment>', `
          if (v_visible < 0.5) discard;
          if (u_activeInstanceIdx >= 0.0 && abs(float(v_instanceIdx) - u_activeInstanceIdx) < 0.5) {
            gl_FragColor.rgb = mix(gl_FragColor.rgb, vec3(1.0, 1.0, 1.0), 0.35);
          }
          #include <dithering_fragment>
        `)
      material.userData.shader = shader
    }
    material.customProgramCacheKey = () => 'atomImpostor_' + material.uuid
    material.userData.isImpostor = true
    material.userData.isAtomImpostor = true
  }

  // Build the per-source atom-impostor batch (one InstancedMesh per element).
  // Reuses the source's instance-transform + visibility textures. Marks the
  // source `isAtomistic` (→ skipped by the LOD updater; renders all atoms at
  // detail) and hides the source's CG / mid / hull geometry.
  async function _buildAtomImpostorBatch(srcEntry, instId, uniformsBundle, numInstances, helixGroup, atomRep = 'vdw', vdwScale = 1.0) {
    // Hide the source's CG / cylinder / hull LODs and flag the source atomistic
    // UP FRONT — before the (slow, ~15 s) atomistic fetch — so its cylinders
    // never flash on screen while atoms are loading. Restore on failure.
    const _setCgVisible = (v) => {
      if (srcEntry.helixCtrl?.root)     srcEntry.helixCtrl.root.visible = v
      if (srcEntry.midLod?.mesh)        srcEntry.midLod.mesh.visible = v
      if (srcEntry.overhangLod?.mesh)   srcEntry.overhangLod.mesh.visible = v
      if (srcEntry.hullLod?.mesh)       srcEntry.hullLod.mesh.visible = v
      if (srcEntry.hullMarkerLod?.mesh) srcEntry.hullMarkerLod.mesh.visible = v
      if (srcEntry.curvedCylLod?.mesh)  srcEntry.curvedCylLod.mesh.visible = v
    }
    srcEntry.isAtomistic = true
    _setCgVisible(false)

    let atomData
    try {
      atomData = await api.getInstanceAtomisticGeometry(instId)
    } catch (err) {
      console.warn('[shared_renderer] atomistic geometry fetch failed:', err)
      srcEntry.isAtomistic = false
      _setCgVisible(true)
      return false
    }
    const atoms = atomData?.atoms ?? []
    if (!atoms.length) { srcEntry.isAtomistic = false; _setCgVisible(true); return false }

    const byEl = new Map()
    for (const a of atoms) {
      const el = a.element || 'C'
      if (!byEl.has(el)) byEl.set(el, [])
      byEl.get(el).push(a)
    }

    // Coloring context (reused by _recolorAtomBatch on mode change) — resolves
    // the same colors the CG path uses so atoms match beads/cylinders.
    const design = srcEntry.design
    const strandType = new Map((design?.strands ?? []).map(s => [s.id, s.strand_type]))
    const ctx = {
      stapleColorMap: buildStapleColorMap(srcEntry.nucleotides, design),
      customColors:   srcEntry.customColors,
      clusterFn:      buildClusterLookup(design),
      strandType,
      sourceColor:    _srcColorHex(srcEntry.group.userData.sharedSource),
    }
    srcEntry._atomCtx = ctx
    const mode = _atomColorMode(store.getState().coloringMode)

    const batch = []
    for (const [el, list] of byEl) {
      const numAtoms = list.length
      const posFlat = new Float32Array(numAtoms * 3)
      for (let i = 0; i < numAtoms; i++) {
        posFlat[i * 3 + 0] = list[i].x
        posFlat[i * 3 + 1] = list[i].y
        posFlat[i * 3 + 2] = list[i].z
      }
      const { tex: atomPosTex } = _makeAtomPosTexture(posFlat, numAtoms)
      const { tex: atomColorTex } = _makeAtomColorTexture(_computeAtomColorRGB(list, mode, ctx), numAtoms)
      const elDef = ELEMENTS[el] || DEFAULT_ELEMENT
      // VDW = per-element van-der-Waals radius (space-fill); ball-and-stick = a
      // fixed small ball radius (matches the design-view atomistic renderer).
      const radius = (atomRep === 'ballstick' ? BALL_RADIUS : elDef.vdw) * vdwScale
      // White base — per-atom color rides the u_atomColor texture (multiplied in).
      const mat = new THREE.MeshPhongMaterial({ color: 0xffffff, side: THREE.DoubleSide })
      _attachAtomImpostorShader(mat, {
        uXform: uniformsBundle.uXform,
        uVis: uniformsBundle.uVis,
        uActiveIdx: uniformsBundle.uActiveIdx,
        uAtomPos: { value: atomPosTex },
        uAtomColor: { value: atomColorTex },
        numAtoms,
        radius,
      })
      const mesh = new THREE.InstancedMesh(IMPOSTOR_QUAD, mat, numInstances * numAtoms)
      // Collapse instanceMatrix to a single identity row (the shader ignores it;
      // this avoids a count×64-byte allocation). meshPerAttribute = count.
      const identityArr = new Float32Array(16)
      identityArr[0] = identityArr[5] = identityArr[10] = identityArr[15] = 1
      const idAttr = new THREE.InstancedBufferAttribute(identityArr, 16, false, mesh.count)
      idAttr.setUsage(THREE.StaticDrawUsage)
      mesh.instanceMatrix = idAttr
      mesh.instanceMatrix.needsUpdate = true
      mesh.frustumCulled = false
      mesh.name = `atomImpostor_${el}`
      // Carries a custom instancing shader — photo mode's _swapMaterials must
      // skip it (a stock material swap would drop the shader → atoms collapse).
      mesh.userData.sharedLodImpostor = true
      helixGroup.add(mesh)
      batch.push({ mesh, posTex: atomPosTex, colorTex: atomColorTex, atomList: list })
    }

    srcEntry.atomBatch = batch
    // CG/cylinder/hull LODs were hidden + isAtomistic flagged up front.
    return true
  }

  // ── Surface representation (assembly) ───────────────────────────────────────
  // One molecular-surface mesh per source (source-local), instanced at each
  // placement transform. Unlike beads/atoms there's no per-vertex texture: the
  // surface is a single BufferGeometry drawn N times via a plain InstancedMesh
  // whose instanceMatrix holds each instance's world transform.
  const _SURFACE_PROBE_RADIUS = 0.28   // nm — SES smoothness (matches design view)

  async function _buildSurfaceBatch(srcEntry, instId, numInstances, helixGroup, instancesForKey) {
    // Hide CG + flag isSurface UP FRONT so cylinders don't flash during the
    // (slow) surface compute. Restore on failure.
    const _setCgVisible = (v) => {
      if (srcEntry.helixCtrl?.root)     srcEntry.helixCtrl.root.visible = v
      if (srcEntry.midLod?.mesh)        srcEntry.midLod.mesh.visible = v
      if (srcEntry.overhangLod?.mesh)   srcEntry.overhangLod.mesh.visible = v
      if (srcEntry.hullLod?.mesh)       srcEntry.hullLod.mesh.visible = v
      if (srcEntry.hullMarkerLod?.mesh) srcEntry.hullMarkerLod.mesh.visible = v
      if (srcEntry.curvedCylLod?.mesh)  srcEntry.curvedCylLod.mesh.visible = v
    }
    srcEntry.isSurface = true
    _setCgVisible(false)

    const colorMode = (store.getState().coloringMode === 'uniform') ? 'uniform' : 'strand'
    let data
    try {
      data = await api.getInstanceSurfaceGeometry(instId, colorMode, _SURFACE_PROBE_RADIUS)
    } catch (err) {
      console.warn('[shared_renderer] surface fetch failed:', err)
      srcEntry.isSurface = false; _setCgVisible(true); return false
    }
    if (!data?.vertices?.length || !data?.faces?.length) {
      srcEntry.isSurface = false; _setCgVisible(true); return false
    }

    const geo = new THREE.BufferGeometry()
    geo.setAttribute('position', new THREE.BufferAttribute(new Float32Array(data.vertices), 3))
    geo.setIndex(new THREE.BufferAttribute(new Uint32Array(data.faces), 1))
    geo.computeVertexNormals()

    // Per-vertex strand-id table → recolor client-side (no re-fetch on mode change).
    const mat = new THREE.MeshStandardMaterial({
      vertexColors: true, color: 0xffffff, roughness: 0.65, metalness: 0.0, side: THREE.DoubleSide,
    })
    const mesh = new THREE.InstancedMesh(geo, mat, Math.max(1, numInstances))
    mesh.count = numInstances
    const _m = new THREE.Matrix4()
    for (let i = 0; i < numInstances; i++) {
      const inst = instancesForKey[i]
      // Hidden instances → degenerate scale so they don't draw.
      if (inst.visible === false) { mesh.setMatrixAt(i, _m.makeScale(0, 0, 0)); continue }
      mesh.setMatrixAt(i, _instMat4(inst.transform?.values))
    }
    mesh.instanceMatrix.needsUpdate = true
    mesh.frustumCulled = false
    mesh.name = 'assemblySurface'
    mesh.userData.sharedLodImpostor = true   // skip photo material swap
    helixGroup.add(mesh)

    // Coloring context (reused by _recolorSurface on mode change). strand color
    // mirrors the CG path; cluster maps each strand to its (first domain's)
    // cluster; source is a per-source tint.
    const design = srcEntry.design
    const clusterFn = buildClusterLookup(design)
    const strandCluster = new Map()
    for (const s of design?.strands ?? []) {
      const d0 = (s.domains ?? [])[0]
      if (!d0) continue
      const ci = clusterFn({ helix_id: d0.helix_id, strand_id: s.id, domain_index: 0 })
      if (ci != null) strandCluster.set(s.id, ci)
    }
    srcEntry._surfaceCtx = {
      stapleColorMap: buildStapleColorMap(srcEntry.nucleotides, design),
      customColors:   srcEntry.customColors,
      strandType:     new Map((design?.strands ?? []).map(s => [s.id, s.strand_type])),
      strandCluster,
      sourceColor:    _srcColorHex(srcEntry.group.userData.sharedSource),
    }
    srcEntry.surfaceMesh = {
      mesh, geo, mat,
      strandTable:     data.vertex_strand_index_table ?? [],
      vertexStrandIdx: data.vertex_strand_index ?? null,
    }
    _recolorSurface(srcEntry, store.getState().coloringMode)
    return true
  }

  // Walk a helixCtrl.root and patch every InstancedMesh's material with the
  // shader. The per-bp local matrices written by `buildHelixObjects` into
  // `instanceMatrix` are EXTRACTED into a per-mesh DataTexture (one bp's
  // matrix per row) and then `instanceMatrix` is collapsed to a single
  // identity row via `meshPerAttribute = mesh.count`. The mesh's `count`
  // is set to `bp_count × num_instances`; `gl_InstanceID` indexes both
  // dimensions, decomposed in the shader as
  //     instanceIdx = gl_InstanceID / bp_count
  //     bpIdx       = gl_InstanceID % bp_count
  // and `world = instTransform[instanceIdx] * bpMat[bpIdx] * position`.
  //
  // Memory: per InstancedMesh, per-bp data is now stored ONCE per source
  // (64 × bp bytes), not N times. At bp=61k, N=500 that's ~4 MB vs ~1.9 GB.
  // Cylinder-LOD meshes built by buildHelixObjects.  At 'full' rep these
  // still get allocated with count=helixCount (for downstream setDetailLevel
  // toggling on the per-instance path) but are invisible.  The shared path
  // serves mid LOD via the dedicated `sharedLodMid` InstancedMesh, so we
  // skip patching these — otherwise close-LOD bucketing would render bp
  // meshes AND cylinders on top of each other (the "Full + Cylinders both
  // render" double-draw + slowdown observed at rep='full').
  const _SKIP_MESH_NAMES = new Set([
    'helixCylinders',
    'overhangCylinders',
    'overhangFullCylinders',
    'curvedHelixCylindersProxy',
    'curvedOverhangCylindersProxy',
    'curvedOverhangFullCylindersProxy',
  ])

  // Linker binding/bridge cylinders are cylinder-LOD meshes, but UNLIKE the
  // per-helix cylinders above they have NO sharedLodMid equivalent — they ARE
  // the linker's only cylinder representation. They're populated at every rep
  // by buildHelixObjects, so they need rep-aware handling (see _patchSharedMeshes):
  //   • full / beads build → hide (the linker's complement + bridge nucs draw
  //     as real bp beads, so a cylinder on top is the bug the user reported);
  //   • cylinders build → patch + force-visible, but DON'T add to activeMeshes
  //     (the close bucket, which the LOD updater zeroes at cylinders rep) — they
  //     draw alongside sharedLodMid as the linker's cylinder rep.
  const _LINKER_CYL_NAMES = new Set([
    'linkerBindingCylinders',
    'linkerBridgeCylinders',
  ])

  function _patchSharedMeshes(helixCtrl, numInstances, uniformsBundle, activeMeshes, source, rep) {
    if (!helixCtrl?.root) return
    helixCtrl.root.traverse(obj => {
      if (!(obj instanceof THREE.InstancedMesh)) return
      const isLinkerCyl = _LINKER_CYL_NAMES.has(obj.name)
      // Linker cylinders only represent the linker at the cylinders rep; at
      // full/beads the linker draws as bp beads, so hide them there.
      if (isLinkerCyl && rep !== 'cylinders') {
        obj.visible = false
        obj.count = 0
        return
      }
      if (_SKIP_MESH_NAMES.has(obj.name)) {
        // Hide outright so the un-patched cylinder mesh doesn't render at
        // its baseCount with stock material at the source origin.
        obj.visible = false
        obj.count = 0
        return
      }
      const baseCount = obj.count
      if (baseCount === 0) return
      const newCount = baseCount * numInstances

      // ── Extract per-bp matrices into a per-mesh DataTexture ──────────────
      const { tex: bpTex, data: bpData } = _makeBpXformTexture(
        obj.instanceMatrix.array, baseCount,
      )

      // ── Collapse `instanceMatrix` to a single identity row ───────────────
      // Three.js's `<project_vertex>` auto-applies `instanceMatrix * mvPosition`
      // when USE_INSTANCING is on. With `meshPerAttribute = mesh.count`, the
      // vertex-attribute divisor is `count`, so every rendered instance reads
      // the SAME single matrix slot. We make that slot identity → no-op.
      const identityArr = new Float32Array(16)
      identityArr[0]  = 1
      identityArr[5]  = 1
      identityArr[10] = 1
      identityArr[15] = 1
      const idAttr = new THREE.InstancedBufferAttribute(identityArr, 16, false, newCount)
      idAttr.setUsage(THREE.StaticDrawUsage)
      obj.instanceMatrix = idAttr
      obj.instanceMatrix.needsUpdate = true

      // ── Extract per-bp colors into a per-mesh DataTexture ──────────────
      // Same pattern as bp matrices: pull the per-bp colors out of
      // instanceColor.array into a 1×bpCount RGBA Float texture so the
      // shader can sample them by bpIdx. Memory: 16 bytes × bpCount per
      // mesh, identical across all source-instances (the strand color
      // pattern is part of the source, not per-instance).
      let bpColorTex = null
      if (obj.instanceColor) {
        const colorArr = obj.instanceColor.array  // bpCount × 3 floats RGB
        // 2D tile layout mirrors _makeBpXformTexture: W texels per row, one
        // RGBA texel per bp.  Each row holds 4*W floats = W bp colors, so
        // bp i still lives at float offset i*4 in the typed array.
        const tileW = _BP_TEX_TILE_W
        const h = Math.max(1, Math.ceil(baseCount / tileW))
        const colorData = new Float32Array(tileW * h * 4)
        for (let i = 0; i < baseCount; i++) {
          colorData[i * 4 + 0] = colorArr[i * 3 + 0]
          colorData[i * 4 + 1] = colorArr[i * 3 + 1]
          colorData[i * 4 + 2] = colorArr[i * 3 + 2]
          colorData[i * 4 + 3] = 1.0
        }
        bpColorTex = new THREE.DataTexture(
          colorData, tileW, h, THREE.RGBAFormat, THREE.FloatType,
        )
        bpColorTex.minFilter = THREE.NearestFilter
        bpColorTex.magFilter = THREE.NearestFilter
        bpColorTex.generateMipmaps = false
        bpColorTex.needsUpdate = true
        obj.instanceColor = null  // drop the tiled buffer; colors live in texture now
      }

      obj.count = newCount

      // Frustum culling reads the geometry's bounding sphere/box only — for
      // an instanced shared source it's wildly wrong. Disable it.
      obj.frustumCulled = false

      // `buildHelixObjects` allocates multiple LOD-specific InstancedMeshes
      // (bead/cone/slab for full; helixCylinders/overhangCylinders for
      // cylinders rep) and relies on a downstream `setDetailLevel(rep)` call
      // to flip `visible` per LOD. The shared path never runs setDetailLevel,
      // so even cylinder rep meshes with valid count stay invisible.
      // Force-enable any mesh that we just sized up — count > 0 here means
      // buildHelixObjects allocated real geometry for it under the requested
      // LOD, so it MUST render.
      obj.visible = true

      // Track-B instrumentation: when window.NADOC_DBG_RENDER_TRACE is true,
      // every shared-renderer InstancedMesh increments a counter via its
      // onBeforeRender callback. `__NADOC_DBG__.traceFrame()` reads + prints
      // the counts plus renderer.info totals so we can SEE whether these
      // meshes are actually being drawn vs silently culled.
      const _prevOnBefore = obj.onBeforeRender
      obj.onBeforeRender = function (renderer, scene, camera, geometry, mat, group) {
        if (_prevOnBefore) _prevOnBefore.call(this, renderer, scene, camera, geometry, mat, group)
        if (typeof window !== 'undefined' && window.NADOC_DBG_RENDER_TRACE) {
          if (!renderer._nadocTrace) renderer._nadocTrace = new Map()
          const id = (obj.name || 'unnamed') + '#' + obj.id
          renderer._nadocTrace.set(id, (renderer._nadocTrace.get(id) || 0) + 1)
        }
      }

      // Attach the per-source + per-mesh uniforms to this material.
      // `uBpTex` is a NEW per-mesh sampler2D pointing at this mesh's bp
      // matrix texture. `uBpColorTex` is the optional per-bp color texture
      // (only present if the original mesh had instanceColor). The other
      // uniforms (xform, vis, active) are shared across the source.
      const uBpTex      = { value: bpTex }
      const uBpColorTex = { value: bpColorTex }  // null when no per-bp colors
      const meshUniforms = {
        uXform:      uniformsBundle.uXform,
        uActiveIdx:  uniformsBundle.uActiveIdx,
        uVis:        uniformsBundle.uVis,
        uBpTex,
        uBpColorTex,
        hasBpColor:  bpColorTex !== null,
      }
      const mat = obj.material
      const mats = Array.isArray(mat) ? mat : [mat]
      for (const m of mats) {
        _attachInstanceShader(m, meshUniforms, baseCount)
      }

      // Phase 7d: photo mode replaces every InstancedMesh material with a
      // MeshPhysicalMaterial. Without the instancing vertex patch those
      // instances collapse to the source origin. Stash a re-apply closure
      // (captures THIS mesh's uniforms + bp count) so photo_renderer can
      // re-inject the patch onto the swapped material; tag for skip-logic.
      obj.userData.sharedInstanced = true
      obj.userData.sharedBaseCount = baseCount
      // Exact source-local matrices uploaded to u_bpXform. Kept as a debug
      // seam so the part/assembly parity harness can distinguish bad source
      // transforms from bad GPU composition without a texture readback.
      obj.userData.sharedBpXformData = bpData
      obj.userData.applySharedInstancing = (material) => {
        const list = Array.isArray(material) ? material : [material]
        for (const mm of list) _attachInstanceShader(mm, meshUniforms, baseCount)
      }

      // Stash bp-texture handles on the source's render-data list so
      // `_disposeSource` can release them.
      if (source) {
        source.bpTextures.push(bpTex)
        if (bpColorTex) source.bpTextures.push(bpColorTex)
      }

      // Record bpColorTex/bpColorData on the activeMeshes entry so
      // `updateStrandColor` can rewrite them after a UI color change.
      // bpColorData is the backing Float32Array (baseCount × 4 RGBA floats).
      const bpColorData = bpColorTex ? bpColorTex.image.data : null
      // Linker cylinders are NOT close-bucket meshes — keep them out of
      // activeMeshes so the per-frame LOD updater (which zeroes the close
      // bucket at cylinders rep) doesn't hide them. They stay force-visible
      // (set above) as the linker's cylinder rep alongside sharedLodMid.
      if (!isLinkerCyl) {
        activeMeshes.push({ mesh: obj, baseCount, bpTex, bpData, bpColorTex, bpColorData })
      }
    })
  }

  // ── Local-bbox helper for one source ──────────────────────────────────────
  // Walks the helixCtrl.root and unions every InstancedMesh's per-bp instance
  // matrix into a local AABB. Per-bp matrices are the SAME across all
  // source-instances (only the outer instTransform differs), so we only need
  // to iterate baseCount-many slots.
  function _computeSourceLocalBox(helixCtrl) {
    const out = new THREE.Box3()
    if (!helixCtrl?.root) return out
    const tmpMat = new THREE.Matrix4()
    const tmpBox = new THREE.Box3()
    helixCtrl.root.traverse(obj => {
      if (!(obj instanceof THREE.InstancedMesh)) return
      if (obj.count === 0) return
      if (!obj.geometry.boundingBox) obj.geometry.computeBoundingBox()
      const baseBox = obj.geometry.boundingBox
      // baseCount per source-instance — but per-bp slots are pattern-tiled,
      // so iterating any one tile is enough. We assume baseCount = count /
      // num_instances and read it from `userData.sharedBase` set by patching;
      // fallback: read the first `count` slots.
      const baseCount = obj.userData.sharedBase ?? obj.count
      for (let i = 0; i < baseCount; i++) {
        obj.getMatrixAt(i, tmpMat)
        if (tmpMat.elements[15] < 0.5) continue
        tmpBox.copy(baseBox).applyMatrix4(tmpMat)
        out.union(tmpBox)
      }
    })
    return out
  }

  // Compute a source's LOCAL bounding box from the actually-rendered
  // shared-LOD cylinder matrices (mid + overhang).  Each LOD's
  // `segXformData` holds one column-major mat4 per segment at float offset
  // i*16 (2D-tiling preserves byte order).  Transform the unit cylinder /
  // half-cylinder geometry box by each segment matrix and union.  Bounds
  // exactly what's drawn — unlike _computeSourceLocalBox which used the
  // legacy (un-drawn) bp meshes.
  function _computeLodLocalBox(midLod, overhangLod) {
    const out = new THREE.Box3()
    const tmpMat = new THREE.Matrix4()
    const tmpBox = new THREE.Box3()
    if (!_LOD_CYL_GEO.boundingBox) _LOD_CYL_GEO.computeBoundingBox()
    if (!_LOD_HALF_CYL_GEO.boundingBox) _LOD_HALF_CYL_GEO.computeBoundingBox()
    const addLod = (lod, geoBox) => {
      if (!lod?.segXformData || !geoBox) return
      const data = lod.segXformData
      for (let i = 0; i < lod.numSegments; i++) {
        const off = i * 16
        const e = tmpMat.elements
        for (let k = 0; k < 16; k++) e[k] = data[off + k]
        if (e[15] < 0.5) continue
        tmpBox.copy(geoBox).applyMatrix4(tmpMat)
        out.union(tmpBox)
      }
    }
    addLod(midLod, _LOD_CYL_GEO.boundingBox)
    addLod(overhangLod, _LOD_HALF_CYL_GEO.boundingBox)
    return out
  }

  // ── Build one source entry ────────────────────────────────────────────────
  async function _buildSource(srcKey, srcDesignData, instancesForKey) {
    const { nucleotides, helix_axes, design } = srcDesignData
    if (!nucleotides || !design) return null

    // Build at the most-detailed LOD that any instance in this source needs.
    // Per-instance ``representation`` selects which LOD draws via
    // _updateLodForSource's lodCap mapping, but the underlying InstancedMeshes
    // must exist (non-zero count) — _patchSharedMeshes early-returns on
    // count==0 (L2428).  Choosing 'full' indiscriminately would allocate
    // backbone-bead DataTextures of size 1×baseCount per LOD mesh, which
    // overflows WebGL's MAX_TEXTURE_SIZE on large origami sources (~16k+ bp).
    //   Strategy: pick the deepest LOD any instance needs (`full` < `beads` <
    //   `cylinders`), so cylinders-only sources still avoid the bp-texture
    //   cost.  If the source's bp count exceeds GPU texture limits, cap the
    //   build at 'cylinders' regardless of per-instance rep — those instances
    //   will fall to the mid bucket via the LOD cap below.
    // Deepest LOD any instance needs: 'full' (beads + slabs) > 'beads' (beads +
    // cones, NO slabs) > 'cylinders'. Building 'beads' instead of 'full' makes
    // buildHelixObjects skip the slab InstancedMesh entirely, so the shared
    // path's force-visible loop has no slab mesh to show — fixing slabs leaking
    // into the beads-only representation. (Mixed full+beads on ONE source still
    // shows slabs on the beads instances since they share the slab mesh; the
    // global rep menu sets all instances the same, which is the common case.)
    let rep = 'cylinders'
    for (const inst of instancesForKey) {
      const r = inst.representation
      if (r === 'full') { rep = 'full'; break }   // deepest — stop scanning
      if (r === 'beads') rep = 'beads'            // keep scanning in case a 'full' follows
    }
    const numInstances = instancesForKey.length

    // ── Hull-prism source geometry ───────────────────────────────────────────
    // Build the design-view Hull Prism solid ONCE per source in source-local
    // coordinates (the InstancedMesh, built later after srcEntry exists, draws
    // it at every hull-prism instance's transform).  _hullGeoForSource mirrors
    // the FULL single-design decision tree (extrusion boxes → cross-section
    // scan → per-cluster cross-section scan) AND builds the overhang face
    // markers, so each part looks the same here as in the design view.  Built
    // here (early) because the per-instance LOD-cap fill below must know whether
    // a hull exists, to demote hull-prism instances to cylinders rather than
    // leave them invisible when none could be produced.
    const hull = _hullGeoForSource(design, nucleotides, helix_axes ?? null)
    const hasHull = !!hull?.solid

    // Build a single helixCtrl with the canonical bp matrices.
    const helixGroup = new THREE.Group()
    helixGroup.userData.sharedSource = srcKey
    const customColors = {}
    for (const strand of design.strands ?? []) {
      if (strand.color) customColors[strand.id] = parseInt(strand.color.replace(/^#/, ''), 16)
    }
    const helixCtrl = buildHelixObjects(
      nucleotides, design, helixGroup, customColors, [], helix_axes ?? null, rep,
    )
    // Match the individual-part renderer: crossover insertions have their own
    // bead/slab/connector meshes and must be present before shared-instancing
    // patches every InstancedMesh in the source tree.
    const stapleColorMap = buildStapleColorMap(nucleotides, design)
    const xoverResult = buildCrossoverConnections(
      design, nucleotides, stapleColorMap, customColors,
    )
    if (xoverResult) helixCtrl.root.add(xoverResult.group)
    // Assembly mode never needs the helix axis arrows — they're meant for
    // single-design editing (and were the only thing visible at default
    // zoom on large assemblies, which looked like clutter).  Hide them so
    // they don't pay per-frame matrix/cull cost either.
    helixCtrl.setAxisArrowsVisible?.(false)

    // Per-source uniforms (xform texture + active-instance index + visibility).
    const { tex: xformTex,  data: xformData  } = _makeXformTexture(numInstances)
    const { tex: visTex,    data: visData    } = _makeXformTexture(numInstances)
    const uActiveIdx = { value: -1 }
    const uXform     = { value: xformTex }
    const uVis       = { value: visTex }
    const uniformsBundle = { uXform, uActiveIdx, uVis }

    // Tag InstancedMeshes with baseCount BEFORE patching so the bbox walker
    // can find the per-bp tile size after patching multiplies it.
    helixCtrl.root.traverse(obj => {
      if (obj instanceof THREE.InstancedMesh) obj.userData.sharedBase = obj.count
    })

    // Compute per-source local bbox BEFORE we patch (count is still baseCount).
    const instBoundingBox = _computeSourceLocalBox(helixCtrl)

    // Patch shader + collapse InstancedMesh.instanceMatrix + extract per-bp
    // matrices into per-mesh DataTextures. We pass a transient holder so the
    // patch helper can register textures for disposal.
    const activeMeshes = []
    const sourceCollector = { bpTextures: [] }
    _patchSharedMeshes(helixCtrl, numInstances, uniformsBundle, activeMeshes, sourceCollector, rep)

    // ── Memory-savings probe (debug visibility into the per-source budget) ──
    // Compute the byte count of the per-bp DataTextures (NEW) + the
    // per-instance transform texture (also Phase 3c). Compare with what the
    // OLD instanceMatrix-tile path would have cost (16 × baseCount × N × 4
    // per InstancedMesh).
    let bpBytes = 0
    let oldTileBytes = 0
    for (const m of activeMeshes) {
      bpBytes += m.bpData.byteLength
      oldTileBytes += 16 * m.baseCount * numInstances * 4
    }
    const xformBytes = xformData.byteLength + visData.byteLength
    if (typeof console !== 'undefined' && console.info) {
      console.info(
        `[shared_renderer] source=${srcKey} N=${numInstances} ` +
        `bp-texture=${(bpBytes/1024/1024).toFixed(2)} MB, ` +
        `inst-texture=${(xformBytes/1024).toFixed(1)} KB ` +
        `(was ${(oldTileBytes/1024/1024).toFixed(2)} MB tiled in instanceMatrix; ` +
        `saved ${((oldTileBytes - bpBytes)/1024/1024).toFixed(2)} MB)`,
      )
    }

    // Per-instance bookkeeping.
    const instanceIds  = instancesForKey.map(i => i.id)
    const instanceIndex = new Map(instanceIds.map((id, idx) => [id, idx]))
    const visibility = new Float32Array(numInstances)
    // Per-instance LOD cap (Int8: 0 = close ok, 1 = no close, 2 = far only,
    // 3 = hull).  Read at every _updateLodForSource frame to bias bucketing by
    // the per-instance ``representation`` field.  ``buildRepCap`` floors the
    // cap when the source was built without close-bucket bp meshes (i.e.
    // 'cylinders') — without it, an instance with rep='full'/'beads' would
    // bucket close but find empty bp meshes.  Both 'full' AND 'beads' builds
    // DO allocate bead/cone bp meshes (beads just skips slabs), so both floor
    // to 0; only 'cylinders' floors to 1.
    const buildRepCap = (rep === 'full' || rep === 'beads') ? 0 : 1
    const instanceLodCap = new Int8Array(numInstances)
    // Fill xform + visibility texture data.
    for (let i = 0; i < numInstances; i++) {
      const inst = instancesForKey[i]
      const m = _instMat4(inst.transform?.values)
      _packMatrixIntoRow(m, xformData, i * 16)
      visibility[i] = (inst.visible !== false) ? 1.0 : 0.0
      visData[i * 16 + 0] = visibility[i]
      // Hull cap (3) needs the hull InstancedMesh to exist; if this source
      // produced no hull geometry, demote hull-prism instances to cylinders
      // (1) so they stay visible instead of bucketing to a non-existent mesh.
      // Clamp BEFORE the Math.max so the demotion isn't undone.
      let cap = _repToLodCap(inst.representation)
      if (cap === 3 && !hasHull) cap = 1
      instanceLodCap[i] = Math.max(buildRepCap, cap)
      // Other channels unused; leave zero.
      _instToSrc.set(inst.id, srcKey)
    }
    xformTex.needsUpdate = true
    visTex.needsUpdate   = true

    // Lines cannot use the InstancedMesh shader path. Keep one local-space
    // line group per placement, sharing the exact crossover endpoints used by
    // the part renderer and inheriting that placement's assembly transform.
    const crossoverArcGroup = _buildSharedCrossoverArcs(
      helixCtrl.getCrossHelixConnections(), instancesForKey, _instMat4,
      store.getState().showPeriodicSeamArcs === true,
    )
    if (crossoverArcGroup) helixGroup.add(crossoverArcGroup)

    scene.add(helixGroup)

    const srcEntry = {
      group: helixGroup,
      helixCtrl,
      design,
      nucleotides,
      helixAxes: helix_axes ?? null,
      rep,                    // representation/LOD — needed to re-run buildHelixObjects
      customColors,           // strandId → hex (live, mutated by updateStrandColor)
      numBpPerInstance: 0,    // not used directly — each mesh carries its baseCount in userData
      instanceIds,
      instanceIndex,
      visibility,
      instanceLodCap,
      xformTex,
      xformData,
      visTex,
      visData,
      activeMeshes,
      bpTextures: sourceCollector.bpTextures,
      uActiveIdxUniform: uActiveIdx,
      uXformUniform: uXform,
      uVisUniform: uVis,
      dirtyRows: new Set(),
      dirtyVisRows: new Set(),
      instBoundingBox,
      crossoverArcGroup,
      xoverResult,
    }

    // ── Phase 3f: build mid-LOD + far-LOD meshes for this source ─────────────
    // Find the legacy iHelixCylinders + iOverhangCylinders meshes that
    // buildHelixObjects populated.  _patchSharedMeshes's skip filter zeroed
    // their `count` but their `instanceMatrix`/`instanceColor` arrays survive
    // (and `userData.sharedBase` retains the original segment counts).
    let legacyOvhgMesh = null
    let legacyHelixCylMesh = null
    helixCtrl.root.traverse(obj => {
      if (!(obj instanceof THREE.InstancedMesh)) return
      if (obj.name === 'overhangCylinders' || obj.name === 'overhangFullCylinders') legacyOvhgMesh = legacyOvhgMesh ?? obj
      if (obj.name === 'helixCylinders')    legacyHelixCylMesh = obj
    })
    console.info(
      `[shared_renderer] source=${srcKey} legacy meshes: ` +
      `helix=${legacyHelixCylMesh ? (legacyHelixCylMesh.userData.sharedBase ?? legacyHelixCylMesh.count) : 'missing'} ` +
      `overhang=${legacyOvhgMesh ? (legacyOvhgMesh.userData.sharedBase ?? legacyOvhgMesh.count) : 'missing'}`,
    )

    // Mid LOD: ONE cylinder per helix axis (built from `helix_axes`
    // start/end), not per-strand-domain.  Matches the user's mental
    // model "non-overhang helices = one cylinder"; overhangs render
    // separately via the overhang LOD below so they still poke out.
    // legacyHelixCylMesh is passed in only as a source of per-segment
    // colour data (averaged into one colour per helix).
    if (legacyHelixCylMesh && (legacyHelixCylMesh.userData.sharedBase ?? 0) > 0) {
      const origCount = legacyHelixCylMesh.userData.sharedBase
      legacyHelixCylMesh.count = origCount
      const midLod = _buildMidLodMesh(srcEntry, design, legacyHelixCylMesh, helixGroup)
      legacyHelixCylMesh.count = 0
      if (midLod) {
        srcEntry.midLod = midLod
        console.info(`[shared_renderer]   mid LOD built: numHelices=${midLod.numSegments}`)
      } else {
        console.warn('[shared_renderer]   _buildMidLodMesh returned null')
      }
    }

    // Overhang LOD: per-segment half-cylinders for protruding overhangs.
    // Same architecture as mid LOD, just half-cylinder geometry.
    if (legacyOvhgMesh && (legacyOvhgMesh.userData.sharedBase ?? 0) > 0) {
      const origCount = legacyOvhgMesh.userData.sharedBase
      legacyOvhgMesh.count = origCount
      const ovhgLod = _buildOverhangLodMesh(srcEntry, legacyOvhgMesh, helixGroup)
      legacyOvhgMesh.count = 0
      if (ovhgLod) {
        srcEntry.overhangLod = ovhgLod
        console.info(`[shared_renderer]   overhang LOD built: numSegments=${ovhgLod.numSegments}`)
      } else {
        console.warn('[shared_renderer]   _buildOverhangLodMesh returned null')
      }
    }
    // Recompute the source's local bbox so the selection / group box hugs what
    // the user actually sees.  Two contributors, UNIONED:
    //   1. nucleotideLocalBox — the real per-nucleotide backbone cloud.  This
    //      FOLLOWS the bend deformation that curves each helix between its
    //      endpoints, so a bent (arc) part is bounded correctly.  A box built
    //      only from the mid-LOD body cylinders collapses here: those cylinders
    //      are one straight CHORD per helix (endpoint-to-endpoint), so for a
    //      ~167° arc (e.g. the Arm_pulley torus) the box lost the entire
    //      arc-bulge axis — drawn box Z ≈ 6 nm vs real ≈ 83 nm.
    //   2. the rendered shared-LOD cylinder box (mid + overhang) — covers the
    //      radial cylinder/overhang extent that pokes slightly past the
    //      backbone centerline, and keeps the original "only the drawn slots,
    //      no empty end padding" property for offset-from-origin parts like
    //      Ultimate Polymer Hinge.
    {
      const box = nucleotideLocalBox(nucleotides) ?? new THREE.Box3()
      const visBox = _computeLodLocalBox(srcEntry.midLod, srcEntry.overhangLod)
      if (!visBox.isEmpty()) box.union(visBox)
      if (!box.isEmpty()) srcEntry.instBoundingBox = box
    }

    // Hull LOD: one instanced grey extrusion-box solid per hull-prism instance
    // (distance-independent — see _repToLodCap bucket 3).  Built from the
    // source-local hull geometry assembled at the top of _buildSource.
    if (hasHull && hull.solid) {
      const hullLod = _buildHullLodMesh(srcEntry, hull.solid, helixGroup)
      if (hullLod) {
        srcEntry.hullLod = hullLod
        const triCount = (hull.solid.attributes?.position?.count ?? 0) / 3
        console.info(`[shared_renderer]   hull LOD built: ~${triCount | 0} tris`)
      }
      // Overhang face markers — vertex-coloured quads instanced alongside the
      // hull (rides the same LOD bucket; see _updateLodForSource).
      if (hull.markers) {
        const markerLod = _buildMarkerLodMesh(srcEntry, hull.markers, helixGroup)
        if (markerLod) srcEntry.hullMarkerLod = markerLod
      }
    }

    // Curved-cylinder LOD — only for deformed sources (bake returns null for a
    // straight part). Lets bent parts show capped, strand-coloured cylinders at
    // every instance in the cylinder rep (mid bucket); see _updateLodForSource.
    {
      const curvedCylGeo = _curvedCylGeoForSource(helixCtrl)
      if (curvedCylGeo) {
        const ccl = _buildCurvedCylLodMesh(srcEntry, curvedCylGeo, helixGroup)
        if (ccl) {
          srcEntry.curvedCylLod = ccl
          const tris = (curvedCylGeo.attributes?.position?.count ?? 0) / 3
          console.info(`[shared_renderer]   curved-cyl LOD built: ~${tris | 0} tris`)
        }
      }
    }

    // Seed per-helix colours from the current coloringMode.  Pre-per-helix
    // implementation tinted the mid-LOD by an averaged flat colour, which
    // dimmed cylinder rendering (scaffold's dark navy dominated the
    // average).  Now the seed populates a per-helix texture instead, so
    // each cylinder picks up its own strand colour and the legacy
    // per-instance look is preserved on the shared path.
    try { _applyColorsToSource(srcEntry, null) }
    catch (err) { console.warn('[shared_renderer] initial colour seed failed:', err) }

    // The shared LODs carry custom shaders that compose placement transforms.
    // Preserve that patch as a material-reinstaller so photo mode can use the
    // SAME physical material as the equivalent single-design representation.
    // Keeping the editor's Lambert material here made a one-instance assembly
    // respond only half as strongly to the key and almost not at all to its
    // shadow, despite a correct shadow map.
    for (const m of [srcEntry.midLod?.mesh, srcEntry.overhangLod?.mesh, srcEntry.hullLod?.mesh, srcEntry.hullMarkerLod?.mesh, srcEntry.curvedCylLod?.mesh]) {
      if (!m) continue
      m.userData.sharedLodImpostor = true
      const compileSharedLod = m.material?.onBeforeCompile
      if (typeof compileSharedLod === 'function') {
        m.userData.applySharedInstancing = material => {
          const materials = Array.isArray(material) ? material : [material]
          for (const target of materials) {
            target.onBeforeCompile = compileSharedLod
            target.customProgramCacheKey = () => `photoSharedLod_${m.name}_${target.uuid}`
          }
        }
      }
    }

    // ── Phase C: atomistic sources → per-source atom-impostor batch ───────────
    // When every instance of this source is vdw/ballstick (the common case — the
    // rep menu sets all instances the same), render the atoms as impostors and
    // hide the CG/hull geometry. Mixed-rep sources fall back to the per-instance
    // LOD cap (vdw/ballstick → hull) as before.
    const _allAtomistic = numInstances > 0 && instancesForKey.every(
      i => i.representation === 'vdw' || i.representation === 'ballstick')
    const _allSurface = numInstances > 0 && instancesForKey.every(
      i => i.representation === 'surface')
    if (_allSurface) {
      // Molecular surface — one mesh per source, instanced at each placement.
      await _buildSurfaceBatch(srcEntry, instancesForKey[0].id, numInstances, helixGroup, instancesForKey)
    } else if (_allAtomistic) {
      const atomRep = instancesForKey[0].representation   // 'vdw' | 'ballstick'
      await _buildAtomImpostorBatch(srcEntry, instancesForKey[0].id, uniformsBundle, numInstances, helixGroup, atomRep)
    }

    return srcEntry
  }

  // ── Dispose one source entry ──────────────────────────────────────────────
  function _disposeSource(srcEntry) {
    if (!srcEntry) return
    srcEntry.group.traverse(obj => {
      if (obj.geometry && !obj.geometry.userData?.shared) obj.geometry.dispose()
      if (obj.material) {
        const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
        mats.forEach(m => m.dispose())
      }
    })
    scene.remove(srcEntry.group)
    srcEntry.xformTex?.dispose()
    srcEntry.visTex?.dispose()
    if (srcEntry.bpTextures) {
      for (const t of srcEntry.bpTextures) t.dispose()
    }
    // Phase 3f — release per-source LOD textures (mid-LOD per-segment
    // matrix + colour textures, plus the same pair for overhang LOD; far-
    // LOD has no extra texture beyond xformTex which is released above).
    if (srcEntry.atomBatch) {
      for (const b of srcEntry.atomBatch) { b.posTex?.dispose(); b.colorTex?.dispose() }
    }
    srcEntry.midLod?.segXformTex?.dispose()
    srcEntry.midLod?.segColorTex?.dispose()
    srcEntry.overhangLod?.segXformTex?.dispose()
    srcEntry.overhangLod?.segColorTex?.dispose()
    for (const id of srcEntry.instanceIds) _instToSrc.delete(id)
  }

  // ╔══════════════════════════════════════════════════════════════════════════╗
  // ║  Phase 3f — three-tier LOD ladder                                        ║
  // ║                                                                          ║
  // ║  Per source, the close-LOD path (already in place above) is augmented   ║
  // ║  by two additional InstancedMesh sets that share the same per-source    ║
  // ║  `xformTex` (per-instance world transforms):                             ║
  // ║                                                                          ║
  // ║    • Mid LOD  — one unit-cylinder InstancedMesh.                         ║
  // ║                 count = numHelices × numInstances.                       ║
  // ║                 Pre-baked per-helix transform stored in a per-source     ║
  // ║                 `helixXformTex` (4 RGBA texels × numHelices rows).       ║
  // ║                 Shader composes  world = instTransform × helixCylMat ×   ║
  // ║                 position. `gl_InstanceID` decomposes as                  ║
  // ║                   instanceIdx = gl_InstanceID / numHelices              ║
  // ║                   helixIdx    = gl_InstanceID % numHelices              ║
  // ║                                                                          ║
  // ║    • Hull LOD — one instanced grey extrusion-box solid.                  ║
  // ║                 count = numInstances. Distance-independent: far-away     ║
  // ║                 close/mid instances collapse to this coarse solid        ║
  // ║                 instead of a billboard (which would misrepresent the     ║
  // ║                 structure under a moving camera).                        ║
  // ║                                                                          ║
  // ║  Each frame, `_updateLod(camera)` runs ONCE per source (hooked via       ║
  // ║  `onBeforeRender` on one mesh per source) and:                           ║
  // ║    1. counts how many instances fall into close / mid / far buckets;    ║
  // ║    2. sets each LOD InstancedMesh's `.count` to that bucket size ×       ║
  // ║       per-LOD multiplier;                                                ║
  // ║    3. sets `.visible = true` on any mesh whose count > 0.                ║
  // ║                                                                          ║
  // ║  STAGE 2 (sort-to-front) shipped: each frame, instances are SORTED by    ║
  // ║  camera distance and the per-source `xformTex` + `visTex` are PERMUTED   ║
  // ║  so row 0 holds the nearest visible instance, row 1 the next-nearest,    ║
  // ║  etc. Then bucket counts (N_close × baseCount on close-LOD InstancedMesh,║
  // ║  N_mid × numHelices on mid, N_far on far) are written to `mesh.count`.   ║
  // ║  Because rows 0..N_close-1 are now the actually-nearest, the close-LOD   ║
  // ║  mesh's first N_close slots render the actually-nearest N_close          ║
  // ║  instances.                                                              ║
  // ║                                                                          ║
  // ║  `srcEntry.instanceIds` and `srcEntry.instanceIndex` are kept in sync    ║
  // ║  with the permutation: `instanceIds[row]` always names the instance      ║
  // ║  currently at that row, and `instanceIndex.get(id)` returns the CURRENT  ║
  // ║  row of `id`. Any external API that today writes by stable insertion-    ║
  // ║  order index MUST look up the live row via `instanceIndex.get(id)`.     ║
  // ║  `setActiveInstance` does this lookup; `applyInlineGeometry` rebuilds.   ║
  // ║  `getInstanceCenters` / `getBoundingBox` iterate `instanceIds` so they   ║
  // ║  stay correct regardless of row order.                                   ║
  // ║                                                                          ║
  // ║  Per-frame cost at N=200: ~50 µs sort + ~30 µs full texture re-upload.   ║
  // ║  Negligible at this scale. (If profiling later shows dominance, switch   ║
  // ║  to partial `texSubImage2D` for changed rows only.)                      ║
  // ╚══════════════════════════════════════════════════════════════════════════╝

  // Default thresholds in scene units (nm). Calibrated for typical assemblies
  // — a ~30-nm origami source's bbox ≈ 30 nm wide, polymerized chain ≈
  // hundreds of nm long. close < 100 nm catches what's filling the viewport;
  // mid < 500 nm picks up most of an extended chain; far is everything else.
  // Angular-size LOD thresholds in screen-pixels.  Bucketing reads the
  // source's local bbox diagonal, projects it to screen-space using the
  // camera's vertical FoV + viewport height, and compares to these pixel
  // thresholds:
  //   instance pixel size >= _lodClosePx → close (bp detail)
  //   instance pixel size >= _lodFarPx   → mid (cylinder)
  //   instance pixel size <  _lodFarPx   → hull solid (no billboard tier)
  let _lodClosePx = 60.0
  let _lodFarPx   = 8.0

  function setLodThresholds(opts) {
    if (typeof opts?.closePx === 'number') _lodClosePx = opts.closePx
    if (typeof opts?.farPx   === 'number') _lodFarPx   = opts.farPx
  }

  // When true, _updateLodForSource skips the distance demotion and renders every
  // instance at its rep's detail bucket (full→close, cylinders→mid).  Set around
  // a photo-mode export render so large figures stay uniformly high-detail
  // instead of showing hulls for the distant parts.
  let _suppressLodDemotion = false
  function setSuppressLodDemotion(on) { _suppressLodDemotion = !!on }

  // ── Mid-LOD: per-helix transform texture ─────────────────────────────────
  // Same column-major layout as the per-source xformTex: width = 4 texels,
  // height = numHelices. Each row holds one mat4 (columns as texels).
  function _makeHelixXformTexture(helixIds, helix_axes) {
    const n = helixIds.length
    const w = 4
    const h = Math.max(1, n)
    const data = new Float32Array(w * h * 4)  // 16 floats per helix
    const tmpM = new THREE.Matrix4()
    const tmpQ = new THREE.Quaternion()
    const tmpV = new THREE.Vector3()
    const tmpS = new THREE.Vector3()
    const yAxis = new THREE.Vector3(0, 1, 0)
    const dirV  = new THREE.Vector3()
    const HELIX_CYL_RADIUS = 1.0  // nm — matches the cylinder LOD rendering
    for (let i = 0; i < n; i++) {
      const ax = helix_axes?.[helixIds[i]]
      if (!ax || !ax.start || !ax.end) {
        // No axis: write a degenerate (zero-scale) matrix. Renders nothing.
        for (let k = 0; k < 16; k++) data[i * 16 + k] = 0
        continue
      }
      const sx = ax.start[0], sy = ax.start[1], sz = ax.start[2]
      const ex = ax.end[0],   ey = ax.end[1],   ez = ax.end[2]
      const dx = ex - sx, dy = ey - sy, dz = ez - sz
      const len = Math.sqrt(dx * dx + dy * dy + dz * dz)
      if (len < 1e-6) {
        for (let k = 0; k < 16; k++) data[i * 16 + k] = 0
        continue
      }
      tmpV.set((sx + ex) * 0.5, (sy + ey) * 0.5, (sz + ez) * 0.5)
      dirV.set(dx / len, dy / len, dz / len)
      tmpQ.setFromUnitVectors(yAxis, dirV)
      tmpS.set(HELIX_CYL_RADIUS, len, HELIX_CYL_RADIUS)
      tmpM.compose(tmpV, tmpQ, tmpS)
      const e = tmpM.elements
      // THREE stores column-major (e[0..3] = col0, etc.). Direct copy.
      for (let k = 0; k < 16; k++) data[i * 16 + k] = e[k]
    }
    const tex = new THREE.DataTexture(
      data, w, h, THREE.RGBAFormat, THREE.FloatType,
    )
    tex.minFilter = THREE.NearestFilter
    tex.magFilter = THREE.NearestFilter
    tex.generateMipmaps = false
    tex.needsUpdate = true
    return { tex, data }
  }

  // ── Mid-LOD InstancedMesh + shader ───────────────────────────────────────
  // Shared cylinder geometry (radius 1.125 nm to match the legacy
  // helix_renderer's GEO_UNIT_CYL; the per-segment matrices we copy from
  // iHelixCylinders assume that radius).  Unit height — matrix scale.y
  // sizes the cylinder to the domain it represents.  Reused across sources
  // so we don't dispose it in _disposeSource; tag userData.shared = true.
  // Must be byte-for-byte equivalent in shape to helix_renderer's
  // GEO_UNIT_CYL. A former 12-vs-8 side mismatch changed facet normals,
  // silhouette coverage and shadow-map rasterization even for one identity
  // assembly instance.
  const _LOD_CYL_GEO = new THREE.CylinderGeometry(1.125, 1.125, 1, 8, 1, false)
  _LOD_CYL_GEO.userData.shared = true
  // Half-cylinder for overhang segments — closed half-tube (180° wall +
  // rectangular cut-face cap), matching helix_renderer.js's GEO_HALF_CYL.
  // The closing face turns the otherwise shell-like half-arc into a solid
  // half-cylinder when viewed from the cut side.  Visually distinguishes
  // overhang protrusions from full helix cylinders so users can spot
  // overhang domains / mate-point candidates at the cylinders LOD.
  const _LOD_HALF_CYL_GEO = (() => {
    const wall = new THREE.CylinderGeometry(1.125, 1.125, 1, 8, 1, false, 0, Math.PI)
    const face = new THREE.PlaneGeometry(2.25, 1).rotateY(-Math.PI / 2)
    const merged = mergeGeometries([wall, face])
    wall.dispose()
    face.dispose()
    merged.userData.shared = true
    return merged
  })()

  // Generic per-segment InstancedMesh builder.  Takes raw arrays of
  // per-segment matrices (matrixArray, 16 floats/segment, source-local)
  // and per-segment colors (colorArrayRGB, 3 floats/segment).  Both data
  // sources currently used:
  //   • iHelixCylinders / iOverhangCylinders: legacy InstancedMesh
  //     instanceMatrix/instanceColor arrays (per-strand-domain or
  //     per-overhang segments).
  //   • helix_axes-derived: one mat4 per helix axis, one RGB per helix
  //     averaged from strand colors (for "one cylinder per helix"
  //     mid-LOD look).
  // Packs the matrix data into a 2D-tiled DataTexture (BP_TILE_W wide
  // for big counts, same layout as bp matrices) and the colour data
  // into a 1×N RGBA texture.  Shader composes `world = instTransform ×
  // segMat × position` per `gl_InstanceID`.
  function _buildSegmentLodMesh({
    srcEntry, matrixArray, colorArrayRGB, numSegments,
    geometry, meshName, sourceGroup, side = THREE.FrontSide,
  }) {
    const numInstances = srcEntry.instanceIds.length
    if (!numSegments || numSegments === 0 || numInstances === 0) return null
    if (!matrixArray || matrixArray.length < numSegments * 16) return null

    const { tex: segXformTex, data: segXformData } = _makeBpXformTexture(
      matrixArray, numSegments,
    )

    const tileW = _BP_TEX_TILE_W
    const h = Math.max(1, Math.ceil(numSegments / tileW))
    const colorData = new Float32Array(tileW * h * 4)
    if (colorArrayRGB) {
      for (let i = 0; i < numSegments; i++) {
        colorData[i * 4 + 0] = colorArrayRGB[i * 3 + 0]
        colorData[i * 4 + 1] = colorArrayRGB[i * 3 + 1]
        colorData[i * 4 + 2] = colorArrayRGB[i * 3 + 2]
        colorData[i * 4 + 3] = 1.0
      }
    } else {
      for (let i = 0; i < numSegments; i++) {
        colorData[i * 4 + 0] = 1
        colorData[i * 4 + 1] = 1
        colorData[i * 4 + 2] = 1
        colorData[i * 4 + 3] = 1
      }
    }
    const segColorTex = new THREE.DataTexture(
      colorData, tileW, h, THREE.RGBAFormat, THREE.FloatType,
    )
    segColorTex.minFilter = THREE.NearestFilter
    segColorTex.magFilter = THREE.NearestFilter
    segColorTex.generateMipmaps = false
    segColorTex.needsUpdate = true

    const mat = new THREE.MeshLambertMaterial({ color: 0xffffff, side })
    // Per-material cache key so each source's program is independent
    // (avoids the static-cache-key trap from earlier worktree gotchas).
    const _cacheKey = meshName + '_' + mat.uuid
    mat.customProgramCacheKey = () => _cacheKey
    const u_instanceOffset = { value: 0 }
    mat.onBeforeCompile = (shader) => {
      shader.uniforms.u_instanceXform   = srcEntry.uXformUniform
      shader.uniforms.u_visibilityTex   = srcEntry.uVisUniform
      shader.uniforms.u_segXform        = { value: segXformTex }
      shader.uniforms.u_segColor        = { value: segColorTex }
      shader.uniforms.u_numSegments     = { value: numSegments }
      shader.uniforms.u_instanceOffset  = u_instanceOffset
      shader.vertexShader = shader.vertexShader
        .replace(
          '#include <common>',
          `
          #include <common>
          #define BP_TILE_W ${_BP_TEX_TILE_W}
          uniform sampler2D u_instanceXform;
          uniform sampler2D u_visibilityTex;
          uniform sampler2D u_segXform;
          uniform float u_numSegments;
          uniform float u_instanceOffset;
          varying float v_visible;
          flat varying int v_segIdx;
          `,
        )
        .replace(
          '#include <beginnormal_vertex>',
          `
          #include <beginnormal_vertex>
          // instanceMatrix is collapsed to identity, so reconstruct the same
          // placement × segment transform used below for positions. Direct
          // lighting and LightShadow.normalBias both depend on this normal.
          int normalInstanceIdx = int(floor(float(gl_InstanceID) / max(u_numSegments, 1.0))) + int(u_instanceOffset);
          int normalSegIdx = gl_InstanceID - (normalInstanceIdx - int(u_instanceOffset)) * int(u_numSegments);
          int normalSegCol = normalSegIdx % BP_TILE_W;
          int normalSegRow = normalSegIdx / BP_TILE_W;
          mat4 normalInstTransform = mat4(
            texelFetch(u_instanceXform, ivec2(0, normalInstanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(1, normalInstanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(2, normalInstanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(3, normalInstanceIdx), 0)
          );
          mat4 normalSegTransform = mat4(
            texelFetch(u_segXform, ivec2(normalSegCol * 4 + 0, normalSegRow), 0),
            texelFetch(u_segXform, ivec2(normalSegCol * 4 + 1, normalSegRow), 0),
            texelFetch(u_segXform, ivec2(normalSegCol * 4 + 2, normalSegRow), 0),
            texelFetch(u_segXform, ivec2(normalSegCol * 4 + 3, normalSegRow), 0)
          );
          objectNormal = transpose(inverse(mat3(normalInstTransform * normalSegTransform))) * objectNormal;
          #ifdef USE_TANGENT
            objectTangent = mat3(normalInstTransform * normalSegTransform) * objectTangent;
          #endif
          `,
        )
        .replace(
          '#include <begin_vertex>',
          `
          // Decompose gl_InstanceID = instanceIdx * numSegments + segmentIdx,
          // then bias instanceIdx by u_instanceOffset so this mesh reads
          // texture rows starting AFTER the close-LOD's bucket range
          // (sort-to-front packs rows by bucket).
          int instanceIdx = int(floor(float(gl_InstanceID) / max(u_numSegments, 1.0))) + int(u_instanceOffset);
          int segIdx      = gl_InstanceID - (instanceIdx - int(u_instanceOffset)) * int(u_numSegments);
          int segCol      = segIdx % BP_TILE_W;
          int segRow      = segIdx / BP_TILE_W;
          v_visible = texelFetch(u_visibilityTex, ivec2(0, instanceIdx), 0).r;
          v_segIdx = segIdx;
          mat4 instTransform = mat4(
            texelFetch(u_instanceXform, ivec2(0, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(1, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(2, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(3, instanceIdx), 0)
          );
          // Per-segment matrix from the 2D-tiled texture (4 RGBA texels per
          // mat4, packed along the row, wrapping every BP_TILE_W slots).
          mat4 segMat = mat4(
            texelFetch(u_segXform, ivec2(segCol * 4 + 0, segRow), 0),
            texelFetch(u_segXform, ivec2(segCol * 4 + 1, segRow), 0),
            texelFetch(u_segXform, ivec2(segCol * 4 + 2, segRow), 0),
            texelFetch(u_segXform, ivec2(segCol * 4 + 3, segRow), 0)
          );
          vec3 transformed = (instTransform * segMat * vec4(position, 1.0)).xyz;
          `,
        )
      shader.fragmentShader = shader.fragmentShader
        .replace(
          '#include <common>',
          `
          #include <common>
          #define BP_TILE_W ${_BP_TEX_TILE_W}
          uniform sampler2D u_segColor;
          varying float v_visible;
          flat varying int v_segIdx;
          `,
        )
        .replace(
          '#include <color_fragment>',
          `
          #include <color_fragment>
          int colorCol = v_segIdx % BP_TILE_W;
          int colorRow = v_segIdx / BP_TILE_W;
          diffuseColor.rgb *= texelFetch(u_segColor, ivec2(colorCol, colorRow), 0).rgb;
          `,
        )
        .replace(
          '#include <dithering_fragment>',
          `
          if (v_visible < 0.5) discard;
          #include <dithering_fragment>
          `,
        )
    }

    const capacity = numSegments * numInstances
    const mesh = new THREE.InstancedMesh(geometry, mat, Math.max(1, capacity))
    // Collapse instanceMatrix to identity (bp-path pattern); per-instance
    // and per-segment transforms ride in textures sampled by the shader.
    const identityArr = new Float32Array(16)
    identityArr[0] = 1; identityArr[5] = 1; identityArr[10] = 1; identityArr[15] = 1
    const idAttr = new THREE.InstancedBufferAttribute(identityArr, 16, false, Math.max(1, capacity))
    idAttr.setUsage(THREE.StaticDrawUsage)
    mesh.instanceMatrix = idAttr
    mesh.instanceMatrix.needsUpdate = true
    mesh.instanceColor = null
    mesh.count = 0
    mesh.frustumCulled = false
    // visible=true so onBeforeRender hooks fire even before _updateLod's
    // first pass (Three.js short-circuits at visible=false BEFORE the
    // callback).  drawElementsInstanced with count=0 is a no-op.
    mesh.visible = true
    mesh.name = meshName
    // CPU mirror used by the photomode parity audit; this is the exact texture
    // payload consumed by u_segColor and lets us compare it with the source
    // part's instanceColor without attempting a GPU readback.
    mesh.userData.sharedSegmentColorData = colorData
    sourceGroup.add(mesh)
    return {
      mesh,
      numSegments,
      segXformTex, segXformData,
      segColorTex, segColorData: colorData,
      u_instanceOffset,
    }
  }

  // Build per-helix body-region cylinders + colours, then call the generic
  // segment-LOD builder.  One cylinder per *contiguous dsDNA region*
  // (computed from domainCylData.t0/t1, merging overlapping/adjacent
  // body domains).  Helices that are entirely overhang (no body domains)
  // get zero cylinders here — their content shows via the overhang LOD
  // only.  Helices with a mid-axis overhang produce two body cylinders,
  // one each side of the gap.
  function _buildMidLodMesh(srcEntry, design, legacyHelixCylMesh, sourceGroup) {
    const helixIds = []
    for (const h of design?.helices ?? []) {
      if (typeof h.id === 'string' && h.id.startsWith('__lnk__')) continue
      helixIds.push(h.id)
    }
    if (helixIds.length === 0) return null

    // Group body domains (from helixCtrl's `domainCylData`) by helixId, kept
    // separate for staples vs scaffold.  The scaffold spans the whole helix
    // under the tiling staples; if we lumped it into one interval and averaged
    // (the old behaviour), a helix whose staples change colour along its length
    // (e.g. red end-caps + orange middle) collapsed to a single muddy average.
    // Instead we split at STAPLE colour boundaries so every strand colour shows
    // as its own cylinder; the scaffold core is excluded from the colour split
    // (it's not what gives a region its colour) and only used as a fallback for
    // scaffold-only helices so nothing vanishes.
    const scaffoldIds = new Set()
    for (const s of design?.strands ?? []) {
      if (s.strand_type === 'scaffold') scaffoldIds.add(s.id)
    }
    const stapleByHelix = new Map()
    const scaffByHelix  = new Map()
    const domainCylData = srcEntry.helixCtrl?.domainCylData ?? []
    for (const dom of domainCylData) {
      if (dom.t0 == null || dom.t1 == null) continue
      const m = scaffoldIds.has(dom.strandId) ? scaffByHelix : stapleByHelix
      let bucket = m.get(dom.helixId)
      if (!bucket) { bucket = []; m.set(dom.helixId, bucket) }
      bucket.push(dom)
    }

    // Build-time per-domain colour (from the legacy strand-coloured cylinders),
    // quantised to 8-bit so float jitter never splits a same-colour run.
    const cylColorArr = legacyHelixCylMesh?.instanceColor?.array ?? null
    const _domColorKey = (d) => {
      if (!cylColorArr) return 0
      const ci = d.cylIdx * 3
      return (Math.round(cylColorArr[ci] * 255) << 16)
           | (Math.round(cylColorArr[ci + 1] * 255) << 8)
           |  Math.round(cylColorArr[ci + 2] * 255)
    }

    // Per helix, sort by t0 and merge axially-adjacent domains into intervals,
    // breaking a run whenever the colour changes.  Each surviving interval is
    // one body cylinder of a single (strand) colour.  `intervals` is the flat
    // list we'll turn into matrices.
    const intervals = []  // { helixIdx, helixId, t0, t1, domains: [...] }
    for (let i = 0; i < helixIds.length; i++) {
      const helixId = helixIds[i]
      let doms = stapleByHelix.get(helixId)
      if (!doms || doms.length === 0) doms = scaffByHelix.get(helixId)
      if (!doms || doms.length === 0) continue
      doms = doms.slice().sort((a, b) => a.t0 - b.t0)
      let curKey = _domColorKey(doms[0])
      let cur = { helixIdx: i, helixId, t0: doms[0].t0, t1: doms[0].t1, domains: [doms[0]] }
      for (let j = 1; j < doms.length; j++) {
        const d = doms[j]
        const k = _domColorKey(d)
        if (k === curKey && d.t0 <= cur.t1 + 1e-9) {
          if (d.t1 > cur.t1) cur.t1 = d.t1
          cur.domains.push(d)
        } else {
          intervals.push(cur)
          cur = { helixIdx: i, helixId, t0: d.t0, t1: d.t1, domains: [d] }
          curKey = k
        }
      }
      intervals.push(cur)
    }

    const numSegments = intervals.length
    if (numSegments === 0) return null

    // Build per-interval matrix array.  Each interval's body cylinder spans
    // the EXTENT OF ITS LEGACY SEGMENTS, derived from
    // legacyHelixCylMesh.instanceMatrix — NOT the API `helix_axes`.  The API
    // helix_axes can be offset/shorter than the actual rendered bp segments
    // (the "offset from origin" mismatch on Ultimate Polymer Hinge), which
    // left the body cylinders ~30 nm short of the real helix and the
    // selection box full of empty space.  Reading the legacy segment
    // endpoints guarantees the body cylinder coincides with where the
    // legacy renderer drew the helix.
    //
    // Each legacy cylinder geometry is unit height along Y; endpoints are
    // matrix × (0, ±0.5, 0).  For an interval's (collinear) segments we
    // take the two farthest-apart endpoints as the body cylinder's ends.
    const matrixArray = new Float32Array(numSegments * 16)
    const tmpM = new THREE.Matrix4()
    const tmpQ = new THREE.Quaternion()
    const tmpV = new THREE.Vector3()
    const tmpS = new THREE.Vector3()
    const yAxis = new THREE.Vector3(0, 1, 0)
    const dirV  = new THREE.Vector3()
    const segMat = new THREE.Matrix4()
    const pA = new THREE.Vector3()
    const pB = new THREE.Vector3()
    const legacyArr = legacyHelixCylMesh?.instanceMatrix?.array
    for (let i = 0; i < numSegments; i++) {
      const iv = intervals[i]
      // Gather all endpoints of this interval's legacy segments.
      const pts = []
      if (legacyArr) {
        for (const d of iv.domains) {
          const off = d.cylIdx * 16
          if (off + 16 > legacyArr.length) continue
          const e = segMat.elements
          for (let k = 0; k < 16; k++) e[k] = legacyArr[off + k]
          pts.push(new THREE.Vector3(0, -0.5, 0).applyMatrix4(segMat))
          pts.push(new THREE.Vector3(0,  0.5, 0).applyMatrix4(segMat))
        }
      }
      if (pts.length < 2) continue
      // Farthest-apart endpoint pair = the cylinder's two ends.
      let best = -1
      for (let a = 0; a < pts.length; a++) {
        for (let b = a + 1; b < pts.length; b++) {
          const d2 = pts[a].distanceToSquared(pts[b])
          if (d2 > best) { best = d2; pA.copy(pts[a]); pB.copy(pts[b]) }
        }
      }
      const dx = pB.x - pA.x, dy = pB.y - pA.y, dz = pB.z - pA.z
      const len = Math.sqrt(dx * dx + dy * dy + dz * dz)
      if (len < 1e-6) continue
      tmpV.set((pA.x + pB.x) * 0.5, (pA.y + pB.y) * 0.5, (pA.z + pB.z) * 0.5)
      dirV.set(dx / len, dy / len, dz / len)
      tmpQ.setFromUnitVectors(yAxis, dirV)
      tmpS.set(1.0, len, 1.0)
      tmpM.compose(tmpV, tmpQ, tmpS)
      const e = tmpM.elements
      for (let k = 0; k < 16; k++) matrixArray[i * 16 + k] = e[k]
    }

    // Per-interval colour = average of the strand-domain colours that
    // belong to this interval (taken from legacyHelixCylMesh.instanceColor
    // via each domain's cylIdx).
    const colorArrayRGB = new Float32Array(numSegments * 3)
    for (let i = 0; i < numSegments; i++) {
      colorArrayRGB[i * 3 + 0] = 1
      colorArrayRGB[i * 3 + 1] = 1
      colorArrayRGB[i * 3 + 2] = 1
    }
    if (legacyHelixCylMesh?.instanceColor) {
      const cylColors = legacyHelixCylMesh.instanceColor.array
      for (let i = 0; i < numSegments; i++) {
        const iv = intervals[i]
        let sumR = 0, sumG = 0, sumB = 0, count = 0
        for (const d of iv.domains) {
          const ci = d.cylIdx * 3
          sumR += cylColors[ci + 0]
          sumG += cylColors[ci + 1]
          sumB += cylColors[ci + 2]
          count++
        }
        if (count > 0) {
          colorArrayRGB[i * 3 + 0] = sumR / count
          colorArrayRGB[i * 3 + 1] = sumG / count
          colorArrayRGB[i * 3 + 2] = sumB / count
        }
      }
    }

    const lod = _buildSegmentLodMesh({
      srcEntry,
      matrixArray,
      colorArrayRGB,
      numSegments,
      geometry: _LOD_CYL_GEO,
      meshName: 'sharedLodMid',
      sourceGroup,
    })
    if (lod) {
      // Stash interval list so `_applyColorsToSource` can re-average
      // segment colours per interval on every coloringMode change.
      lod.intervals = intervals
    }
    return lod
  }

  // ── Overhang-LOD InstancedMesh + shader ──────────────────────────────────
  // Mirrors the sharedLodMid pattern but draws ONE half-cylinder per overhang
  // segment (where the legacy iOverhangCylinders mesh draws individual
  // overhang domains).  This restores the visual cue that overhangs poke
  // out from the helix axis — important for identifying mate points at
  // the cylinders LOD.  Each source-instance replicates the same per-segment
  // set, so total mesh count = numOverhangs × numInstances.  Drawn alongside
  // sharedLodMid in the mid bucket.
  //
  // legacyOverhangMesh: the iOverhangCylinders InstancedMesh from buildHelixObjects.
  // Carries per-segment matrices (instanceMatrix) + colors (instanceColor) in
  // source-local space.  We copy them into our own DataTextures so the shared
  // shader can sample per-segment without needing the source iHelixCtrl alive.
  function _buildOverhangLodMesh(srcEntry, legacyOverhangMesh, sourceGroup) {
    const numSegments = legacyOverhangMesh?.count ?? 0
    if (numSegments === 0) return null
    return _buildSegmentLodMesh({
      srcEntry,
      matrixArray:   legacyOverhangMesh.instanceMatrix.array,
      colorArrayRGB: legacyOverhangMesh.instanceColor?.array,
      numSegments,
      geometry: _LOD_HALF_CYL_GEO,
      meshName: 'sharedLodOverhangs',
      sourceGroup,
      side: THREE.DoubleSide,
    })
  }

  // ── Far-LOD InstancedMesh + shader ───────────────────────────────────────
  // ── Hull-LOD InstancedMesh + shader ───────────────────────────────────────
  // One copy of the source-local hull solid (`hullGeo`, merged extrusion boxes
  // in source-local space) per hull-prism instance. Single-index instancing
  // (gl_InstanceID + u_instanceOffset) — the vertex shader composes the full
  // per-instance world matrix:
  //   world = instTransform × position.
  // The instance row is gl_InstanceID + u_instanceOffset (the hull bucket sorts
  // after close/mid, so the offset is nClose+nMid — set per frame in
  // _updateLodForSource).  Lit flat grey, double-sided.  NOTE: like the mid/
  // overhang cylinder LODs, the shader does NOT rotate normals by instTransform,
  // so lighting on rotated instances is approximate (acceptable for opaque grey
  // boxes; matches shipped LOD precedent).
  function _injectOuterInstanceNormal(vertexShader) {
    return vertexShader.replace('#include <beginnormal_vertex>', `
      #include <beginnormal_vertex>
      int normalInstanceIdx = gl_InstanceID + int(u_instanceOffset);
      mat4 normalInstTransform = mat4(
        texelFetch(u_instanceXform, ivec2(0, normalInstanceIdx), 0),
        texelFetch(u_instanceXform, ivec2(1, normalInstanceIdx), 0),
        texelFetch(u_instanceXform, ivec2(2, normalInstanceIdx), 0),
        texelFetch(u_instanceXform, ivec2(3, normalInstanceIdx), 0)
      );
      objectNormal = transpose(inverse(mat3(normalInstTransform))) * objectNormal;
      #ifdef USE_TANGENT
        objectTangent = mat3(normalInstTransform) * objectTangent;
      #endif
    `)
  }

  function _buildHullLodMesh(srcEntry, hullGeo, sourceGroup) {
    const numInstances = srcEntry.instanceIds.length
    if (numInstances === 0 || !hullGeo) return null

    const mat = new THREE.MeshLambertMaterial({ color: 0x9a9a9a, side: THREE.DoubleSide })
    // Per-material cache key so each source's program is independent (avoids
    // the static-cache-key trap documented for _buildSegmentLodMesh).
    const _hullCacheKey = 'sharedLodHull_' + mat.uuid
    mat.customProgramCacheKey = () => _hullCacheKey
    const u_instanceOffset = { value: 0 }
    mat.onBeforeCompile = (shader) => {
      shader.uniforms.u_instanceXform  = srcEntry.uXformUniform
      shader.uniforms.u_visibilityTex  = srcEntry.uVisUniform
      shader.uniforms.u_instanceOffset = u_instanceOffset
      shader.vertexShader = shader.vertexShader
        .replace(
          '#include <common>',
          `
          #include <common>
          uniform sampler2D u_instanceXform;
          uniform sampler2D u_visibilityTex;
          uniform float u_instanceOffset;
          varying float v_visible;
          `,
        )
        .replace(
          '#include <begin_vertex>',
          `
          int instanceIdx = gl_InstanceID + int(u_instanceOffset);
          v_visible = texelFetch(u_visibilityTex, ivec2(0, instanceIdx), 0).r;
          mat4 instTransform = mat4(
            texelFetch(u_instanceXform, ivec2(0, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(1, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(2, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(3, instanceIdx), 0)
          );
          vec3 transformed = (instTransform * vec4(position, 1.0)).xyz;
          `,
        )
      shader.vertexShader = _injectOuterInstanceNormal(shader.vertexShader)
      shader.fragmentShader = shader.fragmentShader
        .replace(
          '#include <common>',
          `
          #include <common>
          varying float v_visible;
          `,
        )
        .replace(
          '#include <dithering_fragment>',
          `
          if (v_visible < 0.5) discard;
          #include <dithering_fragment>
          `,
        )
    }

    const mesh = new THREE.InstancedMesh(hullGeo, mat, Math.max(1, numInstances))
    // Collapse instanceMatrix to a single identity row — real per-instance
    // transforms ride the u_instanceXform texture, read in the shader.
    const identityArr = new Float32Array(16)
    identityArr[0] = 1; identityArr[5] = 1; identityArr[10] = 1; identityArr[15] = 1
    const idAttr = new THREE.InstancedBufferAttribute(identityArr, 16, false, Math.max(1, numInstances))
    idAttr.setUsage(THREE.StaticDrawUsage)
    mesh.instanceMatrix = idAttr
    mesh.instanceMatrix.needsUpdate = true
    mesh.instanceColor = null
    mesh.count = 0
    // MUST be false: positions live in the texture, not the mesh transform, so
    // Three's geometry-bounding-sphere cull (at the group origin) would wrongly
    // cull the whole batch. Same reason as the mid/far LODs.
    mesh.frustumCulled = false
    // Keep visible=true so onBeforeRender hooks fire even at count=0 (the
    // stuck-LOD trap); drawElementsInstanced with count=0 is a no-op.
    mesh.visible = true
    mesh.name = 'sharedLodHull'
    // Photo mode must skip this custom-shader mesh (else _swapMaterials drops
    // the instancing shader and collapses every hull copy to the source origin).
    mesh.userData.sharedLodImpostor = true
    sourceGroup.add(mesh)
    return { mesh, u_instanceOffset }
  }

  // ── Curved-cylinder LOD (deformed sources) ─────────────────────────────────
  // The per-domain sharedLodMid is built from the STRAIGHT iHelixCylinders, which
  // is empty for curved (bent-deformation) helices — so bent parts rendered no
  // cylinders in the shared path.  Instead we bake the source's bent TUBE meshes
  // (the same curved cylinders + end caps helix_renderer draws in the design view)
  // into ONE source-local geometry with per-vertex strand colours, then instance
  // it per copy exactly like the hull solid.  Returns position+normal+color, or
  // null for a straight part (no curved tubes) — so the straight path is untouched.
  function _curvedCylGeoForSource(helixCtrl) {
    const root = helixCtrl?.root
    if (!root) return null
    root.updateMatrixWorld(true)
    const baked = []
    const col = new THREE.Color()
    root.traverse(o => {
      const pn = o.parent?.name
      if (!o.isMesh || !o.geometry) return
      if (pn !== 'curvedCylGroup' && pn !== 'curvedOvhgGroup') return
      let g = o.geometry.clone()
      g.applyMatrix4(o.matrixWorld)
      g = g.toNonIndexed()
      for (const name of Object.keys(g.attributes)) {
        if (name !== 'position' && name !== 'normal') g.deleteAttribute(name)
      }
      if (!g.attributes.normal) g.computeVertexNormals()
      const m = Array.isArray(o.material) ? o.material[0] : o.material
      if (m?.color) col.copy(m.color); else col.setRGB(0.6, 0.6, 0.6)
      const n = g.attributes.position.count
      const colors = new Float32Array(n * 3)
      for (let i = 0; i < n; i++) { colors[i * 3] = col.r; colors[i * 3 + 1] = col.g; colors[i * 3 + 2] = col.b }
      g.setAttribute('color', new THREE.Float32BufferAttribute(colors, 3))
      baked.push(g)
    })
    if (!baked.length) return null
    const merged = mergeGeometries(baked, false)
    baked.forEach(g => g.dispose())
    return merged
  }

  // One baked bent-tube solid per instance, instanced via the per-instance xform
  // texture exactly like _buildHullLodMesh — but lit + vertex-coloured so strand
  // colours survive.  Rides the MID (cylinder) bucket.  (Normals aren't rotated by
  // instTransform — approximate lighting on rotated instances, matching the hull/
  // mid LOD precedent.)
  function _buildCurvedCylLodMesh(srcEntry, geo, sourceGroup) {
    const numInstances = srcEntry.instanceIds.length
    if (numInstances === 0 || !geo) return null
    const mat = new THREE.MeshLambertMaterial({ vertexColors: true, side: THREE.DoubleSide })
    const _ck = 'sharedLodCurvedCyl_' + mat.uuid
    mat.customProgramCacheKey = () => _ck
    const u_instanceOffset = { value: 0 }
    mat.onBeforeCompile = (shader) => {
      shader.uniforms.u_instanceXform  = srcEntry.uXformUniform
      shader.uniforms.u_visibilityTex  = srcEntry.uVisUniform
      shader.uniforms.u_instanceOffset = u_instanceOffset
      shader.vertexShader = shader.vertexShader
        .replace('#include <common>', `
          #include <common>
          uniform sampler2D u_instanceXform;
          uniform sampler2D u_visibilityTex;
          uniform float u_instanceOffset;
          varying float v_visible;
          `)
        .replace('#include <begin_vertex>', `
          int instanceIdx = gl_InstanceID + int(u_instanceOffset);
          v_visible = texelFetch(u_visibilityTex, ivec2(0, instanceIdx), 0).r;
          mat4 instTransform = mat4(
            texelFetch(u_instanceXform, ivec2(0, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(1, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(2, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(3, instanceIdx), 0)
          );
          vec3 transformed = (instTransform * vec4(position, 1.0)).xyz;
          `)
      shader.vertexShader = _injectOuterInstanceNormal(shader.vertexShader)
      shader.fragmentShader = shader.fragmentShader
        .replace('#include <common>', `
          #include <common>
          varying float v_visible;
          `)
        .replace('#include <dithering_fragment>', `
          if (v_visible < 0.5) discard;
          #include <dithering_fragment>
          `)
    }
    const mesh = new THREE.InstancedMesh(geo, mat, Math.max(1, numInstances))
    const identityArr = new Float32Array(16)
    identityArr[0] = 1; identityArr[5] = 1; identityArr[10] = 1; identityArr[15] = 1
    const idAttr = new THREE.InstancedBufferAttribute(identityArr, 16, false, Math.max(1, numInstances))
    idAttr.setUsage(THREE.StaticDrawUsage)
    mesh.instanceMatrix = idAttr
    mesh.instanceMatrix.needsUpdate = true
    mesh.instanceColor = null
    mesh.count = 0
    mesh.frustumCulled = false
    mesh.visible = true
    mesh.name = 'sharedLodCurvedCyl'
    mesh.userData.sharedLodImpostor = true
    sourceGroup.add(mesh)
    return { mesh, u_instanceOffset }
  }

  // ── Overhang-marker-LOD InstancedMesh ──────────────────────────────────────
  // The source-local overhang face quads (vertex-coloured), instanced exactly
  // like _buildHullLodMesh's hull solid (world = instTransform × position via the
  // per-instance xform texture). Rides the SAME hull LOD bucket: _updateLodForSource
  // sets its count + offset to match srcEntry.hullLod. Unlit MeshBasic +
  // vertexColors so each overhang keeps its strand colour; polygonOffset keeps
  // it proud of the hull face (EPS offset already baked in by buildOverhangMarkers).
  function _buildMarkerLodMesh(srcEntry, markerGeo, sourceGroup) {
    const numInstances = srcEntry.instanceIds.length
    if (numInstances === 0 || !markerGeo) return null

    const mat = new THREE.MeshBasicMaterial({
      vertexColors: true, side: THREE.DoubleSide,
      polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -2,
    })
    const _markerCacheKey = 'sharedLodHullMarker_' + mat.uuid
    mat.customProgramCacheKey = () => _markerCacheKey
    const u_instanceOffset = { value: 0 }
    mat.onBeforeCompile = (shader) => {
      shader.uniforms.u_instanceXform  = srcEntry.uXformUniform
      shader.uniforms.u_visibilityTex  = srcEntry.uVisUniform
      shader.uniforms.u_instanceOffset = u_instanceOffset
      shader.vertexShader = shader.vertexShader
        .replace(
          '#include <common>',
          `
          #include <common>
          uniform sampler2D u_instanceXform;
          uniform sampler2D u_visibilityTex;
          uniform float u_instanceOffset;
          varying float v_visible;
          `,
        )
        .replace(
          '#include <begin_vertex>',
          `
          int instanceIdx = gl_InstanceID + int(u_instanceOffset);
          v_visible = texelFetch(u_visibilityTex, ivec2(0, instanceIdx), 0).r;
          mat4 instTransform = mat4(
            texelFetch(u_instanceXform, ivec2(0, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(1, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(2, instanceIdx), 0),
            texelFetch(u_instanceXform, ivec2(3, instanceIdx), 0)
          );
          vec3 transformed = (instTransform * vec4(position, 1.0)).xyz;
          `,
        )
      shader.fragmentShader = shader.fragmentShader
        .replace(
          '#include <common>',
          `
          #include <common>
          varying float v_visible;
          `,
        )
        .replace(
          '#include <dithering_fragment>',
          `
          if (v_visible < 0.5) discard;
          #include <dithering_fragment>
          `,
        )
    }

    const mesh = new THREE.InstancedMesh(markerGeo, mat, Math.max(1, numInstances))
    const identityArr = new Float32Array(16)
    identityArr[0] = 1; identityArr[5] = 1; identityArr[10] = 1; identityArr[15] = 1
    const idAttr = new THREE.InstancedBufferAttribute(identityArr, 16, false, Math.max(1, numInstances))
    idAttr.setUsage(THREE.StaticDrawUsage)
    mesh.instanceMatrix = idAttr
    mesh.instanceMatrix.needsUpdate = true
    mesh.instanceColor = null
    mesh.count = 0
    mesh.frustumCulled = false
    mesh.visible = true
    mesh.name = 'sharedLodHullMarkers'
    mesh.renderOrder = 105
    mesh.userData.sharedLodImpostor = true
    sourceGroup.add(mesh)
    return { mesh, u_instanceOffset }
  }

  // ── Per-frame LOD assignment + sort-to-front (Phase 3f stage 2) ──────────
  // Each frame, for every source:
  //   1. Compute squared distance from camera to each instance's translation
  //      (read from column-3 texels of `xformData`).
  //   2. Sort row indices by ascending distance² → permutation `perm` where
  //      `perm[newRow] = oldRow`.
  //   3. If the permutation differs from identity (i.e. the current order),
  //      permute `xformData`, `visData`, `visibility`, `instanceIds`, and
  //      `instanceIndex` so row 0 holds the nearest visible instance, row 1
  //      the next-nearest, etc. Visible instances precede hidden ones;
  //      hidden instances retain a stable relative order at the tail.
  //   4. Mark both textures `needsUpdate = true` (simple full re-upload; the
  //      data lives in CPU-side typed arrays, so this is one PBO copy).
  //   5. Refresh `u_activeInstanceIdx` from `_activeInstanceId` against the
  //      new `instanceIndex` so selection brightening tracks the moved row.
  //   6. Bucket count: walk the now-sorted rows, count close/mid/far. Because
  //      rows are sorted nearest-first and the bucket thresholds are pure
  //      distance comparisons, the close bucket occupies rows 0..N_close-1.
  //   7. Set each LOD mesh's `count` (multiplied by per-LOD multiplier) and
  //      `visible = (count > 0)`.
  //
  // Scratch typed arrays are reused across frames (one allocation per source
  // at first use) to avoid GC pressure.
  // Reused scratch for bbox diagonal lookup so we don't allocate per frame.
  const _tmpBboxSize = new THREE.Vector3()

  function _updateLodForSource(srcEntry, camera, renderer) {
    if (!srcEntry || !camera) return
    // Atomistic sources render their atom-impostor batch at full detail and do
    // NOT participate in the close/mid/hull bucketing or instance-texture
    // permutation (the atom batch indexes the unpermuted instance texture).
    if (srcEntry.isAtomistic || srcEntry.isSurface) return
    const N = srcEntry.instanceIds.length
    if (N === 0) return

    // Angular-size LOD: compute on-screen pixel size of the source's bbox
    // diagonal at the camera's distance, then bucket by pixel thresholds.
    // pixelSize = bboxDiag × focalPx / distance, where
    // focalPx = viewport_height_px / (2 × tan(fov/2)).  Falls back to
    // distance-only bucketing for orthographic / no-renderer cases.
    let pxFactor = 0
    if (camera.isPerspectiveCamera && renderer?.domElement) {
      const bboxDiag = (() => {
        const box = srcEntry.instBoundingBox
        if (!box || box.isEmpty()) return 0
        box.getSize(_tmpBboxSize)
        return _tmpBboxSize.length()
      })()
      if (bboxDiag > 0) {
        const fovRad = camera.fov * Math.PI / 180
        const viewportH = renderer.domElement.height || window.innerHeight
        const focalPx = viewportH / (2 * Math.tan(fovRad / 2))
        pxFactor = bboxDiag * focalPx
      }
    }
    const farPxSq   = _lodFarPx   * _lodFarPx

    const cx = camera.position.x, cy = camera.position.y, cz = camera.position.z
    const data = srcEntry.xformData
    const vis  = srcEntry.visibility

    // ── 1. Build (row, distance²) array; hidden rows get +Infinity so they
    //      sort to the tail and never enter the close/mid bucket count.
    // Reuse scratch arrays across frames.
    let scratch = srcEntry._lodScratch
    if (!scratch || scratch.dist2.length !== N) {
      scratch = srcEntry._lodScratch = {
        dist2: new Float64Array(N),
        perm:  new Int32Array(N),       // perm[newRow] = oldRow
        bucket: new Int8Array(N),       // per-instance LOD bucket (0/1/2/3-hull) or 4=hidden
        tmpXform: new Float32Array(N * 16),
        tmpVis:   new Float32Array(N * 16),
        tmpVisibility: new Float32Array(N),
        tmpLodCap: new Int8Array(N),
        tmpIds: new Array(N),
      }
    }
    const dist2 = scratch.dist2
    const perm  = scratch.perm
    const bucket = scratch.bucket
    const lodCap = srcEntry.instanceLodCap
    for (let i = 0; i < N; i++) {
      perm[i] = i
      if (vis[i] < 0.5) {
        dist2[i] = Number.POSITIVE_INFINITY
        bucket[i] = 4  // hidden — sinks to tail
        continue
      }
      // Translation column = column 3. xformData layout (per instance, 16
      // floats): c0(4) | c1(4) | c2(4) | c3(4). col3.xyz at offset i*16+12.
      const off = i * 16 + 12
      const dx = data[off + 0] - cx
      const dy = data[off + 1] - cy
      const dz = data[off + 2] - cz
      const d2 = dx * dx + dy * dy + dz * dz
      dist2[i] = d2
      // Compute effective bucket from (cap, angular size).  Sorting by
      // (bucket, dist²) keeps per-LOD row ranges contiguous, which the
      // mid/far shaders rely on via u_instanceOffset.
      const cap = lodCap ? lodCap[i] : 0
      // pxSq = (pxFactor / distance)² = pxFactor² / d2.  Compare pxSq to
      // threshold² to avoid the sqrt in the hot loop.
      const pxSq = (pxFactor > 0) ? (pxFactor * pxFactor) / Math.max(d2, 1) : 1e12
      // Simplified ladder (no billboard tier): each rep shows its detail bucket
      // when big enough on screen, else collapses to the HULL — real 3-D geometry
      // that reads correctly under a moving camera (a flat camera-facing billboard
      // couldn't).  cap 0 (full/beads): bp close near, hull far.  cap 1
      // (cylinders): mid near, hull far.  cap 3 (hull-prism rep) AND unsupported
      // reps (vdw/ballstick/surface): always hull.  Every source has a hull
      // (real or bbox fallback), so nothing vanishes far away.
      // Photo export sets `_suppressLodDemotion` → every part renders at its rep's
      // detail bucket regardless of distance (uniform high-detail figures).
      if (_suppressLodDemotion)         bucket[i] = (cap === 0) ? 0 : (cap === 1) ? 1 : 3
      else if (cap === 3)               bucket[i] = 3
      else if (cap === 0)               bucket[i] = (pxSq >= farPxSq) ? 0 : 3
      else if (cap === 1)               bucket[i] = (pxSq >= farPxSq) ? 1 : 3
      else                              bucket[i] = 3
    }

    // ── 2. Sort perm by (bucket, dist²) ascending.  Bucket comes first so
    //      every LOD's rows are a contiguous range — mid/far shaders read
    //      via a single u_instanceOffset.
    const permArr = Array.from(perm)
    permArr.sort((a, b) => {
      const ba = bucket[a], bb = bucket[b]
      if (ba !== bb) return ba - bb
      return dist2[a] - dist2[b]
    })

    // ── 3. Detect "already sorted" — if perm equals identity (every entry
    //      is at its own index), short-circuit the permute step. Most steady-
    //      state frames after the first sort will be near-identity, so we
    //      avoid the texture re-upload in that common case.
    let isIdentity = true
    for (let i = 0; i < N; i++) {
      if (permArr[i] !== i) { isIdentity = false; break }
    }

    if (!isIdentity) {
      // Permute xformData, visData, visibility, instanceIds, instanceIndex.
      // We read from the ORIGINAL arrays via perm[newRow] = oldRow, write to
      // scratch buffers, then swap-copy back.
      const tmpX = scratch.tmpXform
      const tmpV = scratch.tmpVis
      const tmpVisFlag = scratch.tmpVisibility
      const tmpLodCap = scratch.tmpLodCap
      const tmpIds = scratch.tmpIds
      const visData = srcEntry.visData
      const ids = srcEntry.instanceIds
      const lodCap = srcEntry.instanceLodCap
      for (let newRow = 0; newRow < N; newRow++) {
        const oldRow = permArr[newRow]
        const srcOff = oldRow * 16
        const dstOff = newRow * 16
        // Copy 16-float xform row.
        for (let k = 0; k < 16; k++) tmpX[dstOff + k] = data[srcOff + k]
        // Copy 16-float vis row (only channel 0 carries the flag, but copy
        // the whole row to preserve any future-use channels).
        for (let k = 0; k < 16; k++) tmpV[dstOff + k] = visData[srcOff + k]
        tmpVisFlag[newRow] = vis[oldRow]
        tmpLodCap[newRow]  = lodCap ? lodCap[oldRow] : 0
        tmpIds[newRow] = ids[oldRow]
      }
      // Write scratch → live arrays.
      data.set(tmpX)
      visData.set(tmpV)
      vis.set(tmpVisFlag)
      if (lodCap) lodCap.set(tmpLodCap)
      for (let i = 0; i < N; i++) ids[i] = tmpIds[i]
      // Rebuild instanceIndex (id → currentRow). instanceIndex is the live
      // map every external API must use to look up an id's current slot.
      srcEntry.instanceIndex.clear()
      for (let i = 0; i < N; i++) srcEntry.instanceIndex.set(ids[i], i)

      // Mark textures dirty for full re-upload next frame's draw. Clear any
      // pending partial-upload dirty-row sets: their indices refer to the
      // OLD row order and would now corrupt the texture if applied.
      srcEntry.xformTex.needsUpdate = true
      srcEntry.visTex.needsUpdate   = true
      srcEntry.dirtyRows.clear()
      srcEntry.dirtyVisRows.clear()
    }

    // ── 4. Refresh u_activeInstanceIdx for the active id (if any belongs to
    //      this source). This MUST run every frame, not just on permute-
    //      change, because `setActiveInstance` is permutation-safe by lookup.
    if (_activeInstanceId == null) {
      srcEntry.uActiveIdxUniform.value = -1
    } else {
      const row = srcEntry.instanceIndex.get(_activeInstanceId)
      srcEntry.uActiveIdxUniform.value = (row == null) ? -1 : row
    }

    // ── 5. Bucket count.  Bucket was computed pre-sort using the
    //      per-instance LOD cap (from ``representation``), so we just walk
    //      the now-sorted perm and tally.  Buckets are guaranteed
    //      contiguous: rows 0..nClose-1 are close, the next nMid are mid,
    //      the next nHull are hull, and hidden rows (bucket=4) fall after.
    //      (Bucket 2 / billboard tier is retired — nothing emits it.)
    let nClose = 0, nMid = 0, nHull = 0
    for (let i = 0; i < N; i++) {
      const b = bucket[permArr[i]]
      if (b === 4) break                // hidden tail — done
      if      (b === 0) nClose++
      else if (b === 1) nMid++
      else              nHull++
    }

    // ── 6. Apply counts. Multiplier per LOD:
    //        close: baseCount per close-LOD InstancedMesh
    //        mid:   numHelices
    //        hull:  1
    for (const am of srcEntry.activeMeshes) {
      const c = nClose * am.baseCount
      am.mesh.count = c
      // Phase 3f stage 2 follow-up: keep `visible = true` unconditionally so
      // the onBeforeRender hook chain keeps firing even when count=0. Three.js
      // short-circuits at `object.visible === false` BEFORE invoking
      // onBeforeRender (WebGLRenderer.js#L1327), which would freeze the LOD
      // state the first time nClose hits zero. drawElementsInstanced with
      // count=0 is a zero-cost no-op.
      am.mesh.visible = true
    }
    // Phase 3f stage 2 follow-up: with rows sorted by distance, mid-LOD
    // reads texture rows starting at nClose, hull starting at nClose+nMid.
    // Without these offsets, the shaders would read rows 0..nMid-1 / 0..nHull-1
    // — i.e. the SAME nearest instances close-LOD already drew (triple-render
    // bug from stage 1, surfaced by the stage-1 evaluator FAIL at 8f185bb).
    if (srcEntry.midLod) {
      const c = nMid * srcEntry.midLod.numSegments
      srcEntry.midLod.mesh.count = c
      srcEntry.midLod.mesh.visible = true  // see comment above re: stuck-LOD trap
      if (srcEntry.midLod.u_instanceOffset) {
        srcEntry.midLod.u_instanceOffset.value = nClose
      }
    }
    // Curved-cylinder LOD (deformed sources) rides the mid bucket — ONE baked
    // bent-tube solid per mid-bucket instance (hull-style: count = nMid, offset =
    // nClose). Coexists with sharedLodMid (which is empty for fully-curved parts).
    if (srcEntry.curvedCylLod) {
      srcEntry.curvedCylLod.mesh.count = nMid
      srcEntry.curvedCylLod.mesh.visible = true
      if (srcEntry.curvedCylLod.u_instanceOffset) {
        srcEntry.curvedCylLod.u_instanceOffset.value = nClose
      }
    }
    // Overhang LOD draws alongside mid LOD — same instance offset (after
    // close bucket).  Skipping when no overhangs exist avoids spurious draws.
    if (srcEntry.overhangLod) {
      const c = nMid * srcEntry.overhangLod.numSegments
      srcEntry.overhangLod.mesh.count = c
      srcEntry.overhangLod.mesh.visible = true
      if (srcEntry.overhangLod.u_instanceOffset) {
        srcEntry.overhangLod.u_instanceOffset.value = nClose
      }
    }
    // Hull LOD draws every demoted-far / hull-prism instance (one merged box
    // solid each), sorted after close+mid → offset = nClose + nMid.
    if (srcEntry.hullLod) {
      srcEntry.hullLod.mesh.count = nHull
      srcEntry.hullLod.mesh.visible = true  // see comment above re: stuck-LOD trap
      if (srcEntry.hullLod.u_instanceOffset) {
        srcEntry.hullLod.u_instanceOffset.value = nClose + nMid
      }
    }
    // Overhang markers ride the hull bucket — same count + offset as the hull.
    if (srcEntry.hullMarkerLod) {
      srcEntry.hullMarkerLod.mesh.count = nHull
      srcEntry.hullMarkerLod.mesh.visible = true
      if (srcEntry.hullMarkerLod.u_instanceOffset) {
        srcEntry.hullMarkerLod.u_instanceOffset.value = nClose + nMid
      }
    }
    srcEntry._lastLodCounts = { close: nClose, mid: nMid, hull: nHull }
    // Debug: stash per-frame state so `probeLod()` + the HUD can read it
    // without re-doing the heavy bucket pass.  Compute min/max pixel size
    // over visible instances in a single cheap loop.
    let minPx = Infinity, maxPx = -Infinity
    if (pxFactor > 0) {
      for (let i = 0; i < N; i++) {
        if (vis[i] < 0.5) continue
        const d2 = dist2[i]
        if (!isFinite(d2) || d2 <= 0) continue
        const px = pxFactor / Math.sqrt(d2)
        if (px < minPx) minPx = px
        if (px > maxPx) maxPx = px
      }
    }
    srcEntry._lastLodDebug = {
      pxFactor,
      bboxDiag: pxFactor > 0 ? pxFactor / (renderer?.domElement?.height
        ? renderer.domElement.height / (2 * Math.tan((camera.fov * Math.PI / 180) / 2))
        : 1) : 0,
      closePx: _lodClosePx,
      farPx: _lodFarPx,
      minPxSize: isFinite(minPx) ? minPx : null,
      maxPxSize: isFinite(maxPx) ? maxPx : null,
    }
  }

  // Install a SECOND onBeforeRender hook for LOD updates. It piggybacks on
  // the first active mesh, which already carries the dirty-row uploader; we
  // chain them. Three.js calls onBeforeRender(renderer, scene, camera, ...).
  function _installLodUpdater(srcEntry) {
    // Find ANY mesh that's reliably scene-resident every frame so the
    // onBeforeRender hook actually fires.  Cylinders-rep builds leave
    // activeMeshes empty (only bp meshes go in there, and bp meshes have
    // baseCount==0 at that rep), so we fall back to sharedLodMid / hull.
    // Without this fallback _updateLodForSource never runs → sharedLodMid.count
    // stays 0 → only helix axes draw (regression from 26f9df1).
    const hookHost =
      srcEntry.activeMeshes[0]?.mesh
      ?? srcEntry.midLod?.mesh
      ?? srcEntry.hullLod?.mesh
    if (!hookHost) return
    const prevHook = hookHost.onBeforeRender
    hookHost.onBeforeRender = function (renderer, scn, camera, geom, mat, group) {
      if (typeof prevHook === 'function') {
        prevHook.call(this, renderer, scn, camera, geom, mat, group)
      }
      _updateLodForSource(srcEntry, camera, renderer)
    }
  }

  // ── Public: dispose ───────────────────────────────────────────────────────
  function dispose() {
    for (const srcEntry of _sources.values()) _disposeSource(srcEntry)
    _sources.clear()
    _instToSrc.clear()
    _prefetchedByPath.clear()
    _activeInstanceId = null
    // Tear down the selection outline.
    _disposeActiveBox()
    // Phase 7c: tear down the materialized articulation instance (if any) +
    // restore its batch slot. Called at the top of rebuild() too, so a
    // cluster-drag commit (→ backend → rebuild) cleanly bakes the new pose
    // into the source and drops the overlay.
    _dematerializeInstance()
    // Overhang label overlay + selection-highlight rings + cached textures.
    _disposeOverhangOverlays()
    // Phase 7a: the per-instance overhang render-data group (owns no geometry
    // of its own — overhang-locations disposes its arrow children).
    if (_renderDataGroup) {
      scene.remove(_renderDataGroup)
      _renderDataGroup = null
    }
    // Phase 7b: cross-part linker group.
    _linkerGroup.traverse(obj => {
      if (obj.geometry && !obj.geometry.userData?.shared) obj.geometry.dispose()
      if (obj.material) {
        const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
        mats.forEach(m => m.dispose())
      }
    })
    while (_linkerGroup.children.length) _linkerGroup.remove(_linkerGroup.children[0])
    scene.remove(_linkerGroup)
  }

  // ── Texture upload — dirty rows only ──────────────────────────────────────
  // Uses an onBeforeRender hook on each source's InstancedMesh to upload only
  // the dirty rows via gl.texSubImage2D (Three.js exposes the gl context via
  // the renderer arg). We attach the hook to one mesh per source (the first
  // active mesh); the others share the same texture so one upload suffices.
  function _installDirtyUploader(srcEntry) {
    if (!srcEntry.activeMeshes.length) return
    const firstMesh = srcEntry.activeMeshes[0].mesh
    firstMesh.onBeforeRender = function (renderer /*, scene, camera, geom, mat, group */) {
      const dirty    = srcEntry.dirtyRows
      const dirtyVis = srcEntry.dirtyVisRows
      if (dirty.size === 0 && dirtyVis.size === 0) return

      const gl = renderer.getContext()
      const props = renderer.properties
      function _uploadRows(texture, srcData, rowSet) {
        if (rowSet.size === 0) return
        const texProps = props.get(texture)
        if (!texProps.__webglTexture) {
          // Texture hasn't been uploaded yet — let Three.js do the initial
          // full upload via needsUpdate.
          texture.needsUpdate = true
          rowSet.clear()
          return
        }
        const prevBinding = gl.getParameter(gl.TEXTURE_BINDING_2D)
        gl.bindTexture(gl.TEXTURE_2D, texProps.__webglTexture)
        // Each row = 4 RGBA texels = 16 floats. We could batch contiguous
        // runs of dirty rows; for now, one texSubImage2D per dirty row.
        // 2000 dirty rows × the upload cost is still bounded; if it bites
        // we'll coalesce.
        for (const rowIdx of rowSet) {
          const offset = rowIdx * 16
          const view = srcData.subarray(offset, offset + 16)
          gl.texSubImage2D(
            gl.TEXTURE_2D, 0,
            /* x */ 0, /* y */ rowIdx,
            /* width */ 4, /* height */ 1,
            gl.RGBA, gl.FLOAT, view,
          )
        }
        gl.bindTexture(gl.TEXTURE_2D, prevBinding)
        rowSet.clear()
      }
      _uploadRows(srcEntry.xformTex, srcEntry.xformData, dirty)
      _uploadRows(srcEntry.visTex,   srcEntry.visData,   dirtyVis)
    }
  }

  // ── Public: rebuild ───────────────────────────────────────────────────────
  async function rebuild(assembly /*, opts */) {
    if (!assembly) { dispose(); return }

    const instances = assembly.instances ?? []
    if (!instances.length) {
      dispose()
      _fireRebuildComplete()
      return
    }

    // Group instances by source_key.
    const groups = new Map() // srcKey → PartInstance[]
    for (const inst of instances) {
      const key = _sharedSourceKey(inst)
      if (!groups.has(key)) groups.set(key, [])
      groups.get(key).push(inst)
    }

    // Fetch geometry for any source we haven't built yet (or one that the
    // user invalidated). For simplicity (and per spec for invalidateInstance),
    // we tear down all current sources and rebuild. Future optimization: only
    // rebuild sources whose membership / source_key set changed.
    // Fetch BEFORE disposing so the CURRENT geometry stays on screen during the
    // (slow, seconds-long) batch fetch. Disposing first blanked the whole scene
    // for the entire fetch — the user saw an empty viewport and assumed the app
    // had hung. Now the old chain stays visible until the new data is in hand.
    let batchGeo = null
    try {
      batchGeo = await api.getAssemblyGeometry()
    } catch (err) {
      console.warn('[shared_renderer] batch geometry fetch failed:', err)
      _fireRebuildComplete()
      return   // keep the old scene visible on error rather than blanking it
    }
    dispose()  // now wipe — we rebuild from scratch with the fetched data below.
    const perInst = batchGeo?.instances ?? {}

    for (const [srcKey, instList] of groups) {
      // Pick the first instance's geometry record — every instance of the
      // same source shares the same nucleotides/design references (client.js
      // dedup is already in place).
      const firstId = instList[0].id
      const rec = perInst[firstId]
      let srcData = rec
      if (!srcData || srcData.error) {
        // Per-instance fallback.
        try {
          const geo = await api.getInstanceGeometry(firstId)
          srcData = {
            nucleotides: geo?.nucleotides ?? [],
            helix_axes: _convertHelixAxesArray(geo?.helix_axes),
            design: geo?.design ?? null,
          }
        } catch (err) {
          console.warn(`[shared_renderer] geometry fetch failed for ${firstId}:`, err)
          continue
        }
      }
      // The client's `getAssemblyGeometry` projects helix_axes through as the
      // raw map (already dict-shape after _expandCompactNucleotides). When
      // we fall back to getInstanceGeometry the shape is array-of-axis so we
      // convert it.
      if (Array.isArray(srcData.helix_axes)) {
        srcData = { ...srcData, helix_axes: _convertHelixAxesArray(srcData.helix_axes) }
      }
      const entry = await _buildSource(srcKey, srcData, instList)
      if (!entry) continue
      _sources.set(srcKey, entry)
      _installDirtyUploader(entry)
      _installLodUpdater(entry)
    }

    rebuildOverhangNames()   // rebuild label sprites if the toggle is on
    _fireRebuildComplete()
  }

  function _convertHelixAxesArray(arr) {
    if (!arr) return null
    if (!Array.isArray(arr)) return arr   // already dict
    const map = {}
    for (const ax of arr) {
      map[ax.helix_id] = {
        start: ax.start,
        end: ax.end,
        samples: ax.samples ?? null,
        ovhgAxes: ax.ovhg_axes ?? null,
      }
    }
    return map
  }

  // ── Public: applyInlineGeometry ───────────────────────────────────────────
  // Stash the prefetched geometry and trigger a full rebuild. The simplest
  // correct behaviour at scale: the geometry pertains to a file source so
  // every instance referencing that path needs the new geometry — easiest
  // is a rebuild that re-fetches via api (which the seek endpoint already
  // has invalidated). For now this matches the old path's contract.
  async function applyInlineGeometry(filePath, design, nucleotides, helixAxes) {
    const assembly = store?.getState?.()?.currentAssembly
    if (!assembly || !filePath) return
    // Same trigger as the old path — rebuild will refetch.
    await rebuild(assembly)
  }

  // ── Public: invalidateInstance ────────────────────────────────────────────
  function invalidateInstance(instanceId) {
    _bendCentersLocalCache.delete(instanceId)
    // Per the spec: a full rebuild is acceptable for representation changes.
    const assembly = store?.getState?.()?.currentAssembly
    if (assembly) {
      // Don't await — fire-and-forget; matches old path semantics.
      rebuild(assembly).catch(err =>
        console.warn('[shared_renderer] invalidate-triggered rebuild failed:', err),
      )
    }
  }

  // ── Public: setActiveInstance ─────────────────────────────────────────────
  // Phase 3f stage 2: row indices are sort-to-front-permuted every frame, so
  // an id's row is not stable across frames. We stash the active id in
  // `_activeInstanceId` and rely on `_updateLodForSource` to refresh
  // `uActiveIdxUniform.value` from `instanceIndex.get(_activeInstanceId)`
  // each frame after the permutation. To keep the highlight visible BEFORE
  // the next frame's onBeforeRender (e.g. a still-image render after a
  // selection click), we also write the CURRENT row here.
  function setActiveInstance(id) {
    // Phase 7c: switching away from a materialized (articulating) instance
    // without committing rolls it back — drop the overlay + restore its batch
    // slot at the original pose.
    if (_matInst && _matInst.id !== id) _dematerializeInstance()
    // Clear previous highlight (every source) — the per-frame refresh will
    // re-light the matching source's uniform on the next draw.
    for (const srcEntry of _sources.values()) {
      srcEntry.uActiveIdxUniform.value = -1
    }
    _activeInstanceId = id ?? null
    _refreshActiveBox()
    if (!id) return
    const srcKey = _instToSrc.get(id)
    if (!srcKey) return
    const srcEntry = _sources.get(srcKey)
    if (!srcEntry) return
    // instanceIndex is the LIVE id-to-row map (permuted by sort-to-front).
    const idx = srcEntry.instanceIndex.get(id)
    if (idx == null) return
    srcEntry.uActiveIdxUniform.value = idx
  }

  // Selection outline — an ORIENTED white box hugging the active instance.
  // We draw the source's LOCAL bounding box edges and apply the instance's
  // world transform as the line object's matrix, so the outline rotates
  // with the part instead of using an inflated world-space AABB (a rotated
  // hinge's AABB can be ~50 % larger than its true footprint, which made
  // the selection look like it wrapped neighbouring instances in densely-
  // packed assemblies).  The edge geometry is rebuilt only when the active
  // source changes; per-frame / per-drag updates just re-copy the matrix.
  let _activeBoxHelper = null
  let _activeBoxSrcKey = null
  const _activeBoxMat = new THREE.Matrix4()
  let _photoMode = false   // Phase 7d: hide the selection outline in photo mode

  function _disposeActiveBox() {
    if (!_activeBoxHelper) return
    scene.remove(_activeBoxHelper)
    _activeBoxHelper.geometry?.dispose()
    _activeBoxHelper.material?.dispose()
    _activeBoxHelper = null
    _activeBoxSrcKey = null
  }

  function _refreshActiveBox() {
    const srcKey   = _activeInstanceId ? _instToSrc.get(_activeInstanceId) : null
    const srcEntry = srcKey ? _sources.get(srcKey) : null
    const row      = srcEntry ? srcEntry.instanceIndex.get(_activeInstanceId) : null
    const baseBox  = srcEntry?.instBoundingBox
    if (row == null || !baseBox || baseBox.isEmpty()) {
      if (_activeBoxHelper) _activeBoxHelper.visible = false
      return
    }
    // Rebuild local-box edges when the active instance belongs to a new
    // source (different part → different local bbox dimensions).
    if (!_activeBoxHelper || _activeBoxSrcKey !== srcKey) {
      _disposeActiveBox()
      const size = new THREE.Vector3();   baseBox.getSize(size)
      const center = new THREE.Vector3(); baseBox.getCenter(center)
      const boxGeo = new THREE.BoxGeometry(
        Math.max(size.x, 1e-3), Math.max(size.y, 1e-3), Math.max(size.z, 1e-3),
      )
      boxGeo.translate(center.x, center.y, center.z)
      const edges = new THREE.EdgesGeometry(boxGeo)
      boxGeo.dispose()
      _activeBoxHelper = new THREE.LineSegments(
        edges, new THREE.LineBasicMaterial({ color: 0xffffff }),
      )
      _activeBoxHelper.matrixAutoUpdate = false
      _activeBoxHelper.frustumCulled = false
      scene.add(_activeBoxHelper)
      _activeBoxSrcKey = srcKey
    }
    // Orient the box to the instance's world transform (the same matrix the
    // shader samples for this row).  matrixAutoUpdate=false so we set the
    // matrix directly; flag matrixWorld for recompute next render.
    const off = row * 16
    const e = _activeBoxMat.elements
    for (let k = 0; k < 16; k++) e[k] = srcEntry.xformData[off + k]
    _activeBoxHelper.matrix.copy(_activeBoxMat)
    _activeBoxHelper.matrixWorldNeedsUpdate = true
    _activeBoxHelper.visible = !_photoMode   // Phase 7d: never in publication renders
  }

  // ── Public: setPhotoMode (Phase 7d) ───────────────────────────────────────
  // The shared path has no per-instance annotation overlays to hide (axis
  // arrows are pre-hidden at build; helix-id labels / overhang-name sprites
  // are per-instance-only and don't exist here), so the only thing to suppress
  // is the selection outline. The actual PBR material swap is photo_renderer's
  // job — it re-applies our instancing vertex patch via the per-mesh
  // `userData.applySharedInstancing` hook stashed in `_patchSharedMeshes`, so
  // instances keep their world transforms under MeshPhysicalMaterial.
  function setPhotoMode(on) {
    _photoMode = !!on
    if (on) {
      if (_activeBoxHelper) _activeBoxHelper.visible = false
    } else {
      _refreshActiveBox()
    }
    rebuildOverhangNames()   // suppress labels in photo mode / restore on exit
  }

  // ── Overhang labels + hover/selection (shared path) ───────────────────────
  // Labels render for: the "show all" toggle (showOverhangNames), the hovered
  // overhang (transient), and selected overhangs (persistent, with a green
  // ring). Hover + click selection are driven by PROXIMITY in main.js: it
  // reads world-space anchors via getOverhangAnchors() and calls
  // setHoveredOverhang() / setOverhangSelectionHighlight(). Hover + click
  // selection are gated on the overhang tool (toolFilters.overhangLocations,
  // the "ovhg" button); when it's off, overhangs ignore the pointer so a part
  // buried under them stays selectable. The "show all" labels toggle
  // (showOverhangNames) and persisted selection rings are independent.
  const _ovhgLabelGroup = new THREE.Group()
  _ovhgLabelGroup.name = 'sharedOverhangNames'
  _ovhgLabelGroup.renderOrder = 12
  scene.add(_ovhgLabelGroup)

  const _ovhgSelGroup = new THREE.Group()
  _ovhgSelGroup.name = 'overhangSelHighlight'
  _ovhgSelGroup.renderOrder = 20
  scene.add(_ovhgSelGroup)

  let _ovhgAnchors = []          // [{instanceId, overhangId, label, local: Vector3, world: Vector3}]
  let _ovhgAnchorsByInstance = new Map()   // instanceId -> anchor[] (live-drag reposition index)
  let _ovhgSelList = []          // selected [{instanceId, overhangId}]
  let _ovhgHover   = null        // hovered {instanceId, overhangId} | null
  let _ovhgRingTex = null
  const _ovhgLabelTexCache = new Map()   // label text -> { tex, aspect }

  const _ovhgKey = (o) => `${o.instanceId}|${o.overhangId}`

  function _overhangLabelTex(label) {
    let e = _ovhgLabelTexCache.get(label)
    if (!e) {
      const tex = _makeOverhangNameTexture(label)
      e = { tex, aspect: tex.image.width / tex.image.height }
      _ovhgLabelTexCache.set(label, e)
    }
    return e
  }

  function _overhangRingTexture() {
    if (_ovhgRingTex) return _ovhgRingTex
    const c = document.createElement('canvas')
    c.width = c.height = 64
    const g = c.getContext('2d')
    g.strokeStyle = '#3cff8e'
    g.lineWidth = 7
    g.beginPath()
    g.arc(32, 32, 25, 0, Math.PI * 2)
    g.stroke()
    _ovhgRingTex = new THREE.CanvasTexture(c)
    return _ovhgRingTex
  }

  function _clearSpriteGroup(group) {
    for (const ch of [...group.children]) {
      group.remove(ch)
      ch.material?.dispose?.()   // textures are cached/shared — don't dispose here
    }
  }

  // World-space anchor (label position) for every labeled overhang on every
  // visible instance. Cheap data only; recomputed on geometry rebuild.
  function _computeOverhangAnchors() {
    _ovhgAnchors = []
    _ovhgAnchorsByInstance = new Map()
    const assembly = store.getState().currentAssembly
    if (!assembly) return
    const mat = new THREE.Matrix4()
    for (const srcEntry of _sources.values()) {
      const locals = _overhangLabelAnchorsLocal(srcEntry.design, srcEntry.nucleotides)
      if (!locals.length) continue
      for (let i = 0; i < srcEntry.instanceIds.length; i++) {
        if (srcEntry.visibility[i] < 0.5) continue
        const inst = assembly.instances?.find(x => x.id === srcEntry.instanceIds[i])
        if (!inst || inst.visible === false) continue
        const off = i * 16
        for (let k = 0; k < 16; k++) mat.elements[k] = srcEntry.xformData[off + k]
        const instanceId = srcEntry.instanceIds[i]
        for (const a of locals) {
          // Keep the design-LOCAL anchor so a live gizmo drag can re-derive the
          // world position without a full rebuild (see _liveMoveOverhangOverlays).
          const local = new THREE.Vector3(a.x, a.y, a.z)
          const world = local.clone().applyMatrix4(mat)
          const anchor = { instanceId, overhangId: a.overhangId, label: a.label, local, world }
          _ovhgAnchors.push(anchor)
          if (!_ovhgAnchorsByInstance.has(instanceId)) _ovhgAnchorsByInstance.set(instanceId, [])
          _ovhgAnchorsByInstance.get(instanceId).push(anchor)
        }
      }
    }
  }

  // Live-drag: reposition this instance's overhang overlay sprites (labels +
  // selection rings) to follow its new matrix.  The shared path keeps these
  // sprites in WORLD space in scene-level groups (no per-instance Three.js
  // group), so unlike geometry — which the GPU xform texture moves for free —
  // a gizmo move must re-derive their anchors here.  Cheap: only labeled /
  // selected overhangs on the dragged instance are touched.
  function _liveMoveOverhangOverlays(instanceId, matrix4) {
    const anchors = _ovhgAnchorsByInstance.get(instanceId)
    if (!anchors?.length) return
    for (const a of anchors) a.world.copy(a.local).applyMatrix4(matrix4)
    const byOverhang = new Map(anchors.map(a => [a.overhangId, a.world]))
    for (const sp of _ovhgLabelGroup.children) {
      if (sp.userData?.instanceId !== instanceId) continue
      const w = byOverhang.get(sp.userData.overhangId)
      if (w) sp.position.copy(w)
    }
    for (const ring of _ovhgSelGroup.children) {
      if (ring.userData?.instanceId !== instanceId) continue
      const w = byOverhang.get(ring.userData.overhangId)
      if (w) ring.position.copy(w)
    }
  }

  function _addOverhangLabelSprite(a) {
    const { tex, aspect } = _overhangLabelTex(a.label)
    const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: tex, depthTest: false, transparent: true }))
    sprite.scale.set(_OVHG_SPRITE_HEIGHT_BASE * aspect, _OVHG_SPRITE_HEIGHT_BASE, 1)
    sprite.position.copy(a.world)
    sprite.renderOrder = 12
    sprite.userData = { tag: 'overhang-name', overhangId: a.overhangId, overhangLabel: a.label, instanceId: a.instanceId }
    _ovhgLabelGroup.add(sprite)
  }

  // Visible label set = (showAll ? all) ∪ selected ∪ hovered.
  function rebuildOverhangLabels() {
    _clearSpriteGroup(_ovhgLabelGroup)
    if (_photoMode) return
    const showAll  = !!store.getState().showOverhangNames
    const selKeys  = new Set(_ovhgSelList.map(_ovhgKey))
    const hoverKey = _ovhgHover ? _ovhgKey(_ovhgHover) : null
    for (const a of _ovhgAnchors) {
      const k = _ovhgKey(a)
      if (showAll || selKeys.has(k) || k === hoverKey) _addOverhangLabelSprite(a)
    }
  }

  function _rebuildOverhangSelHighlight() {
    _clearSpriteGroup(_ovhgSelGroup)
    if (_photoMode || !_ovhgSelList.length) return
    const byKey = new Map(_ovhgAnchors.map(a => [_ovhgKey(a), a]))
    for (const sel of _ovhgSelList) {
      const a = byKey.get(_ovhgKey(sel))
      if (!a) continue
      const ring = new THREE.Sprite(new THREE.SpriteMaterial({
        map: _overhangRingTexture(), depthTest: false, transparent: true,
      }))
      ring.position.copy(a.world)
      ring.scale.setScalar(2.4)
      ring.renderOrder = 20
      ring.userData = { instanceId: sel.instanceId, overhangId: sel.overhangId }
      _ovhgSelGroup.add(ring)
    }
  }

  // Full overhang-overlay refresh after a geometry rebuild / photo toggle.
  function rebuildOverhangNames() {
    _computeOverhangAnchors()
    rebuildOverhangLabels()
    _rebuildOverhangSelHighlight()
  }

  // Toggle "show all overhang labels" → relabel (anchors unchanged).
  store.subscribe((newState, prevState) => {
    if (newState.showOverhangNames !== prevState.showOverhangNames) rebuildOverhangLabels()
  })

  /** Public: selected overhangs (list of {instanceId, overhangId}) → rings + persistent labels. */
  function setOverhangSelectionHighlight(list) {
    _ovhgSelList = Array.isArray(list) ? list : []
    rebuildOverhangLabels()
    _rebuildOverhangSelHighlight()
  }

  /** Public: hovered overhang ({instanceId, overhangId} | null) → transient label. */
  function setHoveredOverhang(h) {
    const next = h ? _ovhgKey(h) : null
    const cur  = _ovhgHover ? _ovhgKey(_ovhgHover) : null
    if (next === cur) return
    _ovhgHover = h ? { instanceId: h.instanceId, overhangId: h.overhangId } : null
    if (store.getState().showOverhangNames) return   // everything already shown
    rebuildOverhangLabels()
  }

  /** Public: world-space anchors for proximity hit-testing (hover + click) in main.js. */
  function getOverhangAnchors() {
    return _ovhgAnchors.map(a => ({ instanceId: a.instanceId, overhangId: a.overhangId, label: a.label, world: a.world }))
  }

  function _disposeOverhangOverlays() {
    _clearSpriteGroup(_ovhgLabelGroup)
    _clearSpriteGroup(_ovhgSelGroup)
    for (const { tex } of _ovhgLabelTexCache.values()) tex.dispose?.()
    _ovhgLabelTexCache.clear()
    _ovhgRingTex?.dispose?.(); _ovhgRingTex = null
    _ovhgAnchors = []; _ovhgSelList = []; _ovhgHover = null
  }

  // ── Public: updateStrandColor ─────────────────────────────────────────────
  // Live UI strand-color change. For each source we:
  //   1. Update the source's `customColors` dict (strandId → hex int).
  //   2. Re-run `buildHelixObjects` with the updated colors into a throwaway
  //      Group, producing fresh InstancedMeshes whose `instanceColor.array`
  //      already encodes the new per-bp colors (helix_renderer.js owns the
  //      bp-slot → strand mapping).
  //   3. Walk the temp helixCtrl + the patched activeMeshes IN PARALLEL
  //      (traverse order is deterministic from buildHelixObjects), copying
  //      each temp InstancedMesh's `instanceColor.array` into the matching
  //      activeMeshes entry's `bpColorData` Float32Array. Mark
  //      `bpColorTex.needsUpdate = true` for a full re-upload on the next
  //      frame (bp color textures are 1 × bp_count × RGBA32F, typically a
  //      few KB per mesh — full re-upload is cheap relative to per-row
  //      `texSubImage2D` bookkeeping, and the user-visible UI click already
  //      cost the buildHelixObjects rebuild).
  //   4. Dispose the temp helixCtrl group (its InstancedMeshes + geometries
  //      + materials).
  //
  // The bp-color mapping is implicit inside helix_renderer.js (option C in
  // the Phase 3d-A spec); we never inspect it directly.
  function _applyCrossoverColorsToSource(srcEntry, mode) {
    if (!srcEntry) return
    const dimGray = 0xbbbbbb
    const clusterColor = mode === 'cluster'
      ? buildClusterColorLookup(srcEntry.design)
      : null
    const color = new THREE.Color()

    // Arc lines use the same endpoint-owner rule as the individual design:
    // fromNuc's cluster wins, then toNuc, then the natural strand colour.
    srcEntry.crossoverArcGroup?.traverse(line => {
      const conns = line.userData?.arcConnections
      const attr = line.geometry?.getAttribute?.('color')
      if (!conns || !attr) return
      for (let a = 0; a < conns.length; a++) {
        const conn = conns[a]
        const isOverhang = conn.fromNuc?.overhang_id != null || conn.toNuc?.overhang_id != null
        const clusterHex = clusterColor
          ? (clusterColor(conn.fromNuc) ?? clusterColor(conn.toNuc))
          : undefined
        const hex = clusterHex
          ?? ((mode === 'overhang-only' && !isOverhang) ? dimGray : (conn.color ?? 0x00ccff))
        color.setHex(hex)
        const start = a * (_XOVER_ARC_SEGS + 1) * 3
        const end = start + (_XOVER_ARC_SEGS + 1) * 3
        for (let i = start; i < end; i += 3) {
          attr.array[i] = color.r; attr.array[i + 1] = color.g; attr.array[i + 2] = color.b
        }
      }
      attr.needsUpdate = true
    })

    // Extra crossover bases are shared-instanced, so update their GPU colour
    // textures rather than the now-collapsed instanceColor attributes.
    const xr = srcEntry.xoverResult
    if (!xr?.arcData) return
    const activeFor = mesh => srcEntry.activeMeshes?.find(item => item.mesh === mesh)
    const bead = activeFor(xr.beadsMesh)
    const slab = activeFor(xr.slabsMesh)
    const connector = activeFor(xr.connMesh)
    const slabConnector = activeFor(xr.slabConnMesh)
    const write = (active, index, hex) => {
      if (!active?.bpColorData || index < 0 || index >= active.baseCount) return
      color.setHex(hex)
      const offset = index * 4
      active.bpColorData[offset] = color.r
      active.bpColorData[offset + 1] = color.g
      active.bpColorData[offset + 2] = color.b
      active.bpColorData[offset + 3] = 1
    }
    for (const arc of xr.arcData) {
      const isOverhang = arc.nucA?.overhang_id != null || arc.nucB?.overhang_id != null
      const clusterHex = clusterColor
        ? (clusterColor(arc.nucA) ?? clusterColor(arc.nucB))
        : undefined
      const beadHex = clusterHex
        ?? ((mode === 'overhang-only' && !isOverhang) ? dimGray : arc.beadBaseColor)
      const slabHex = clusterHex
        ?? ((mode === 'overhang-only' && !isOverhang) ? dimGray : arc.slabBaseColor)
      for (let i = 0; i < arc.beadCount; i++) {
        write(bead, arc.beadStartIdx + i, beadHex)
        write(slab, arc.beadStartIdx + i, slabHex)
        write(slabConnector, arc.beadStartIdx + i, slabHex)
      }
      for (let i = 0; i < arc.beadCount + 1; i++) {
        write(connector, arc.connStartIdx + i, beadHex)
      }
    }
    for (const active of [bead, slab, connector, slabConnector]) {
      if (active?.bpColorTex) active.bpColorTex.needsUpdate = true
    }
  }

  // Re-paint one source's bp-color texture by running `buildHelixObjects`
  // against a throwaway Group (option C from the 3d-A spec). When
  // `modeOverride` is non-null OR the store's coloringMode is not 'strand',
  // also invoke `helixCtrl.applyColoring(mode, ...)` on the throwaway —
  // mirrors the per-instance path's `_applyColoringToEntry`.
  function _applyColorsToSource(srcEntry, modeOverride) {
    if (!srcEntry?.design || !srcEntry?.nucleotides) return
    const tmpGroup = new THREE.Group()
    let tmpHelixCtrl
    try {
      tmpHelixCtrl = buildHelixObjects(
        srcEntry.nucleotides,
        srcEntry.design,
        tmpGroup,
        srcEntry.customColors,
        [],                  // loopStrandIds — assemblies don't track this
        srcEntry.helixAxes,
        srcEntry.rep,
      )
    } catch (err) {
      console.warn('[shared_renderer] _applyColorsToSource: buildHelixObjects threw:', err)
      return
    }

    // Apply coloring-mode transform on the temp helixCtrl. buildHelixObjects
    // always paints strand colors; non-strand modes need a follow-up
    // `applyColoring` call. Old per-instance path does the same.
    const mode = modeOverride ?? (store.getState().coloringMode || 'strand')
    if (mode !== 'strand' && typeof tmpHelixCtrl.applyColoring === 'function') {
      try {
        tmpHelixCtrl.applyColoring(mode, srcEntry.design, srcEntry.customColors, new Set())
      } catch (err) {
        console.warn('[shared_renderer] _applyColorsToSource: applyColoring threw:', err)
      }
    }

    // Collect temp InstancedMeshes in traverse order (matches the order in
    // `_patchSharedMeshes`, which uses the same .traverse() over the SAME
    // helixCtrl.root structure). Skip count=0 meshes.
    // Also stash the temp iHelixCylinders mesh by name so we can pull its
    // per-segment instanceColor into the mid-LOD per-helix colour texture.
    const tmpMeshes = []
    let tmpHelixCyl = null
    let tmpOvhgCyl  = null
    tmpHelixCtrl.root.traverse(obj => {
      if (!(obj instanceof THREE.InstancedMesh)) return
      if (obj.name === 'helixCylinders')    tmpHelixCyl = obj
      if (obj.name === 'overhangCylinders' || obj.name === 'overhangFullCylinders') tmpOvhgCyl  = tmpOvhgCyl ?? obj
      if (obj.count === 0) return
      tmpMeshes.push(obj)
    })

    const pairs = Math.min(tmpMeshes.length, srcEntry.activeMeshes.length)
    // Per-bp colour copy into activeMeshes' bpColorTex (full-rep path).
    for (let i = 0; i < pairs; i++) {
      const tmp = tmpMeshes[i]
      const am  = srcEntry.activeMeshes[i]
      if (!tmp.instanceColor) continue
      if (!am.bpColorTex || !am.bpColorData) continue
      const src = tmp.instanceColor.array
      const n   = Math.min(am.baseCount, Math.floor(src.length / 3))
      const dst = am.bpColorData
      for (let j = 0; j < n; j++) {
        dst[j * 4 + 0] = src[j * 3 + 0]
        dst[j * 4 + 1] = src[j * 3 + 1]
        dst[j * 4 + 2] = src[j * 3 + 2]
      }
      am.bpColorTex.needsUpdate = true
    }

    // Direct per-segment colour copy (overhang LOD): the temp mesh's
    // instanceColor already matches the LOD's numSegments 1:1, so we just
    // copy 3 floats per segment into the LOD's 4-float texture rows.
    function _copySegmentColors(lod, tmpMesh) {
      if (!lod?.segColorTex || !tmpMesh?.instanceColor) return
      const src = tmpMesh.instanceColor.array
      const dst = lod.segColorData
      const n = Math.min(lod.numSegments, Math.floor(src.length / 3))
      for (let i = 0; i < n; i++) {
        dst[i * 4 + 0] = src[i * 3 + 0]
        dst[i * 4 + 1] = src[i * 3 + 1]
        dst[i * 4 + 2] = src[i * 3 + 2]
        dst[i * 4 + 3] = 1
      }
      lod.segColorTex.needsUpdate = true
    }
    _copySegmentColors(srcEntry.overhangLod, tmpOvhgCyl)

    // Mid LOD: one cylinder per *contiguous dsDNA region* (interval) →
    // average the legacy iHelixCylinders per-domain colours within each
    // interval.  Each interval carries its own `domains` list with
    // cylIdx entries that index into tmpHelixCyl.instanceColor.
    if (srcEntry.midLod?.segColorTex && srcEntry.midLod?.intervals
        && tmpHelixCyl?.instanceColor) {
      const midLod = srcEntry.midLod
      const intervals = midLod.intervals
      const cylColors = tmpHelixCyl.instanceColor.array
      const dst = midLod.segColorData
      for (let i = 0; i < intervals.length; i++) {
        const iv = intervals[i]
        let sumR = 0, sumG = 0, sumB = 0, count = 0
        for (const d of iv.domains) {
          const ci = d.cylIdx * 3
          sumR += cylColors[ci + 0]
          sumG += cylColors[ci + 1]
          sumB += cylColors[ci + 2]
          count++
        }
        if (count > 0) {
          dst[i * 4 + 0] = sumR / count
          dst[i * 4 + 1] = sumG / count
          dst[i * 4 + 2] = sumB / count
        } else {
          dst[i * 4 + 0] = 1
          dst[i * 4 + 1] = 1
          dst[i * 4 + 2] = 1
        }
        dst[i * 4 + 3] = 1
      }
      midLod.segColorTex.needsUpdate = true
    }

    // Curved-cyl LOD (bent parts): its cylinders are a baked TubeGeometry whose
    // per-vertex colours were frozen at build time, so live coloringMode changes
    // never reached it (the documented "Known v1 limitation").  Re-bake the
    // colour attribute from the freshly-recoloured temp helixCtrl and copy it
    // into the live geometry so bent parts track the coloringMode like straight
    // ones.  Vertex order/count are deterministic from the same source, so a
    // plain array copy suffices (guarded on count).
    if (srcEntry.curvedCylLod?.mesh?.geometry) {
      const reGeo = _curvedCylGeoForSource(tmpHelixCtrl)
      if (reGeo) {
        const newCol = reGeo.getAttribute('color')
        const dstCol = srcEntry.curvedCylLod.mesh.geometry.getAttribute('color')
        if (newCol && dstCol && newCol.count === dstCol.count) {
          dstCol.array.set(newCol.array)
          dstCol.needsUpdate = true
        }
        reGeo.dispose()
      }
    }

    _applyCrossoverColorsToSource(srcEntry, mode)

    // (No far/billboard tint to update — the far tier was retired; distant
    // instances render as the flat-grey hull solid, not a coloured rectangle.)

    // Dispose: skip module-level shared template geometries (still in use
    // by the live helixCtrl); dispose the fresh-per-call materials.
    tmpHelixCtrl.root.traverse(obj => {
      if (obj.geometry && !obj.geometry.userData?.shared) obj.geometry.dispose()
      if (obj.material) {
        const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
        mats.forEach(m => m.dispose())
      }
    })
  }

  function updateStrandColor(strandId, hexColor) {
    if (strandId == null || hexColor == null) return
    for (const srcEntry of _sources.values()) {
      srcEntry.customColors[strandId] = hexColor
      _applyColorsToSource(srcEntry, null)  // null = pick current mode from store
    }
  }

  function updateColoringMode(mode) {
    if (mode == null) return
    for (const srcEntry of _sources.values()) {
      if (srcEntry.isAtomistic)    _recolorAtomBatch(srcEntry, mode)
      else if (srcEntry.isSurface) _recolorSurface(srcEntry, mode)
      else _applyColorsToSource(srcEntry, mode)
    }
  }

  // Subscribe to coloringMode changes. Mirrors the per-instance path's
  // subscriber (assembly_renderer.js:1936 in `initAssemblyRenderer`) which
  // doesn't fire when the shared path is active.
  store.subscribe?.((newState, prevState) => {
    if (newState.coloringMode !== prevState.coloringMode) {
      updateColoringMode(newState.coloringMode)
    }
    if (newState.showPeriodicSeamArcs !== prevState.showPeriodicSeamArcs) {
      const show = newState.showPeriodicSeamArcs === true
      for (const srcEntry of _sources.values()) {
        srcEntry.crossoverArcGroup?.traverse(line => {
          if (line.userData?.isPeriodicSeam) line.visible = show
        })
      }
    }
  })

  // ── Public: getBoundingBox ────────────────────────────────────────────────
  function getBoundingBox() {
    const out = new THREE.Box3()
    const tmpInst = new THREE.Matrix4()
    const tmpBox  = new THREE.Box3()
    for (const srcEntry of _sources.values()) {
      const baseBox = srcEntry.instBoundingBox
      if (!baseBox || baseBox.isEmpty()) continue
      for (let i = 0; i < srcEntry.instanceIds.length; i++) {
        if (srcEntry.visibility[i] < 0.5) continue
        // Reconstruct the row-major matrix from xformData. Recall the texel
        // layout stores columns, so reading column-major is direct.
        const o = i * 16
        const e = tmpInst.elements
        for (let k = 0; k < 16; k++) e[k] = srcEntry.xformData[o + k]
        tmpBox.copy(baseBox).applyMatrix4(tmpInst)
        out.union(tmpBox)
      }
    }
    return out
  }

  // Live-drag transform writer.  Gizmo drag callbacks push a new world
  // matrix per affected instance via `setLiveTransform(id, mat)`; we write
  // its column-major elements straight into `xformData` at the instance's
  // row and mark the per-source xform texture dirty so the GPU sees it
  // next frame.  No bbox / collision re-derivation here — the per-frame
  // LOD sort picks the new positions up automatically.
  function setLiveTransform(instanceId, matrix4) {
    if (!instanceId || !matrix4) return
    const srcKey = _instToSrc.get(instanceId)
    if (!srcKey) return
    const srcEntry = _sources.get(srcKey)
    if (!srcEntry) return
    const row = srcEntry.instanceIndex.get(instanceId)
    if (row == null) return
    _packMatrixIntoRow(matrix4, srcEntry.xformData, row * 16)
    // Full texture re-upload.  The per-row texSubImage2D optimisation in
    // `_installDirtyUploader` is gated on activeMeshes.length > 0 (the
    // hook attaches to the first close-LOD mesh); for cylinders-rep
    // sources activeMeshes is empty so the optimisation wouldn't fire.
    // Full upload of a 4×N RGBA32F texture is tiny (~64 bytes/instance)
    // and works uniformly across LODs.
    srcEntry.xformTex.needsUpdate = true
    const arcGroup = srcEntry.crossoverArcGroup?.userData?.instanceGroups?.get(instanceId)
    if (arcGroup) {
      arcGroup.matrix.copy(matrix4)
      arcGroup.matrixWorldNeedsUpdate = true
    }
    // Keep the selection outline glued to the part as it drags.
    if (instanceId === _activeInstanceId) _refreshActiveBox()
    // Overhang label/ring sprites live in world space — drag them along too.
    _liveMoveOverhangOverlays(instanceId, matrix4)
  }

  function getLiveTransform(instanceId) {
    if (!instanceId) return null
    const srcKey = _instToSrc.get(instanceId)
    if (!srcKey) return null
    const srcEntry = _sources.get(srcKey)
    if (!srcEntry) return null
    const row = srcEntry.instanceIndex.get(instanceId)
    if (row == null) return null
    const mat = new THREE.Matrix4()
    const off = row * 16
    for (let k = 0; k < 16; k++) mat.elements[k] = srcEntry.xformData[off + k]
    return mat
  }

  // Blunt-end / free-strand-terminus connectors for every visible instance —
  // the candidate mate points "Define Mate" shows.  Uses the shared
  // `_computeInstanceBluntEnds` helper with each source's design + helixAxes
  // and the per-instance world matrix read from xformData.  (Stubbed before;
  // that's why Define Mate showed nothing on the shared path.)
  function getInstanceBluntEnds() {
    const assembly = store.getState().currentAssembly
    if (!assembly) return []
    const out = []
    const mat = new THREE.Matrix4()
    for (const srcEntry of _sources.values()) {
      const design = srcEntry.design
      const helixAxes = srcEntry.helixAxes ?? {}
      if (!design?.helices?.length) continue
      for (let i = 0; i < srcEntry.instanceIds.length; i++) {
        if (srcEntry.visibility[i] < 0.5) continue
        const instId = srcEntry.instanceIds[i]
        const inst = assembly.instances?.find(x => x.id === instId)
        if (!inst || inst.visible === false) continue
        const off = i * 16
        const e = mat.elements
        for (let k = 0; k < 16; k++) e[k] = srcEntry.xformData[off + k]
        const instName = inst.name ?? instId.slice(0, 6)
        const ends = _computeInstanceBluntEnds(design, helixAxes, mat, instId, instName)
        for (const be of ends) out.push(be)
      }
    }
    return out
  }

  function getConnectorClusterId(instanceId, label) {
    if (!instanceId || !label) return null
    const c = getInstanceBluntEnds().find(x => x.instanceId === instanceId && x.label === label)
    return c?.clusterId ?? null
  }

  function getConnectorClusterIds(instanceId, label) {
    if (!instanceId || !label) return []
    const c = getInstanceBluntEnds().find(x => x.instanceId === instanceId && x.label === label)
    return c?.clusterIds?.length ? c.clusterIds : (c?.clusterId ? [c.clusterId] : [])
  }

  // Bend center-of-curvature connectors per visible instance for Define-Mate.
  // Fetched lazily from the backend (per-instance, since cluster overrides can
  // vary), cached per instance. World-frame records use the instance's live
  // xformData matrix the same way getInstanceBluntEnds does.
  async function getInstanceBendCenters() {
    const assembly = store.getState().currentAssembly
    if (!assembly) return []
    const out = []
    const tmp = new THREE.Matrix4()
    const tasks = []
    for (const srcEntry of _sources.values()) {
      for (let i = 0; i < srcEntry.instanceIds.length; i++) {
        if (srcEntry.visibility[i] < 0.5) continue
        const instId = srcEntry.instanceIds[i]
        const inst = assembly.instances?.find(x => x.id === instId)
        if (!inst || inst.visible === false) continue
        tasks.push({ instId, inst, srcEntry, row: i })
      }
    }
    await Promise.all(tasks.map(async t => {
      let local = _bendCentersLocalCache.get(t.instId)
      if (!local) {
        try {
          const resp = await api.getInstanceBendCenters(t.instId)
          local = resp?.bend_centers ?? []
          _bendCentersLocalCache.set(t.instId, local)
        } catch { local = [] }
      }
      if (!local.length) return
      const off = t.row * 16
      const mat = tmp.clone()
      for (let k = 0; k < 16; k++) mat.elements[k] = t.srcEntry.xformData[off + k]
      const instName = t.inst.name ?? t.instId.slice(0, 6)
      for (const bc of local) {
        out.push(_bendCenterRecordToWorld(bc, mat, t.instId, instName))
      }
    }))
    return out
  }

  // ── Phase 7a: per-instance introspection (shared path) ────────────────────
  // On the shared path there is no per-instance helixCtrl — geometry is one
  // shared helixCtrl per source, GPU-composed. But the source helixCtrl still
  // carries `backboneEntries` in SOURCE-LOCAL coords, and the per-instance
  // world matrix lives in `xformData`. Callers (cluster glow, overhang arrows)
  // already apply that matrix to local positions themselves, so we just hand
  // back the source-local data + the instance's world matrix.

  // The Design dict for an instance's source. Used by cluster articulation +
  // the cluster-panel glow to resolve cluster_transforms / cluster_joints.
  function getInstanceDesign(instanceId) {
    const srcKey = instanceId ? _instToSrc.get(instanceId) : null
    return (srcKey ? _sources.get(srcKey)?.design : null) ?? null
  }

  // Source-local backbone beads + the instance's world matrix. Mirrors the
  // per-instance path's shape ({ entries, matrixWorld }); the caller maps
  // `entry.pos.applyMatrix4(matrixWorld)` to reach world space.
  function getInstanceBackboneEntries(instanceId) {
    const empty = { entries: [], matrixWorld: new THREE.Matrix4() }
    const srcKey = instanceId ? _instToSrc.get(instanceId) : null
    const srcEntry = srcKey ? _sources.get(srcKey) : null
    if (!srcEntry) return empty
    const mw = getLiveTransform(instanceId) ?? new THREE.Matrix4()
    return { entries: srcEntry.helixCtrl?.backboneEntries ?? [], matrixWorld: mw }
  }

  // Render data for overhang-locations: the design + source-local nucleotides
  // plus a scene group positioned at the instance's world transform, so the
  // overhang arrows (built in design-local coords) land at the right place.
  // overhang-locations only ever renders the ACTIVE instance, so a single
  // reused parent group is enough (it re-clears its own children each rebuild).
  let _renderDataGroup = null
  function getInstanceRenderData(instanceId) {
    const srcKey = instanceId ? _instToSrc.get(instanceId) : null
    const srcEntry = srcKey ? _sources.get(srcKey) : null
    if (!srcEntry) return null
    const mw = getLiveTransform(instanceId)
    if (!mw) return null
    if (!_renderDataGroup) {
      _renderDataGroup = new THREE.Group()
      _renderDataGroup.name = 'shared_instance_render_data'
      _renderDataGroup.matrixAutoUpdate = false
      scene.add(_renderDataGroup)
    }
    _renderDataGroup.matrix.copy(mw)
    _renderDataGroup.matrixWorldNeedsUpdate = true
    return {
      design:      srcEntry.design ?? null,
      nucleotides: srcEntry.nucleotides ?? null,
      group:       _renderDataGroup,
    }
  }

  // ── Phase 7c: cluster articulation via a materialized active instance ─────
  // The shared batch stores bp geometry in a per-SOURCE texture, so rotating
  // ONE instance's cluster can't be done in the batch without moving every
  // copy of that source.  When the user articulates a cluster we build a real
  // single-instance helixCtrl in world space (the per-instance render path,
  // unpatched), hide that instance's slot in the batch, and delegate
  // captureClusterBase / applyClusterTransform to it.  rebuild()/dispose()
  // tear it down and restore the batch slot.  Only ONE instance is ever
  // materialized at a time (the one being articulated), so the cost is a
  // single extra helixCtrl — negligible.
  let _matInst = null   // { id, srcKey, group, helixCtrl }

  // Toggle a batch slot's visibility (used to hide the materialized instance's
  // duplicate in the shared batch). visData moves WITH the id through the
  // per-frame LOD permutation, so writing the current row stays correct.
  function _setBatchSlotVisible(srcEntry, id, visible) {
    const row = srcEntry?.instanceIndex?.get(id)
    if (row == null) return
    srcEntry.visibility[row] = visible ? 1.0 : 0.0
    srcEntry.visData[row * 16 + 0] = srcEntry.visibility[row]
    srcEntry.dirtyVisRows.add(row)
    const arcGroup = srcEntry.crossoverArcGroup?.userData?.instanceGroups?.get(id)
    if (arcGroup) arcGroup.visible = visible
  }

  function _materializeInstance(id) {
    if (_matInst && _matInst.id === id) return _matInst
    _dematerializeInstance()
    const srcKey   = id ? _instToSrc.get(id) : null
    const srcEntry = srcKey ? _sources.get(srcKey) : null
    if (!srcEntry?.design || !srcEntry?.nucleotides) return null
    const mw = getLiveTransform(id)
    if (!mw) return null
    const group = new THREE.Group()
    group.userData.assemblyInstance     = id
    group.userData.materializedInstance = true
    group.matrixAutoUpdate = false
    group.matrix.copy(mw)
    group.matrixWorldNeedsUpdate = true
    // Unpatched, single-instance helixCtrl — its geometry is mutable in place,
    // which is exactly what captureClusterBase/applyClusterTransform need.
    const helixCtrl = buildHelixObjects(
      srcEntry.nucleotides, srcEntry.design, group,
      srcEntry.customColors, [], srcEntry.helixAxes ?? null, srcEntry.rep,
    )
    helixCtrl.setAxisArrowsVisible?.(false)
    // buildHelixObjects starts every LOD mesh with visible=false; setDetailLevel
    // flips the right ones on (the bp-invisibility lesson — without this the
    // overlay renders nothing and the user sees no articulation).
    if (helixCtrl.root) helixCtrl.root.visible = true
    helixCtrl.setDetailLevel?.(CG_LOD[srcEntry.rep] ?? CG_LOD.cylinders)
    scene.add(group)
    _setBatchSlotVisible(srcEntry, id, false)   // hide the batch copy
    _matInst = { id, srcKey, group, helixCtrl }
    return _matInst
  }

  function _dematerializeInstance() {
    if (!_matInst) return
    const { id, srcKey, group } = _matInst
    // Restore the batch slot (respecting the instance's own visibility flag).
    const srcEntry = _sources.get(srcKey)
    if (srcEntry) {
      const inst = store.getState().currentAssembly?.instances?.find(i => i.id === id)
      _setBatchSlotVisible(srcEntry, id, inst?.visible !== false)
    }
    scene.remove(group)
    group.traverse(o => {
      if (o.geometry && !o.geometry.userData?.shared) o.geometry.dispose()
      if (o.material) {
        const mats = Array.isArray(o.material) ? o.material : [o.material]
        mats.forEach(m => { m.map?.dispose?.(); m.dispose?.() })
      }
    })
    _matInst = null
  }

  function captureInstanceClusterBase(instanceId, cluster) {
    if (!instanceId || !cluster) return
    const mat = _materializeInstance(instanceId)
    if (!mat) return
    mat.helixCtrl?.captureClusterBase(
      cluster.helix_ids,
      cluster.domain_ids?.length ? cluster.domain_ids : null,
    )
  }

  function applyInstanceClusterTransform(instanceId, cluster, centerVec, dummyPosVec, incrRotQuat) {
    if (!instanceId || !cluster) return
    const mat = (_matInst && _matInst.id === instanceId)
      ? _matInst
      : _materializeInstance(instanceId)
    if (!mat) return
    mat.helixCtrl?.applyClusterTransform(
      cluster.helix_ids,
      centerVec,
      dummyPosVec,
      incrRotQuat,
      cluster.domain_ids?.length ? cluster.domain_ids : null,
    )
  }

  // Pick the cluster whose member beads are nearest the click. Mirrors the
  // per-instance nearest-bead fallback: project each source's SOURCE-LOCAL
  // backboneEntries through the per-instance world matrix. Needs beads, so
  // (like the per-instance path) it only resolves at a bead-bearing rep —
  // the cluster-panel selection path works at any rep via the 7a getters.
  function pickInstanceCluster(ndc, camera, { scopeInstId = null, threshold = 0.06 } = {}) {
    const assembly = store.getState().currentAssembly
    if (!assembly) return null
    const _proj = new THREE.Vector3()
    const mw = new THREE.Matrix4()
    let bestDist = threshold
    let bestResult = null
    for (const srcEntry of _sources.values()) {
      const beads  = srcEntry.helixCtrl?.backboneEntries ?? []
      const joints = srcEntry.design?.cluster_joints ?? []
      if (!beads.length || !joints.length) continue
      const clusters = srcEntry.design?.cluster_transforms ?? []
      for (let i = 0; i < srcEntry.instanceIds.length; i++) {
        if (srcEntry.visibility[i] < 0.5) continue
        const instId = srcEntry.instanceIds[i]
        if (scopeInstId && instId !== scopeInstId) continue
        const inst = assembly.instances?.find(x => x.id === instId)
        if (!inst) continue
        const off = i * 16
        for (let k = 0; k < 16; k++) mw.elements[k] = srcEntry.xformData[off + k]
        for (const joint of joints) {
          const cluster = clusters.find(c => c.id === joint.cluster_id)
          const filter  = _clusterMemberFilter(cluster, srcEntry.design)
          if (!filter) continue
          for (const bead of beads) {
            if (!filter(bead.nuc)) continue
            _proj.copy(bead.pos).applyMatrix4(mw).project(camera)
            const d = Math.hypot(_proj.x - ndc.x, _proj.y - ndc.y)
            if (d < bestDist) {
              bestDist   = d
              bestResult = { inst, design: srcEntry.design, cluster, joint, entry: bead }
            }
          }
        }
      }
    }
    return bestResult
  }

  // Ray-vs-per-instance-ORIENTED-box picker.  The shared path can't reuse
  // THREE.Raycaster.intersectObjects because instanceMatrix is collapsed
  // to identity (per-instance transforms live in `xformData`, sampled by
  // the shader).  We test the source's LOCAL bbox in each instance's own
  // frame: transform the camera ray by the inverse instance matrix, then
  // ray-vs-(axis-aligned local box).  This is an oriented-box test in
  // world space — far tighter than a world-space AABB, which for rotated
  // hinges balloons ~50 % and makes adjacent instances' boxes overlap so
  // a click on one selects its neighbour/duplicate.  Returns the closest
  // hit (distance measured in world space).
  const _pickRaycaster = new THREE.Raycaster()
  function pickInstance(ndc, camera) {
    if (_sources.size === 0) return null
    _pickRaycaster.setFromCamera(ndc, camera)
    const worldRay = _pickRaycaster.ray
    const tmpInst = new THREE.Matrix4()
    const tmpInv  = new THREE.Matrix4()
    const localRay = new THREE.Ray()
    const tmpHit  = new THREE.Vector3()
    let bestDist = Infinity
    let bestId = null
    for (const srcEntry of _sources.values()) {
      const baseBox = srcEntry.instBoundingBox
      if (!baseBox || baseBox.isEmpty()) continue
      for (let i = 0; i < srcEntry.instanceIds.length; i++) {
        if (srcEntry.visibility[i] < 0.5) continue
        const o = i * 16
        const e = tmpInst.elements
        for (let k = 0; k < 16; k++) e[k] = srcEntry.xformData[o + k]
        // Ray into instance-local space, then test the local AABB.
        tmpInv.copy(tmpInst).invert()
        localRay.copy(worldRay).applyMatrix4(tmpInv)
        const hit = localRay.intersectBox(baseBox, tmpHit)
        if (!hit) continue
        // hit is local; bring it back to world for a comparable distance.
        tmpHit.applyMatrix4(tmpInst)
        const d = worldRay.origin.distanceToSquared(tmpHit)
        if (d < bestDist) {
          bestDist = d
          bestId = srcEntry.instanceIds[i]
        }
      }
    }
    if (!bestId) return null
    const assembly = store.getState().currentAssembly
    return assembly?.instances?.find(i => i.id === bestId) ?? null
  }

  // Raycast the linker group; return the overhang-connection id under the
  // cursor (any linker mesh — complement / bridge beads or connector arc), or
  // null. Connector arcs carry userData.connId; bead hits fall back to the
  // nearest tagged linker nuc. Used by the right-click → Relax menu.
  function pickLinker(ndc, camera) {
    if (!_linkerGroup.children.length) return null
    _pickRaycaster.setFromCamera(ndc, camera)
    const hits = _pickRaycaster.intersectObject(_linkerGroup, true)
    if (!hits.length) return null
    for (let o = hits[0].object; o && o !== _linkerGroup; o = o.parent) {
      if (o.userData?.connId) return o.userData.connId
    }
    const nucs = _linkerGroup.userData.linkerNucs ?? []
    const hp = hits[0].point
    let best = null, bestD = Infinity
    for (const n of nucs) {
      const dx = hp.x - n.pos[0], dy = hp.y - n.pos[1], dz = hp.z - n.pos[2]
      const d = dx * dx + dy * dy + dz * dz
      if (d < bestD) { bestD = d; best = n }
    }
    return best?.connId ?? null
  }

  /**
   * Per-instance world centers + radii. Called every frame by nav_controller's
   * fly-mode threshold check; must NOT throw or the rAF loop spams the console.
   * Returns `Array<{id, center: THREE.Vector3, radius: number}>`, same shape
   * as the old path's `getInstanceCenters()`.
   */
  function getInstanceCenters() {
    const out = []
    const tmpInst = new THREE.Matrix4()
    const tmpBox  = new THREE.Box3()
    for (const srcEntry of _sources.values()) {
      const baseBox = srcEntry.instBoundingBox
      if (!baseBox || baseBox.isEmpty()) continue
      for (let i = 0; i < srcEntry.instanceIds.length; i++) {
        if (srcEntry.visibility[i] < 0.5) continue
        const o = i * 16
        const e = tmpInst.elements
        for (let k = 0; k < 16; k++) e[k] = srcEntry.xformData[o + k]
        tmpBox.copy(baseBox).applyMatrix4(tmpInst)
        if (tmpBox.isEmpty()) continue
        const center = tmpBox.getCenter(new THREE.Vector3())
        const size   = tmpBox.getSize(new THREE.Vector3())
        const radius = Math.max(size.x, size.y, size.z) * 0.5
        // Include the world-space bbox `size` (xyz extents) so callers
        // computing axis-specific offsets (e.g. duplicate placement) can
        // use the actual extent along their axis of interest instead of
        // the max-radius (which over-spaces parts oriented perpendicular
        // to that axis).  `size` is a fresh Vector3 — callers may mutate.
        out.push({ id: srcEntry.instanceIds[i], center, radius, size })
      }
    }
    return out
  }

  // ── Public: applyGroupVisibilityOverlay ───────────────────────────────────
  // Combined per-instance + group visibility, applied WITHOUT a rebuild. An
  // instance draws iff its own `visible !== false` AND it is not inside a
  // hidden PartGroup. We write the per-source visibility texture (the shared
  // shaders discard rows whose `v_visible < 0.5`) and flag the row dirty so the
  // per-frame `_uploadRows` flush picks it up — O(N) over instances, no geometry
  // re-fetch. Surface-rep sources have no vis-texture path (a plain
  // InstancedMesh), so we bake visibility into their instanceMatrix directly;
  // surface sources skip the LOD permutation (see `_updateLodForSource`), so
  // `instanceIndex` rows stay aligned with the surface mesh's rows.
  function applyGroupVisibilityOverlay(hiddenInstanceIds) {
    const hidden = hiddenInstanceIds instanceof Set
      ? hiddenInstanceIds
      : new Set(hiddenInstanceIds || [])
    const instances = store.getState().currentAssembly?.instances ?? []
    const selfVisible = new Map(instances.map(i => [i.id, i.visible !== false]))
    const _m = new THREE.Matrix4()
    for (const srcEntry of _sources.values()) {
      const sm = srcEntry.surfaceMesh?.mesh
      for (const [id, row] of srcEntry.instanceIndex.entries()) {
        const vis = (selfVisible.get(id) ?? true) && !hidden.has(id)
        srcEntry.visibility[row]        = vis ? 1.0 : 0.0
        srcEntry.visData[row * 16 + 0]  = srcEntry.visibility[row]
        srcEntry.dirtyVisRows.add(row)
        const arcGroup = srcEntry.crossoverArcGroup?.userData?.instanceGroups?.get(id)
        if (arcGroup) arcGroup.visible = vis
        if (sm) {
          if (vis) {
            for (let k = 0; k < 16; k++) _m.elements[k] = srcEntry.xformData[row * 16 + k]
            sm.setMatrixAt(row, _m)
          } else {
            sm.setMatrixAt(row, _m.makeScale(0, 0, 0))
          }
        }
      }
      if (sm) sm.instanceMatrix.needsUpdate = true
    }
  }

  // ── Public: onRebuildComplete ─────────────────────────────────────────────
  function onRebuildComplete(fn) { _onRebuildCompleteCbs.push(fn) }
  function _fireRebuildComplete() {
    for (const fn of _onRebuildCompleteCbs) {
      try { fn() } catch (e) { console.warn('[shared_renderer] cb threw:', e) }
    }
  }

  // ── Public: stubs for out-of-plan-scope methods ───────────────────────────
  // No-op with a one-time console.warn so a missing implementation is visible
  // in DevTools without spamming the rAF loop / pointerdown handlers / load
  // pipeline. Each stub returns the type the per-instance path would return,
  // so callers fall through their `if (!result) return` guards naturally.
  const _stubWarned = new Set()
  function _outOfScope(name) {
    const fallback = _SHARED_RENDERER_STUB_DEFAULTS[name]
    return (...args) => {
      if (!_stubWarned.has(name)) {
        _stubWarned.add(name)
        console.warn(
          `[shared_renderer] '${name}' not implemented; returning default. ` +
          `Phase 3d/3e/etc. will wire it up. ` +
          `Toggle window.NADOC_SHARED_RENDERER = false for the per-instance path.`,
        )
      }
      return fallback(...args)
    }
  }

  const out = {
    rebuild,
    dispose,
    setActiveInstance,
    applyGroupVisibilityOverlay,
    getBoundingBox,
    getInstanceCenters,
    pickInstance,
    pickLinker,
    setLiveTransform,
    getLiveTransform,
    getInstanceBluntEnds,
    getInstanceBendCenters,
    getConnectorClusterId,
    getConnectorClusterIds,
    getInstanceDesign,
    getInstanceBackboneEntries,
    getInstanceRenderData,
    pickInstanceCluster,
    captureInstanceClusterBase,
    applyInstanceClusterTransform,
    getOverhangAnchors,
    setHoveredOverhang,
    setOverhangSelectionHighlight,
    setPhotoMode,
    rebuildLinkers,
    invalidateInstance,
    applyInlineGeometry,
    onRebuildComplete,
    updateStrandColor,
    updateColoringMode,
    // Phase 3f — LOD ladder (close / mid / hull; no billboard tier)
    setLodThresholds,
    // Photo export: force every instance to its rep's detail bucket regardless
    // of camera distance (suppresses the far→hull demotion) so large figures
    // render uniformly high-detail.  main.js toggles this around an export.
    setSuppressLodDemotion,
    // Phase 3f test/instrumentation hook: drive the per-source LOD bucketing
    // from a test environment without a real render loop. Iterates every
    // active source and applies the same bucketing the onBeforeRender hook
    // would apply each frame.
    _updateLod(camera, renderer) {
      for (const srcEntry of _sources.values()) _updateLodForSource(srcEntry, camera, renderer)
    },
    _sourcesForTest() { return _sources },
    // Debug: snapshot every source's last-frame LOD bucket counts + pixel
    // thresholds + min/max pixel size.  Stashed by _updateLodForSource each
    // frame; this helper formats it into a plain object DevTools can pretty-
    // print.  Use to diagnose "why isn't bp showing when I zoom in?" —
    // compare maxPxSize against closePx to see if the angular threshold
    // is being crossed.
    probeLod() {
      const snap = { closePx: _lodClosePx, farPx: _lodFarPx, sources: [] }
      for (const [srcKey, srcEntry] of _sources.entries()) {
        const dbg = srcEntry._lastLodDebug ?? null
        const counts = srcEntry._lastLodCounts ?? null
        snap.sources.push({
          srcKey,
          numInstances: srcEntry.instanceIds.length,
          counts,
          bboxDiag: dbg?.bboxDiag ?? null,
          pxFactor: dbg?.pxFactor ?? null,
          minPxSize: dbg?.minPxSize ?? null,
          maxPxSize: dbg?.maxPxSize ?? null,
          activeMeshes: srcEntry.activeMeshes.length,
          midLodCount: srcEntry.midLod?.mesh.count ?? null,
          hullLodCount: srcEntry.hullLod?.mesh.count ?? null,
        })
      }
      return snap
    },
  }
  for (const name of _SHARED_RENDERER_STUB_METHODS) out[name] = _outOfScope(name)
  return out
}
