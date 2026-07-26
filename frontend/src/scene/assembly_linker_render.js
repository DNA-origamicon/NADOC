/**
 * Cross-part linker rendering for the assembly view — the `__lnk__` bridge
 * duplexes between bound overhangs, plus the white connector arcs that close the
 * visible gap at each strand junction.
 *
 * Extracted verbatim from assembly_renderer.js, where BOTH render paths (legacy
 * per-instance and shared-instancing) already shared `_rebuildLinkerHelices`.
 * Linkers are few and per-connection, so they are drawn as ordinary meshes in a
 * dedicated group — no instancing on either path.
 *
 * One reason to change: how cross-part linkers are drawn.
 */
import * as THREE from 'three'
import { buildHelixObjects, CG_LOD } from './helix_renderer.js'
import { assemblyConnectorArcEndpoints } from './assembly_connector_arcs.js'

// ── Cross-part ds linker connector arcs ───────────────────────────────────
// Port of the per-design overhang_link_arcs.js connector arcs to the assembly
// view: a white tube from each ds linker strand's complement-domain end to its
// bridge-domain end (the cross-helix strand junction between the overhang
// binding domain on a part and the native-length __lnk__ bridge duplex). This
// closes the visible gap when parts aren't relaxed into a continuous duplex.
// buildHelixObjects (used for the linker helices) does NOT draw cross-helix
// junctions, so without this the gap is unbridged. Purely topological
// (domain[i].end ↔ domain[i+1].start) — no bp/direction reasoning. ds side
// strands only (`__lnk__<conn>__a` / `__b`); ss linkers render as their own
// bead chain in the design view and are not ported here.
const _LNK_ARC_RADIUS = 0.065   // nm — matches DS_ARC_RADIUS in overhang_link_arcs.js
const _LNK_ARC_SEGS   = 32

function _lnkCssToHex(css) {
  return (typeof css === 'string' && /^#[0-9a-fA-F]{6}$/.test(css)) ? parseInt(css.slice(1), 16) : null
}

function _lnkConnectorArc(a, b, color) {
  const chord = b.clone().sub(a)
  const len = chord.length() || 1
  let bow = chord.clone().cross(new THREE.Vector3(0, 0, 1))
  if (bow.lengthSq() < 1e-6) bow = chord.clone().cross(new THREE.Vector3(1, 0, 0))
  bow.normalize().multiplyScalar(len * 0.25)
  const ctrl = a.clone().add(b).multiplyScalar(0.5).add(bow)
  const mesh = new THREE.Mesh(
    new THREE.TubeGeometry(new THREE.QuadraticBezierCurve3(a, ctrl, b), _LNK_ARC_SEGS, _LNK_ARC_RADIUS, 8, false),
    new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.85 }),
  )
  mesh.name = 'assemblyDsConnectorArc'
  return mesh
}

// Connector arcs for every cross-part linker strand, at each backbone jump
// between domains on different helices: the complement↔bridge junction of a ds
// (`__a`/`__b`) or length>0 ss (`__s`) linker, AND the direct complement↔
// complement jump of a zero-length indirect ss linker. The endpoint math lives
// in the pure, unit-tested `assemblyConnectorArcEndpoints`; here we just turn
// each endpoint pair into a tube mesh tagged with its connection id (for
// right-click → relax/delete picking). `nucs` are world-space (from
// /assembly/linker-geometry).
function _buildAssemblyConnectorArcs(linkerStrands, nucs) {
  const arcs = []
  for (const e of assemblyConnectorArcEndpoints(linkerStrands, nucs)) {
    const a = new THREE.Vector3(e.a[0], e.a[1], e.a[2])
    const b = new THREE.Vector3(e.b[0], e.b[1], e.b[2])
    const arc = _lnkConnectorArc(a, b, _lnkCssToHex(e.colorCss) ?? 0xffffff)
    arc.userData.connId = e.connId
    arcs.push(arc)
  }
  return arcs
}

/**
 * Build the cross-part linker helix meshes (complement beads + virtual __lnk__
 * bridge) into `linkerGroup` from `GET /assembly/linker-geometry`. Module-level
 * so BOTH the legacy and shared instancing renderers can reuse it — linkers are
 * O(few) per overhang-connection (not per-bp instanced), so a plain dedicated
 * group is the cheapest correct representation on either path.
 *
 * Clears the group first (disposing non-shared geometry/materials). Does NOT
 * draw the `__vsc__` virtual-scaffold dashed lines — those need per-instance
 * world-axis caches that only the legacy path populates; the legacy
 * `rebuildLinkers` adds them after calling this.
 */
export async function _rebuildLinkerHelices({ assembly, api, linkerGroup, axesToMap }) {
  linkerGroup.traverse(obj => {
    // Skip module-level template geometries shared across instances.
    if (obj.geometry && !obj.geometry.userData?.shared) obj.geometry.dispose()
    if (obj.material) {
      const mats = Array.isArray(obj.material) ? obj.material : [obj.material]
      mats.forEach(m => m.dispose())
    }
  })
  while (linkerGroup.children.length) linkerGroup.remove(linkerGroup.children[0])
  linkerGroup.userData.linkerNucs = []   // world-space [{connId, pos}] for right-click → relax picking

  if (!assembly) return

  // Cross-part linker strands reference world-space alias helices keyed by
  // '<instance_id>::<original_helix_id>'; the backend returns them in
  // `aliased_helices` so the synthetic design used by buildHelixObjects can
  // resolve those domain.helix_id lookups.
  const linkerHelices = assembly.assembly_helices ?? []
  const linkerStrands = assembly.assembly_strands ?? []
  if (linkerHelices.length === 0 && linkerStrands.length === 0) return

  let geoData = null
  try { geoData = await api.getLinkerGeometry() } catch (_) {}
  if (!geoData?.nucleotides?.length) return

  const syntheticDesign = {
    helices:    [...linkerHelices, ...(geoData.aliased_helices ?? [])],
    strands:    linkerStrands,
    crossovers: [],
    lattice_type: 'honeycomb',
  }
  // Linkers are cross-part, so follow the DEEPEST representation any part uses
  // (full=0 > beads=1 > cylinders=2 — lower CG_LOD = more detail). This stops
  // a cylinders part from pinning every linker to a cylinder that then bleeds
  // over a part the user set to Full (covering its bead/slab model at the
  // junction). Was: the FIRST instance's rep, which lost to whatever came first
  // in the array. Non-CG reprs (hull-prism / atomistic) are ignored; if no part
  // is a CG rep, fall back to cylinders — linkers are tiny, a cylinder reads
  // cleanly. buildHelixObjects must be built at this LOD and then told to show
  // it (its meshes start hidden until setDetailLevel).
  let _linkerLod = 2
  let _sawCgRep = false
  for (const inst of assembly.instances ?? []) {
    const l = CG_LOD[inst.representation]
    if (l === undefined) continue
    _linkerLod = _sawCgRep ? Math.min(_linkerLod, l) : l
    _sawCgRep = true
  }
  const _linkerRepr = _linkerLod === 1 ? 'beads' : _linkerLod === 0 ? 'full' : 'cylinders'
  const linkerHelixCtrl = buildHelixObjects(
    geoData.nucleotides, syntheticDesign, linkerGroup, {}, [],
    axesToMap(geoData.helix_axes), _linkerRepr,
  )
  linkerHelixCtrl?.setDetailLevel?.(_linkerLod)
  linkerGroup.userData.helixCtrl = linkerHelixCtrl

  // Connector arcs: bridge the complement↔bridge domain junction of each ds
  // linker strand (same visual as the per-design overhang_link_arcs.js).
  for (const arc of _buildAssemblyConnectorArcs(linkerStrands, geoData.nucleotides)) {
    linkerGroup.add(arc)
  }

  // Stash world-space linker nuc positions tagged by connection id so a
  // right-click on any linker mesh (complement / bridge beads — which carry no
  // per-conn userData) resolves to its connection via nearest-nuc.
  const linkerNucs = []
  for (const n of geoData.nucleotides ?? []) {
    const sid = n.strand_id ?? ''
    if (!/^__lnk__.+__(a|b|s)$/.test(sid)) continue
    const p = n.backbone_position ?? n.base_position
    if (!p) continue
    linkerNucs.push({ connId: sid.replace(/^__lnk__/, '').replace(/__(a|b|s)$/, ''), pos: [p[0], p[1], p[2]] })
  }
  linkerGroup.userData.linkerNucs = linkerNucs
}
