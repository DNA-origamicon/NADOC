/**
 * Far-LOD hull geometry for one assembly SOURCE (a part design), in source-local
 * space.
 *
 * Extracted verbatim from assembly_renderer.js. `_hullGeoForSource` is the solid
 * every part demotes into when it is far from the camera; `_bboxSolidFromNucs`
 * is the fallback for parts that produce no extrusion/scan/cluster geometry, so
 * no source is ever left without a hull bucket (it would vanish when zoomed out).
 *
 * One reason to change: how a part's coarse far-distance solid is built.
 *
 * Consumers: the shared-instancing renderer (assembly_renderer_shared.js) and
 * assembly_joint_renderer.js.
 */
import * as THREE from 'three'
import { mergeGeometries } from 'three/addons/utils/BufferGeometryUtils.js'
import {
  buildExtrusionBoxes, scanExtrusionGroup, dsTrimmedAxes, dsBpByHelix, dsBpRangeByHelix,
  buildOverhangMarkers, buildClusteredOccupancyHull, usesOccupancyHull,
} from './joint_renderer.js'

// Clusters under this fraction of the part's dsDNA bp are dropped from the
// per-cluster hull — matches joint_renderer's _hullMinSizeFraction default.
export const HULL_MIN_SIZE_FRACTION = 0.10

// Curved-hull facet tolerance (nm) for deformed parts in the assembly — matches
// joint_renderer's _hullCurveTolNm default. The design-view slider doesn't reach
// the assembly path (separate renderer); this fixed default keeps the assembly
// hull's faceting in step with the design view's out-of-the-box look.
export const HULL_CURVE_TOL_NM = 1.0

// Coarse axis-aligned bounding-box solid (source-local) over a part's
// nucleotide backbone positions.  This is the FALLBACK hull for parts that
// produce no extrusion/scan/cluster geometry (e.g. a bare imported strand set),
// so every source still has a far-LOD solid to demote into — without it, the
// distance ladder would have no hull bucket and such parts would simply vanish
// when zoomed far out.  Prefers dsDNA nucleotides (matching the hull's
// dsDNA-only convention) and falls back to all positioned nucleotides.
// Returns a non-indexed position+normal BoxGeometry, or null.
export function _bboxSolidFromNucs(nucleotides) {
  if (!nucleotides?.length) return null
  const box = new THREE.Box3()
  const v = new THREE.Vector3()
  let n = 0
  const dsCount = new Map()
  for (const nuc of nucleotides) {
    if (!nuc.strand_id || nuc.overhang_id) continue
    const k = nuc.helix_id + ':' + nuc.bp_index
    dsCount.set(k, (dsCount.get(k) ?? 0) + 1)
  }
  for (const nuc of nucleotides) {
    const p = nuc.backbone_position
    if (!p || !nuc.strand_id || nuc.overhang_id) continue
    if ((dsCount.get(nuc.helix_id + ':' + nuc.bp_index) ?? 0) < 2) continue
    box.expandByPoint(v.set(p[0], p[1], p[2])); n++
  }
  if (n === 0) {                              // no dsDNA — bound all positioned nucs
    for (const nuc of nucleotides) {
      const p = nuc.backbone_position
      if (!p) continue
      box.expandByPoint(v.set(p[0], p[1], p[2])); n++
    }
  }
  if (n === 0 || box.isEmpty()) return null
  box.expandByScalar(1.0)                     // ~1 nm pad for the backbone tube radius
  const size = box.getSize(new THREE.Vector3())
  const c = box.getCenter(new THREE.Vector3())
  const geo = new THREE.BoxGeometry(
    Math.max(size.x, 0.5), Math.max(size.y, 0.5), Math.max(size.z, 0.5),
  )
  geo.translate(c.x, c.y, c.z)
  return geo.toNonIndexed()
}

// Source-local merged Hull Prism solid for the shared instancing path.
// Mirrors joint_renderer._rebuildHullRepr's full decision tree so each part
// renders the same hull in an assembly as in the single-design view:
//   1. feature-log extrusion boxes (NADOC-built parts), else
//   2. dsDNA-trimmed cross-section scan (cluster-less imports), else
//   3. per-cluster dsDNA cross-section SCAN (clustered parts w/o build history
//      — e.g. hinges): the SAME per-cluster scan + cluster selection the design
//      view uses (drop the whole-part cluster + sub-threshold clusters, scan
//      each remaining cluster's own axis), NOT convex prisms — so the assembly
//      hull SHAPE matches the single-design view.
// Bakes each solid mesh's transform into its vertices, normalises attributes to
// position+normal / non-indexed, and merges into ONE BufferGeometry.  ALSO builds
// the overhang FACE MARKERS (vertex-coloured quads, same radial raycast as the
// design view) in SOURCE-LOCAL space so they instance alongside the hull.
// Returns { solid, markers } — each a BufferGeometry the caller owns, or null
// (no edge LineSegments: the boxes themselves stay "solid bodies only").
//
// EXPORTED so the assembly connector-define surface (assembly_joint_renderer.js)
// can reuse these exact bounds as its click target — the surface you place a
// connector on then matches the rendered Hull Prism, instead of the old coarse
// convex bundle prism.  Pass source-local `nucleotides` + a source-local
// helix-axes map ({helixId:{start,end,samples,ovhgAxes}}); the caller bakes the
// instance world transform into the returned `solid`.
export function _hullGeoForSource(design, nucleotides, helixAxes, { forceLegacy = false } = {}) {
  if (!design) return null

  // Shared inputs for every hull branch AND the markers (mirror _rebuildHullRepr):
  // dsDNA-trimmed axes, per-helix dsDNA bp, and the render-cluster set with the
  // whole-part cluster (is_default OR >=90% of helices) dropped.
  const scanAxes = dsTrimmedAxes(nucleotides, helixAxes ?? null)
  const { helixBp, totalBp } = dsBpByHelix(nucleotides)
  const totalHelices = (design.helices ?? []).length
  const isWholePart = c => c.is_default
    || (totalHelices > 0 && (c.helix_ids?.length ?? 0) >= 0.9 * totalHelices)
  const allClusters = design.cluster_transforms ?? []
  const finer = allClusters.filter(c => !isWholePart(c))
  const renderClusters = finer.length ? finer : allClusters
  const dsHelices = new Set(helixBp.keys())
  const clusteredHelices = new Set()
  for (const cluster of renderClusters) {
    for (const hid of cluster.helix_ids ?? []) if (dsHelices.has(hid)) clusteredHelices.add(hid)
  }
  const clustersComplete = dsHelices.size === 0 || clusteredHelices.size / dsHelices.size >= 0.9
  const clustersToRender = allClusters.length && clustersComplete
    ? renderClusters
    : [{ id: '__current_geometry__', name: design.metadata?.name || 'Part', helix_ids: [...dsHelices] }]
  const fractionOf = (c) => {
    if (totalBp <= 0) return 1
    let bp = 0
    for (const hid of (c.helix_ids ?? [])) bp += (helixBp.get(hid) ?? 0)
    return bp / totalBp
  }

  const disposables = []   // builder geom+mat to dispose after baking
  const solids = []        // { geometry, m } to bake + merge
  const hullMeshObjs = []  // live Mesh objects, for the overhang-marker raycast
  const collect = (root) => {
    root.updateMatrixWorld(true)
    root.traverse(o => {
      if (o.isMesh && o.geometry) {
        solids.push({ geometry: o.geometry, m: o.matrixWorld.clone() })
        hullMeshObjs.push(o)
      }
      if (o.geometry) disposables.push(o.geometry)
      if (o.material) {
        const mats = Array.isArray(o.material) ? o.material : [o.material]
        for (const mm of mats) disposables.push(mm)
      }
    })
  }

  // Pass the source's deformed helixAxes (carries .samples) + curve tol so a bent
  // part's extrusion boxes sweep along its spine here too (parity with the design
  // view). Non-deformed sources (no samples) build straight boxes as before.
  // When the part has a moved cluster (a rigidly-displaced arm, no bend → straight
  // boxes that would otherwise ignore it), pass the clusters so each sub-box gets
  // its owning cluster's transform baked in. Merged into ONE source hull (the part
  // is a single instance — no per-cluster keying). Omitted when nothing moved, so
  // the common case is byte-identical to before. (Swept boxes already carry the
  // transform in their samples and are left untouched.)
  const clusterMoved = (c) => {
    const T = c.translation || [0, 0, 0], R = c.rotation || [0, 0, 0, 1]
    return Math.abs(T[0]) > 1e-9 || Math.abs(T[1]) > 1e-9 || Math.abs(T[2]) > 1e-9 ||
           Math.abs(R[0]) > 1e-9 || Math.abs(R[1]) > 1e-9 || Math.abs(R[2]) > 1e-9 || Math.abs(R[3] - 1) > 1e-9
  }
  const hullOpts = {
    clusters: allClusters.some(clusterMoved) ? allClusters : [],
    dsBpRange: dsBpRangeByHelix(nucleotides),
  }
  let grp = !forceLegacy && usesOccupancyHull(design)
    ? buildClusteredOccupancyHull(design, nucleotides, helixAxes, HULL_CURVE_TOL_NM)
    : buildExtrusionBoxes(design, helixAxes ?? null, HULL_CURVE_TOL_NM, hullOpts)  // 1. native extrusion boxes
  if (!grp && !allClusters.length) {                          // 2. scan (no clusters)
    grp = scanExtrusionGroup(
      (design.helices ?? []).map(h => h.id),
      scanAxes, helixBp, design.lattice_type, design.metadata?.name, null,
    )
  }
  if (grp) {
    collect(grp)
  } else if (helixAxes) {
    // 3. Per-cluster dsDNA cross-section scan — mirror _rebuildHullRepr (NOT
    //    convex prisms): drop clusters under HULL_MIN_SIZE_FRACTION of dsDNA bp,
    //    scan each remaining cluster on its own axis.
    const tmp = new THREE.Group()
    for (const cluster of clustersToRender) {
      if (fractionOf(cluster) < HULL_MIN_SIZE_FRACTION) continue
      const cg = scanExtrusionGroup(
        cluster.helix_ids, scanAxes, helixBp, design.lattice_type, cluster.name, null,
      )
      if (cg) tmp.add(cg)
    }
    collect(tmp)
  }

  if (!solids.length) {
    // No extrusion / scan / cluster hull — fall back to a single AABB over the
    // nucleotides so the part still has a coarse solid for the far-LOD bucket.
    // Push it through the SAME bake + marker path (raycast onto this box) below.
    const bboxGeo = _bboxSolidFromNucs(nucleotides)
    if (!bboxGeo) {
      for (const d of disposables) d.dispose?.()
      return null
    }
    const bboxMesh = new THREE.Mesh(bboxGeo, new THREE.MeshBasicMaterial())
    bboxMesh.updateMatrixWorld(true)
    solids.push({ geometry: bboxGeo, m: bboxMesh.matrixWorld.clone() })
    hullMeshObjs.push(bboxMesh)
    disposables.push(bboxGeo, bboxMesh.material)
  }

  // ── Solid hull geometry (baked + merged) ──
  const baked = []
  for (const s of solids) {
    let g = s.geometry.clone()
    g.applyMatrix4(s.m)
    g = g.toNonIndexed()
    for (const name of Object.keys(g.attributes)) {
      if (name !== 'position' && name !== 'normal') g.deleteAttribute(name)
    }
    if (!g.attributes.normal) g.computeVertexNormals()
    baked.push(g)
  }
  const solid = mergeGeometries(baked, false)
  baked.forEach(g => g.dispose())

  // ── Overhang face markers (source-local; instanced like the hull solid) ──
  // Same builder + radial raycast as the design view, cast onto the still-alive
  // SOURCE-LOCAL hull meshes — so the merged vertex-coloured quad geometry is
  // source-local and _buildMarkerLodMesh can instance it across every copy.
  let markers = null
  if (hullMeshObjs.length && design.overhangs?.length) {
    const markerClusters = renderClusters.length
      ? renderClusters
      : [{ helix_ids: (design.helices ?? []).map(h => h.id) }]
    const mGroup = buildOverhangMarkers(design, scanAxes, markerClusters, nucleotides, helixBp, hullMeshObjs)
    if (mGroup) {
      mGroup.updateMatrixWorld(true)
      const mGeos = []
      mGroup.traverse(o => {
        if (o.isMesh && o.geometry) {
          let g = o.geometry.clone()
          g.applyMatrix4(o.matrixWorld)
          g = g.toNonIndexed()
          for (const name of Object.keys(g.attributes)) {
            if (name !== 'position' && name !== 'color') g.deleteAttribute(name)
          }
          mGeos.push(g)
        }
        o.geometry?.dispose()
        if (o.material) {
          const mm = Array.isArray(o.material) ? o.material : [o.material]
          for (const x of mm) x.dispose?.()
        }
      })
      if (mGeos.length) {
        markers = mergeGeometries(mGeos, false)
        mGeos.forEach(g => g.dispose())
      }
    }
  }

  for (const d of disposables) d.dispose?.()
  return { solid: solid || null, markers: markers || null }
}
