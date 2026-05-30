/**
 * Strand-animation DRIVER for a real overhang + its binder strand.
 *
 * Display-only un/hybridization of the ACTUAL rendered beads, decomposed about
 * the overhang's real HELIX AXIS (cylinder axis). As the binder unbinds:
 *  - the OVERHANG unwinds in place: every bead keeps its radius R from the
 *    helix axis and its axial position, but its azimuth lerps toward the ROOT
 *    bead's angle → it settles into a straight line parallel to the axis at
 *    radius R (the spiral relaxes; it does NOT fly away).
 *  - the BINDER drifts radially OUTWARD: each freed bead's radius grows from R
 *    to R+drift along its own radial direction (azimuth + axial preserved).
 * Both are gated by a melt fork that travels free-tip → root as φ: 1 → 0. The
 * fork is fully-paired at φ=1 (every bead at its authored position — no jump on
 * play start/stop) and fully-freed at φ=0.
 *
 * Three-Layer Law: pure display. Reads geometry + the helix axis; writes only
 * transient bead/slab matrices via `helixCtrl.setBeadOverrides`; restores
 * authored positions on clear().
 *
 * Wiring:
 *   const driver = initOverhangStrandAnim({ getHelixCtrl, getGeometry, getDesign })
 *   driver.bind(overhangId, binderStrandId)   // capture axis frame + anchors
 *   driver.setPhi(phi, paramsSnapshot)         // per-frame (ticker hot path)
 *   driver.clear()                             // restore beads, drop capture
 */

import * as THREE from 'three'
import { createStrandRenderer } from '../strand-anim/strand_renderer.js'

const TWO_PI = Math.PI * 2
/** shortest signed angle a→b in (−π, π] */
function _angDiff(a, b) { let d = (b - a) % TWO_PI; if (d > Math.PI) d -= TWO_PI; if (d < -Math.PI) d += TWO_PI; return d }

/** Binder strand id bound to an overhang (oh_binder first, then any complement). */
export function findBinderStrand(design, overhangId) {
  if (!design || !overhangId) return null
  const byType = design.strands?.find(s => s.strand_type === 'oh_binder'
    && s.domains?.some(d => d.binds_overhang_id === overhangId))
  if (byType) return byType.id
  const any = design.strands?.find(s => s.domains?.some(d => d.binds_overhang_id === overhangId))
  return any?.id ?? null
}

export function initOverhangStrandAnim({ getHelixCtrl, getGeometry, getDesign, getScene }) {
  let _bound = null          // capture (see bind())
  let _movedKeys = new Set()
  let _lastGeometry = null
  let _invader = null        // synthetic invader strand renderer (lazy, TMSD mode)

  // scratch (no per-frame allocation)
  const _A0 = new THREE.Vector3(), _Adir = new THREE.Vector3()
  const _U = new THREE.Vector3(), _V = new THREE.Vector3()
  const _P = new THREE.Vector3(), _rad = new THREE.Vector3(), _ax = new THREE.Vector3()
  const _WX = new THREE.Vector3(1, 0, 0), _WY = new THREE.Vector3(0, 1, 0)
  // frame-slerp scratch (invader slab orientation: direct shortest path, no
  // orthogonalization-singularity swings between bound/unbound).
  const _qa = new THREE.Quaternion(), _qb = new THREE.Quaternion(), _mm = new THREE.Matrix4()
  const _st = new THREE.Vector3(), _sn = new THREE.Vector3(), _sc = new THREE.Vector3()
  function _frameQuat(tx, ty, tz, nx, ny, nz, out) {       // orthonormal slab frame → quat
    _st.set(tx, ty, tz); const tl = _st.length() || 1; _st.divideScalar(tl)
    _sn.set(nx, ny, nz); _sn.addScaledVector(_st, -_sn.dot(_st))
    const nl = _sn.length(); if (nl < 1e-6) { _sn.set(0, 0, 1).addScaledVector(_st, -_st.z); _sn.normalize() } else _sn.divideScalar(nl)
    _sc.crossVectors(_st, _sn).normalize()
    _mm.makeBasis(_sc, _st, _sn); out.setFromRotationMatrix(_mm)
  }
  /** Slerp the slab frame from (bt,bn) to (ft,fn) by t∈[0,1] → tanArr/bnArr at o. */
  function _slerpFrame(bt, bn, ft, fn, t, tanArr, bnArr, o) {
    _frameQuat(bt[0], bt[1], bt[2], bn[0], bn[1], bn[2], _qa)
    _frameQuat(ft[0], ft[1], ft[2], fn[0], fn[1], fn[2], _qb)
    _qa.slerp(_qb, t)
    _mm.makeRotationFromQuaternion(_qa)
    const e = _mm.elements
    tanArr[o] = e[4]; tanArr[o + 1] = e[5]; tanArr[o + 2] = e[6]   // column 1 = tangent
    bnArr[o] = e[8]; bnArr[o + 1] = e[9]; bnArr[o + 2] = e[10]     // column 2 = base-normal
  }

  const _key = (n) => `${n.helix_id}:${n.bp_index}:${n.direction}`
  const _v3 = (a, out) => out.set(a[0] ?? a.x, a[1] ?? a.y, a[2] ?? a.z)

  function _overhangNucs(geometry, ohId) {
    return geometry.filter(n => n.overhang_id === ohId).sort((a, b) => a.bp_index - b.bp_index)
  }

  /** Decompose world point P about the axis → {axisPt(into _ax), R, theta, rhat(into _rad)}. */
  function _decompose(posArr) {
    _v3(posArr, _P)
    const t = _P.clone().sub(_A0).dot(_Adir)
    _ax.copy(_A0).addScaledVector(_Adir, t)          // axis point (closest)
    _rad.copy(_P).sub(_ax)                            // radial vector
    const R = _rad.length()
    const theta = Math.atan2(_rad.dot(_V), _rad.dot(_U))
    if (R > 1e-9) _rad.multiplyScalar(1 / R)         // _rad now = rhat
    return { t, R, theta }
  }

  /**
   * Capture the helix-axis frame + authored anchors for an (overhang, binder) pair.
   * @returns {{ok:boolean, reason?:string, N?:number, R?:number}}
   */
  function bind(overhangId, binderStrandId) {
    clear()
    const geometry = getGeometry?.()
    const design = getDesign?.()
    if (!geometry) return { ok: false, reason: 'no geometry' }
    _lastGeometry = geometry

    let oh = _overhangNucs(geometry, overhangId)
    if (oh.length < 2) return { ok: false, reason: 'overhang too short' }
    if (oh[0].is_five_prime || oh[0].is_three_prime) oh = oh.slice().reverse() // root at i=0
    const M = oh.length
    const ohHelix = oh[0].helix_id

    // Binder beads on the overhang helix (ANY length). Pair to overhang beads by
    // bp_index where they overlap — overhang & binder may differ in length.
    const ohBpToIdx = new Map(); oh.forEach((n, i) => ohBpToIdx.set(n.bp_index, i))
    const binderNucs = geometry
      .filter(n => n.strand_id === binderStrandId && n.helix_id === ohHelix)
      .sort((a, b) => a.bp_index - b.bp_index)
    if (!binderNucs.length) return { ok: false, reason: 'no binder beads on the overhang helix' }
    const bnToOh = binderNucs.map(n => (ohBpToIdx.has(n.bp_index) ? ohBpToIdx.get(n.bp_index) : -1))
    if (!bnToOh.some(x => x >= 0)) return { ok: false, reason: 'binder does not overlap the overhang' }
    const Mb = binderNucs.length

    // Helix axis (cylinder axis). Prefer the helix's stored axis; fall back to
    // the overhang bead root→tip line.
    const helix = design?.helices?.find(h => h.id === ohHelix)
    if (helix?.axis_start && helix?.axis_end) {
      _v3(helix.axis_start, _A0)
      _v3(helix.axis_end, _Adir).sub(_A0)
    } else {
      _v3(oh[0].backbone_position, _A0)
      _v3(oh[M - 1].backbone_position, _Adir).sub(_A0)
    }
    if (_Adir.lengthSq() < 1e-12) _v3(oh[0].axis_tangent, _Adir)
    _Adir.normalize()
    // perpendicular frame (U, V) ⟂ Adir for azimuth
    _U.copy(_WX).addScaledVector(_Adir, -_WX.dot(_Adir))
    if (_U.lengthSq() < 1e-9) _U.copy(_WY).addScaledVector(_Adir, -_WY.dot(_Adir))
    _U.normalize()
    _V.copy(_Adir).cross(_U).normalize()

    // per-bead decomposition → cached arrays (axisPt, radius, azimuth). Slab
    // base-normals are cached in the axis frame (U,V,Adir components) so the
    // paired region's slabs can be rotated by the unwind angle each frame.
    const ohAxis = new Float32Array(M * 3), ohR = new Float32Array(M), ohTheta = new Float32Array(M), ohBnUVA = new Float32Array(M * 3)
    const bnAxis = new Float32Array(Mb * 3), bnR = new Float32Array(Mb), bnTheta = new Float32Array(Mb), bnBnUVA = new Float32Array(Mb * 3)
    const _uva = (v, out, k) => { out[k] = v[0] * _U.x + v[1] * _U.y + v[2] * _U.z;
      out[k + 1] = v[0] * _V.x + v[1] * _V.y + v[2] * _V.z;
      out[k + 2] = v[0] * _Adir.x + v[1] * _Adir.y + v[2] * _Adir.z }
    let rSum = 0
    for (let i = 0; i < M; i++) {
      const d = _decompose(oh[i].backbone_position)
      ohAxis[i * 3] = _ax.x; ohAxis[i * 3 + 1] = _ax.y; ohAxis[i * 3 + 2] = _ax.z
      ohR[i] = d.R; ohTheta[i] = d.theta; rSum += d.R
      _uva(oh[i].base_normal ?? [0, 0, 0], ohBnUVA, i * 3)
    }
    for (let k = 0; k < Mb; k++) {
      const d = _decompose(binderNucs[k].backbone_position)
      bnAxis[k * 3] = _ax.x; bnAxis[k * 3 + 1] = _ax.y; bnAxis[k * 3 + 2] = _ax.z
      bnR[k] = d.R; bnTheta[k] = d.theta
      _uva(binderNucs[k].base_normal ?? [0, 0, 0], bnBnUVA, k * 3)
    }
    // mean helix twist + axial rise from the OVERHANG (the fork is in overhang bp).
    let twist = 0
    for (let i = 0; i < M - 1; i++) twist += _angDiff(ohTheta[i], ohTheta[i + 1])
    twist = M > 1 ? twist / (M - 1) : 0
    let riseSum = 0
    for (let i = 0; i < M - 1; i++) {
      const a = i * 3, c = (i + 1) * 3
      riseSum += Math.hypot(ohAxis[c] - ohAxis[a], ohAxis[c + 1] - ohAxis[a + 1], ohAxis[c + 2] - ohAxis[a + 2])
    }
    const meanRise = M > 1 ? riseSum / (M - 1) : 0.334
    // mean cross-strand distance (duplex width) — the straight-ladder rail gap.
    let wSum = 0, wCnt = 0
    for (let k = 0; k < Mb; k++) {
      const oj = bnToOh[k]; if (oj < 0) continue
      const op = oh[oj].backbone_position, bp = binderNucs[k].backbone_position
      wSum += Math.hypot(op[0] - bp[0], op[1] - bp[1], op[2] - bp[2]); wCnt++
    }
    const meanW = wCnt > 0 ? wSum / wCnt : (M > 0 ? 2 * rSum / M : 2)

    // Toehold (TMSD): overhang indices NOT covered by the binder. The branch-
    // migration front sweeps from the toehold inward (displacement coordinate d).
    const covered = new Array(M).fill(false)
    for (const oj of bnToOh) if (oj >= 0) covered[oj] = true
    const toeholdIdx = [], coveredIdx = []
    for (let j = 0; j < M; j++) (covered[j] ? coveredIdx : toeholdIdx).push(j)
    const hasToehold = toeholdIdx.length > 0 && coveredIdx.length > 0
    const dOf = new Float32Array(M)
    let grooveOffset = Math.PI, toeholdAtTip = true
    if (hasToehold) {
      const meanToe = toeholdIdx.reduce((a, b) => a + b, 0) / toeholdIdx.length
      const meanCov = coveredIdx.reduce((a, b) => a + b, 0) / coveredIdx.length
      toeholdAtTip = meanToe > meanCov
      for (let j = 0; j < M; j++) dOf[j] = toeholdAtTip ? (M - 1 - j) : j
      let gs = 0, gc = 0
      for (let k = 0; k < Mb; k++) { const oj = bnToOh[k]; if (oj >= 0) { gs += _angDiff(ohTheta[oj], bnTheta[k]); gc++ } }
      grooveOffset = gc > 0 ? gs / gc : Math.PI
    }
    if (!_invader) { const sc = getScene?.(); if (sc) _invader = createStrandRenderer(sc, { roleColor: { invader: 0x3fb950 }, lineOpacity: 0.6 }) }

    _bound = {
      overhangId, binderStrandId, M, Mb, ohNucs: oh, binderNucs, bnToOh,
      Adir: _Adir.clone(), U: _U.clone(), V: _V.clone(),
      ohAxis, ohR, ohTheta, ohBnUVA, thetaRoot: ohTheta[0],
      bnAxis, bnR, bnTheta, bnBnUVA, twist, meanRise, meanW, bnRootTheta: bnTheta[0], bnRootR: bnR[0],
      hasToehold, dOf, grooveOffset, toeholdAtTip,
    }
    return { ok: true, N: M, R: rSum / M, hasToehold }
  }

  /** Drive the beads to φ. `params` = the panel's param snapshot. Hot path. */
  function setPhi(phi, params) {
    const helixCtrl = getHelixCtrl?.()
    if (!_bound || !helixCtrl?.setBeadOverrides) return
    const straight = params?.form === 'straight'
    if (params?.mode === 'displacement' && _bound.hasToehold) {
      if (straight) _displacementStraight(phi, params, helixCtrl)
      else _displacement(phi, params, helixCtrl)
      return
    }
    if (_invader) _invader.update([])           // unzip mode: hide the invader
    if (straight) { _unzipStraight(phi, params, helixCtrl); return }
    const b = _bound, M = b.M, U = b.U, V = b.V
    const meltBp = params?.meltBp ?? 0
    const unwindScale = params?.unwindScale ?? 1.0
    const thetaDeg = params?.thetaDeg ?? 30
    const armPull = params?.armPull ?? 1.0
    const meltSafe = Math.max(meltBp, 1e-6)
    // Fork travels root(0) → tip(M) as φ: 1 → 0. Fully paired (w=0 ∀i) at φ=1,
    // fully freed (w=1 ∀i) at φ=0. Freed = root side. The −0.5 keeps the fork
    // strictly below the root at φ=1 even with meltBp=0 (hard step).
    const forkPos = (1 - phi) * (M + meltBp) - meltBp / 2 - 0.5
    const freedCount = Math.max(0, Math.min(M, forkPos))
    // still-paired remainder rotates about the axis as the helix unwinds.
    const dTheta = -unwindScale * freedCount * b.twist
    const _sstep = (t) => { t = t < 0 ? 0 : t > 1 ? 1 : t; return t * t * (3 - 2 * t) }

    // Binder freed straight arm: emanates from the fork, leaning toward the root
    // (−Adir) and outward (bref) at the splay angle. Same straight line for every
    // freed bead → a single ssDNA arm like the sandbox.
    const thRad = thetaDeg * Math.PI / 180
    // azimuthal departure plane: binder root angle + adjustable exit angle.
    const exitRad = ((params?.exitAngleDeg ?? 0) * Math.PI / 180) + b.bnRootTheta
    const brefX = Math.cos(exitRad) * U.x + Math.sin(exitRad) * V.x
    const brefY = Math.cos(exitRad) * U.y + Math.sin(exitRad) * V.y
    const brefZ = Math.cos(exitRad) * U.z + Math.sin(exitRad) * V.z
    const armStep = b.meanRise * armPull
    const fp = Math.max(0, Math.min(M - 1, forkPos))
    const f0 = Math.floor(fp), f1 = Math.min(M - 1, f0 + 1), ft = fp - f0
    const faxX = b.bnAxis[f0 * 3] * (1 - ft) + b.bnAxis[f1 * 3] * ft
    const faxY = b.bnAxis[f0 * 3 + 1] * (1 - ft) + b.bnAxis[f1 * 3 + 1] * ft
    const faxZ = b.bnAxis[f0 * 3 + 2] * (1 - ft) + b.bnAxis[f1 * 3 + 2] * ft
    const pfX = faxX + b.bnRootR * brefX, pfY = faxY + b.bnRootR * brefY, pfZ = faxZ + b.bnRootR * brefZ
    let adX = -Math.cos(thRad) * b.Adir.x + Math.sin(thRad) * brefX
    let adY = -Math.cos(thRad) * b.Adir.y + Math.sin(thRad) * brefY
    let adZ = -Math.cos(thRad) * b.Adir.z + Math.sin(thRad) * brefZ
    const adl = Math.hypot(adX, adY, adZ) || 1; adX /= adl; adY /= adl; adZ /= adl
    const Adir = b.Adir
    // freed binder slab: a single uniform direction 90° from the splay/arm, in the
    // arm plane (sinθ·Adir + cosθ·bref). All freed binder slabs share this.
    const pdX = Math.sin(thRad) * Adir.x + Math.cos(thRad) * brefX
    const pdY = Math.sin(thRad) * Adir.y + Math.cos(thRad) * brefY
    const pdZ = Math.sin(thRad) * Adir.z + Math.cos(thRad) * brefZ
    const cosD = Math.cos(dTheta), sinD = Math.sin(dTheta)   // paired-slab unwind rotation

    const updates = []
    const nowKeys = new Set()
    for (let i = 0; i < M; i++) {
      const o = i * 3
      const w = _sstep((forkPos - i) / meltSafe + 0.5)   // 0 paired (ahead) .. 1 freed (behind)
      // overhang azimuth: paired → authored+dTheta (rotates); freed → root angle (fixed).
      const pairedTh = b.ohTheta[i] + dTheta
      const th = pairedTh + w * _angDiff(pairedTh, b.thetaRoot)
      const cR = b.ohR[i], c = Math.cos(th), s = Math.sin(th)
      const rhx = c * U.x + s * V.x, rhy = c * U.y + s * V.y, rhz = c * U.z + s * V.z
      const ox = b.ohAxis[o] + cR * rhx
      const oy = b.ohAxis[o + 1] + cR * rhy
      const oz = b.ohAxis[o + 2] + cR * rhz
      // slab: paired = authored base-normal rotated by dTheta (tracks the
      // unwinding duplex); freed = inward −rhat (toward axis). Blend by w.
      const oU = b.ohBnUVA[o], oV = b.ohBnUVA[o + 1], oA = b.ohBnUVA[o + 2]
      const opu = oU * cosD - oV * sinD, opv = oU * sinD + oV * cosD
      let nbx = (opu * U.x + opv * V.x + oA * Adir.x) * (1 - w) - rhx * w
      let nby = (opu * U.y + opv * V.y + oA * Adir.y) * (1 - w) - rhy * w
      let nbz = (opu * U.z + opv * V.z + oA * Adir.z) * (1 - w) - rhz * w
      const nl = Math.hypot(nbx, nby, nbz) || 1; nbx /= nl; nby /= nl; nbz /= nl
      const on = b.ohNucs[i]
      updates.push({ helix_id: on.helix_id, bp_index: on.bp_index, direction: on.direction,
        backbone_position: [ox, oy, oz], nx: nbx, ny: nby, nz: nbz })
      nowKeys.add(_key(on))
    }
    // Binder beads (any length): each paired to an overhang index via bnToOh; its
    // fork progress w + arm arc-length use that overhang index. Unpaired binder
    // beads (no overhang partner) stay at their authored position.
    for (let bk = 0; bk < b.Mb; bk++) {
      const o = bk * 3
      const bn = b.binderNucs[bk]
      const oj = b.bnToOh[bk]
      if (oj < 0) {
        const ap = bn.backbone_position, an = bn.base_normal
        const u = { helix_id: bn.helix_id, bp_index: bn.bp_index, direction: bn.direction, backbone_position: [ap[0], ap[1], ap[2]] }
        if (an) { u.nx = an[0]; u.ny = an[1]; u.nz = an[2] }
        updates.push(u); nowKeys.add(_key(bn)); continue
      }
      const w = _sstep((forkPos - oj) / meltSafe + 0.5)
      // paired → authored position rotated by dTheta; freed → straight arm. Blend.
      const thB = b.bnTheta[bk] + dTheta
      const pcx = b.bnAxis[o] + b.bnR[bk] * (Math.cos(thB) * U.x + Math.sin(thB) * V.x)
      const pcy = b.bnAxis[o + 1] + b.bnR[bk] * (Math.cos(thB) * U.y + Math.sin(thB) * V.y)
      const pcz = b.bnAxis[o + 2] + b.bnR[bk] * (Math.cos(thB) * U.z + Math.sin(thB) * V.z)
      const sArm = (forkPos - oj) * armStep
      const fbx = pfX + sArm * adX, fby = pfY + sArm * adY, fbz = pfZ + sArm * adZ   // freed arm pos
      const bx = pcx * (1 - w) + fbx * w
      const by = pcy * (1 - w) + fby * w
      const bz = pcz * (1 - w) + fbz * w
      // slab: paired = authored rotated by dTheta; freed → uniform direction 90°
      // from the splay/arm (pdX, all aligned). Blend by w.
      const bU = b.bnBnUVA[o], bV = b.bnBnUVA[o + 1], bA = b.bnBnUVA[o + 2]
      const bpu = bU * cosD - bV * sinD, bpv = bU * sinD + bV * cosD
      let mbx = (bpu * U.x + bpv * V.x + bA * Adir.x) * (1 - w) + pdX * w
      let mby = (bpu * U.y + bpv * V.y + bA * Adir.y) * (1 - w) + pdY * w
      let mbz = (bpu * U.z + bpv * V.z + bA * Adir.z) * (1 - w) + pdZ * w
      const ml = Math.hypot(mbx, mby, mbz) || 1; mbx /= ml; mby /= ml; mbz /= ml
      updates.push({ helix_id: bn.helix_id, bp_index: bn.bp_index, direction: bn.direction,
        backbone_position: [bx, by, bz], nx: mbx, ny: mby, nz: mbz })
      nowKeys.add(_key(bn))
    }
    for (const key of _movedKeys) {
      if (nowKeys.has(key)) continue
      const u = _authoredUpdate(key, _lastGeometry)
      if (u) updates.push(u)
    }
    helixCtrl.setBeadOverrides(updates)
    _movedKeys = nowKeys
  }

  /**
   * Toehold-mediated strand displacement (TMSD). A synthetic invader (rendered
   * via the sandbox strand renderer) binds the toehold then branch-migrates,
   * displacing the real binder. The overhang (substrate) stays put. φ: 0 =
   * invader free + binder bound → 1 = invader bound + binder displaced.
   */
  function _displacement(phi, params, helixCtrl) {
    const b = _bound, M = b.M, U = b.U, V = b.V, Adir = b.Adir
    const meltBp = params?.meltBp ?? 0
    const meltSafe = Math.max(meltBp, 1e-6)
    // separate splay angles: displaced binder vs the synthetic invader.
    const thRadB = (params?.thetaDeg ?? 30) * Math.PI / 180
    const thRadI = (params?.invaderSplayDeg ?? params?.thetaDeg ?? 30) * Math.PI / 180
    const armStep = b.meanRise * (params?.armPull ?? 1.0)
    const exitRad = ((params?.exitAngleDeg ?? 0) * Math.PI / 180) + b.bnRootTheta
    const brefX = Math.cos(exitRad) * U.x + Math.sin(exitRad) * V.x
    const brefY = Math.cos(exitRad) * U.y + Math.sin(exitRad) * V.y
    const brefZ = Math.cos(exitRad) * U.z + Math.sin(exitRad) * V.z
    const _sstep = (t) => { t = t < 0 ? 0 : t > 1 ? 1 : t; return t * t * (3 - 2 * t) }
    // binding front in displacement coordinate d: φ=0 nothing bound, φ=1 all.
    const bf = phi * (M + meltBp) - meltBp / 2 - 0.5
    // the binder's displacement front LEADS the invader's binding front by `gap`
    // bp, so the binder vacates a position before the invader occupies it (no
    // clipping; the binder stays ahead of the invader).
    const gap = params?.dispGap ?? 1.0
    const bfB = bf + gap
    const cosI = Math.cos(thRadI), sinI = Math.sin(thRadI)   // invader splay
    const cosB = Math.cos(thRadB), sinB = Math.sin(thRadB)   // displaced binder splay
    const axSign = b.toeholdAtTip ? -1 : 1     // unit "+d" axial direction = axSign·Adir
    // two free tails splay in a Λ from the branch point: invader toward +d, the
    // displaced binder toward −d; both lean outward (bref).
    const _norm3 = (x, y, z) => { const l = Math.hypot(x, y, z) || 1; return [x / l, y / l, z / l] }
    const [aInvX, aInvY, aInvZ] = _norm3(axSign * cosI * Adir.x + sinI * brefX, axSign * cosI * Adir.y + sinI * brefY, axSign * cosI * Adir.z + sinI * brefZ)
    const [aBndX, aBndY, aBndZ] = _norm3(-axSign * cosB * Adir.x + sinB * brefX, -axSign * cosB * Adir.y + sinB * brefY, -axSign * cosB * Adir.z + sinB * brefZ)
    // displaced-binder slab → uniform direction 90° from its splay/arm (all aligned)
    const [pdBX, pdBY, pdBZ] = _norm3(sinB * Adir.x + axSign * cosB * brefX, sinB * Adir.y + axSign * cosB * brefY, sinB * Adir.z + axSign * cosB * brefZ)
    // invader free-slab base-normal: a SINGLE uniform inward direction (⟂ the arm's
    // axial part), so every fully-unbound invader slab lands on the same orientation.
    // (Per-bead _inwardAxis tilts near the branch → slabs look unfinished at φ=0.)
    const dotI = aInvX * Adir.x + aInvY * Adir.y + aInvZ * Adir.z
    const [uiX, uiY, uiZ] = _norm3(-(aInvX - dotI * Adir.x), -(aInvY - dotI * Adir.y), -(aInvZ - dotI * Adir.z))

    const _pairPos = (j, out) => {                 // antiparallel partner on the cylinder
      const ang = b.ohTheta[j] + b.grooveOffset, R = b.ohR[j], o = j * 3
      out[0] = b.ohAxis[o] + R * (Math.cos(ang) * U.x + Math.sin(ang) * V.x)
      out[1] = b.ohAxis[o + 1] + R * (Math.cos(ang) * U.y + Math.sin(ang) * V.y)
      out[2] = b.ohAxis[o + 2] + R * (Math.cos(ang) * U.z + Math.sin(ang) * V.z)
    }
    // invader branch-point anchor = paired position at d = bf; the binder's is
    // ahead at d = bfB (so the two Λ tails emanate from slightly offset points).
    const _frontAt = (dd, out) => {
      const j = Math.max(0, Math.min(M - 1, b.toeholdAtTip ? (M - 1 - dd) : dd))
      const j0 = Math.floor(j), j1 = Math.min(M - 1, j0 + 1), jt = j - j0
      const _pa = [0, 0, 0], _pb = [0, 0, 0]; _pairPos(j0, _pa); _pairPos(j1, _pb)
      out[0] = _pa[0] * (1 - jt) + _pb[0] * jt; out[1] = _pa[1] * (1 - jt) + _pb[1] * jt; out[2] = _pa[2] * (1 - jt) + _pb[2] * jt
    }
    const _fI = [0, 0, 0], _fB = [0, 0, 0]; _frontAt(bf, _fI); _frontAt(bfB, _fB)
    const fX = _fI[0], fY = _fI[1], fZ = _fI[2]
    const fbX = _fB[0], fbY = _fB[1], fbZ = _fB[2]

    // ── synthetic invader strand ───────────────────────────────────────────────
    const ipos = new Float32Array(M * 3), itan = new Float32Array(M * 3), ibn = new Float32Array(M * 3)
    const _bp = [0, 0, 0]
    for (let j = 0; j < M; j++) {
      const o = j * 3, d = b.dOf[j]
      const wj = _sstep((bf - d) / meltSafe + 0.5)  // 1 bound, 0 free
      _pairPos(j, _bp)
      const s = (d - bf) * armStep                  // free (d>bf) trails along +d arm
      const fx = fX + s * aInvX, fy = fY + s * aInvY, fz = fZ + s * aInvZ
      ipos[o] = _bp[0] * wj + fx * (1 - wj); ipos[o + 1] = _bp[1] * wj + fy * (1 - wj); ipos[o + 2] = _bp[2] * wj + fz * (1 - wj)
      const oo = j * 3
      const ox = b.ohAxis[oo] + b.ohR[j] * (Math.cos(b.ohTheta[j]) * U.x + Math.sin(b.ohTheta[j]) * V.x)
      const oy = b.ohAxis[oo + 1] + b.ohR[j] * (Math.cos(b.ohTheta[j]) * U.y + Math.sin(b.ohTheta[j]) * V.y)
      const oz = b.ohAxis[oo + 2] + b.ohR[j] * (Math.cos(b.ohTheta[j]) * U.z + Math.sin(b.ohTheta[j]) * V.z)
      // Slab frame SLERPs the shortest path from BOUND (tangent = axis, base-normal
      // = toward the overhang it pairs) to UNBOUND (tangent = backbone direction in
      // array order = axSign·arm, base-normal = toward axis). Using axSign·arm (not
      // the arm-extension direction) keeps the free tangent aligned with the bound
      // tangent — else the frame slerps ~180° about the normal.
      _slerpFrame([Adir.x, Adir.y, Adir.z], [ox - _bp[0], oy - _bp[1], oz - _bp[2]],
        [axSign * aInvX, axSign * aInvY, axSign * aInvZ], [uiX, uiY, uiZ], 1 - wj, itan, ibn, o)
    }
    if (_invader) _invader.update([{ pos: ipos, tan: itan, bn: ibn, role: 'invader' }])

    // ── displaced binder (real beads) ──────────────────────────────────────────
    const updates = []
    const nowKeys = new Set()
    for (let bk = 0; bk < b.Mb; bk++) {
      const o = bk * 3, bn = b.binderNucs[bk], oj = b.bnToOh[bk]
      if (oj < 0) {
        const ap = bn.backbone_position, an = bn.base_normal
        const u = { helix_id: bn.helix_id, bp_index: bn.bp_index, direction: bn.direction, backbone_position: [ap[0], ap[1], ap[2]] }
        if (an) { u.nx = an[0]; u.ny = an[1]; u.nz = an[2] }
        updates.push(u); nowKeys.add(_key(bn)); continue
      }
      const d = b.dOf[oj]
      const df = _sstep((bfB - d) / meltSafe + 0.5)  // leads invader by `gap`
      const pcx = b.bnAxis[o] + b.bnR[bk] * (Math.cos(b.bnTheta[bk]) * U.x + Math.sin(b.bnTheta[bk]) * V.x)
      const pcy = b.bnAxis[o + 1] + b.bnR[bk] * (Math.cos(b.bnTheta[bk]) * U.y + Math.sin(b.bnTheta[bk]) * V.y)
      const pcz = b.bnAxis[o + 2] + b.bnR[bk] * (Math.cos(b.bnTheta[bk]) * U.z + Math.sin(b.bnTheta[bk]) * V.z)
      const s = (bfB - d) * armStep                  // displaced (d<bfB) trails from binder front
      const dx = fbX + s * aBndX, dy = fbY + s * aBndY, dz = fbZ + s * aBndZ
      // slab: authored (paired) → uniform perpDir (freed) by displacement fraction df
      const an = bn.base_normal
      let mbx = (an ? an[0] : pdBX) * (1 - df) + pdBX * df
      let mby = (an ? an[1] : pdBY) * (1 - df) + pdBY * df
      let mbz = (an ? an[2] : pdBZ) * (1 - df) + pdBZ * df
      const ml = Math.hypot(mbx, mby, mbz) || 1; mbx /= ml; mby /= ml; mbz /= ml
      updates.push({ helix_id: bn.helix_id, bp_index: bn.bp_index, direction: bn.direction,
        backbone_position: [pcx * (1 - df) + dx * df, pcy * (1 - df) + dy * df, pcz * (1 - df) + dz * df],
        nx: mbx, ny: mby, nz: mbz })
      nowKeys.add(_key(bn))
    }
    // overhang substrate stays authored (not pushed). Restore any stale beads.
    for (const key of _movedKeys) {
      if (nowKeys.has(key)) continue
      const u = _authoredUpdate(key, _lastGeometry)
      if (u) updates.push(u)
    }
    helixCtrl.setBeadOverrides(updates)
    _movedKeys = nowKeys
  }

  /** Unit vector from a world point toward the helix axis (⟂ Adir). */
  function _inwardAxis(b, px, py, pz) {
    const d = b.Adir
    const qx = px - b.ohAxis[0], qy = py - b.ohAxis[1], qz = pz - b.ohAxis[2]
    const t = qx * d.x + qy * d.y + qz * d.z
    const rx = qx - t * d.x, ry = qy - t * d.y, rz = qz - t * d.z
    const l = Math.hypot(rx, ry, rz) || 1
    return [-rx / l, -ry / l, -rz / l]
  }

  // straight-form radial frames: each strand de-spirals into a straight line at
  // its OWN ROOT azimuth/radius, so the root backbone bead stays aligned with the
  // helix axis (unmoved) and the strand runs parallel to the axis from there.
  function _straightFrame(b, params) {
    const U = b.U, V = b.V
    const ohRx = Math.cos(b.thetaRoot) * U.x + Math.sin(b.thetaRoot) * V.x
    const ohRy = Math.cos(b.thetaRoot) * U.y + Math.sin(b.thetaRoot) * V.y
    const ohRz = Math.cos(b.thetaRoot) * U.z + Math.sin(b.thetaRoot) * V.z
    const bnRx = Math.cos(b.bnRootTheta) * U.x + Math.sin(b.bnRootTheta) * V.x
    const bnRy = Math.cos(b.bnRootTheta) * U.y + Math.sin(b.bnRootTheta) * V.y
    const bnRz = Math.cos(b.bnRootTheta) * U.z + Math.sin(b.bnRootTheta) * V.z
    const ex = ((params?.exitAngleDeg ?? 0) * Math.PI / 180) + b.bnRootTheta
    const brefX = Math.cos(ex) * U.x + Math.sin(ex) * V.x
    const brefY = Math.cos(ex) * U.y + Math.sin(ex) * V.y
    const brefZ = Math.cos(ex) * U.z + Math.sin(ex) * V.z
    return { ohR0: b.ohR[0], bnR0: b.bnRootR, ohRx, ohRy, ohRz, bnRx, bnRy, bnRz, brefX, brefY, brefZ }
  }

  /** Straight-form unzip: overhang de-spirals into a straight line at its root
   *  azimuth/radius (root bead unmoved); binder de-spirals on its own root rail
   *  and peels into a straight arm. No spiral, no unwind. */
  function _unzipStraight(phi, params, helixCtrl) {
    const b = _bound, M = b.M, Adir = b.Adir
    const meltBp = params?.meltBp ?? 0, meltSafe = Math.max(meltBp, 1e-6)
    const thRad = (params?.thetaDeg ?? 30) * Math.PI / 180
    const armStep = b.meanRise * (params?.armPull ?? 1.0)
    const forkPos = (1 - phi) * (M + meltBp) - meltBp / 2 - 0.5
    const _sstep = (t) => { t = t < 0 ? 0 : t > 1 ? 1 : t; return t * t * (3 - 2 * t) }
    const f = _straightFrame(b, params)
    const cN = Math.cos(thRad), sN = Math.sin(thRad)
    const _n3 = (x, y, z) => { const l = Math.hypot(x, y, z) || 1; return [x / l, y / l, z / l] }
    const [aX, aY, aZ] = _n3(-cN * Adir.x + sN * f.brefX, -cN * Adir.y + sN * f.brefY, -cN * Adir.z + sN * f.brefZ) // toward root + outward
    const pdX = sN * Adir.x + cN * f.brefX, pdY = sN * Adir.y + cN * f.brefY, pdZ = sN * Adir.z + cN * f.brefZ // 90° from splay/arm (uniform)
    const fp = Math.max(0, Math.min(M - 1, forkPos)), f0 = Math.floor(fp), f1 = Math.min(M - 1, f0 + 1), ft = fp - f0
    const faxX = b.ohAxis[f0 * 3] * (1 - ft) + b.ohAxis[f1 * 3] * ft
    const faxY = b.ohAxis[f0 * 3 + 1] * (1 - ft) + b.ohAxis[f1 * 3 + 1] * ft
    const faxZ = b.ohAxis[f0 * 3 + 2] * (1 - ft) + b.ohAxis[f1 * 3 + 2] * ft
    const pfX = faxX + f.bnR0 * f.bnRx, pfY = faxY + f.bnR0 * f.bnRy, pfZ = faxZ + f.bnR0 * f.bnRz   // binder rail at fork
    const updates = [], nowKeys = new Set()
    for (let i = 0; i < M; i++) {                       // overhang rail — at the root azimuth/radius
      const o = i * 3, on = b.ohNucs[i]
      updates.push({ helix_id: on.helix_id, bp_index: on.bp_index, direction: on.direction,
        backbone_position: [b.ohAxis[o] + f.ohR0 * f.ohRx, b.ohAxis[o + 1] + f.ohR0 * f.ohRy, b.ohAxis[o + 2] + f.ohR0 * f.ohRz],
        nx: -f.ohRx, ny: -f.ohRy, nz: -f.ohRz })       // slab → toward axis
      nowKeys.add(_key(on))
    }
    for (let bk = 0; bk < b.Mb; bk++) {                 // binder: root rail ↔ arm
      const o = bk * 3, bn = b.binderNucs[bk], oj = b.bnToOh[bk]
      if (oj < 0) { const ap = bn.backbone_position, an = bn.base_normal; const u = { helix_id: bn.helix_id, bp_index: bn.bp_index, direction: bn.direction, backbone_position: [ap[0], ap[1], ap[2]] }; if (an) { u.nx = an[0]; u.ny = an[1]; u.nz = an[2] } updates.push(u); nowKeys.add(_key(bn)); continue }
      const w = _sstep((forkPos - oj) / meltSafe + 0.5), oo = oj * 3
      const pcx = b.ohAxis[oo] + f.bnR0 * f.bnRx, pcy = b.ohAxis[oo + 1] + f.bnR0 * f.bnRy, pcz = b.ohAxis[oo + 2] + f.bnR0 * f.bnRz
      const s = (forkPos - oj) * armStep
      const bx = pcx * (1 - w) + (pfX + s * aX) * w, by = pcy * (1 - w) + (pfY + s * aY) * w, bz = pcz * (1 - w) + (pfZ + s * aZ) * w
      // freed binder slab → uniform direction 90° from the splay/arm (all aligned)
      updates.push({ helix_id: bn.helix_id, bp_index: bn.bp_index, direction: bn.direction,
        backbone_position: [bx, by, bz], nx: pdX, ny: pdY, nz: pdZ })
      nowKeys.add(_key(bn))
    }
    for (const key of _movedKeys) { if (nowKeys.has(key)) continue; const u = _authoredUpdate(key, _lastGeometry); if (u) updates.push(u) }
    helixCtrl.setBeadOverrides(updates)
    _movedKeys = nowKeys
  }

  /** Straight-form TMSD: overhang (substrate) is a straight line at its root
   *  azimuth/radius; binder & invader pair on the binder's root rail and peel
   *  into straight arms. */
  function _displacementStraight(phi, params, helixCtrl) {
    const b = _bound, M = b.M, Adir = b.Adir
    const meltBp = params?.meltBp ?? 0, meltSafe = Math.max(meltBp, 1e-6)
    const thB = (params?.thetaDeg ?? 30) * Math.PI / 180
    const thI = (params?.invaderSplayDeg ?? params?.thetaDeg ?? 30) * Math.PI / 180
    const armStep = b.meanRise * (params?.armPull ?? 1.0)
    const gap = params?.dispGap ?? 1.0
    const bf = phi * (M + meltBp) - meltBp / 2 - 0.5, bfB = bf + gap
    const _sstep = (t) => { t = t < 0 ? 0 : t > 1 ? 1 : t; return t * t * (3 - 2 * t) }
    const axSign = b.toeholdAtTip ? -1 : 1
    const f = _straightFrame(b, params)
    const _n3 = (x, y, z) => { const l = Math.hypot(x, y, z) || 1; return [x / l, y / l, z / l] }
    const [aIX, aIY, aIZ] = _n3(axSign * Math.cos(thI) * Adir.x + Math.sin(thI) * f.brefX, axSign * Math.cos(thI) * Adir.y + Math.sin(thI) * f.brefY, axSign * Math.cos(thI) * Adir.z + Math.sin(thI) * f.brefZ)
    const [aBX, aBY, aBZ] = _n3(-axSign * Math.cos(thB) * Adir.x + Math.sin(thB) * f.brefX, -axSign * Math.cos(thB) * Adir.y + Math.sin(thB) * f.brefY, -axSign * Math.cos(thB) * Adir.z + Math.sin(thB) * f.brefZ)
    // uniform invader free-slab base-normal (⟂ arm axial part) — all unbound slabs align
    const dotI = aIX * Adir.x + aIY * Adir.y + aIZ * Adir.z
    const [uiX, uiY, uiZ] = _n3(-(aIX - dotI * Adir.x), -(aIY - dotI * Adir.y), -(aIZ - dotI * Adir.z))
    // binder/invader root rail at displacement coord dd
    const _railAt = (dd, out) => {
      const j = Math.max(0, Math.min(M - 1, b.toeholdAtTip ? (M - 1 - dd) : dd))
      const j0 = Math.floor(j), j1 = Math.min(M - 1, j0 + 1), jt = j - j0
      out[0] = (b.ohAxis[j0 * 3] * (1 - jt) + b.ohAxis[j1 * 3] * jt) + f.bnR0 * f.bnRx
      out[1] = (b.ohAxis[j0 * 3 + 1] * (1 - jt) + b.ohAxis[j1 * 3 + 1] * jt) + f.bnR0 * f.bnRy
      out[2] = (b.ohAxis[j0 * 3 + 2] * (1 - jt) + b.ohAxis[j1 * 3 + 2] * jt) + f.bnR0 * f.bnRz
    }
    const _fI = [0, 0, 0], _fB = [0, 0, 0]; _railAt(bf, _fI); _railAt(bfB, _fB)
    const ipos = new Float32Array(M * 3), itan = new Float32Array(M * 3), ibn = new Float32Array(M * 3)
    for (let j = 0; j < M; j++) {
      const o = j * 3, d = b.dOf[j], wj = _sstep((bf - d) / meltSafe + 0.5)
      const bx = b.ohAxis[o] + f.bnR0 * f.bnRx, by = b.ohAxis[o + 1] + f.bnR0 * f.bnRy, bz = b.ohAxis[o + 2] + f.bnR0 * f.bnRz   // bound = binder rail
      const s = (d - bf) * armStep
      const fx = _fI[0] + s * aIX, fy = _fI[1] + s * aIY, fz = _fI[2] + s * aIZ                                                  // free = arm
      ipos[o] = bx * wj + fx * (1 - wj); ipos[o + 1] = by * wj + fy * (1 - wj); ipos[o + 2] = bz * wj + fz * (1 - wj)
      // Slab frame SLERPs the shortest path from the BOUND frame (tangent = axis,
      // base-normal = toward axis on the rail) to the UNBOUND frame. The free
      // tangent is the BACKBONE direction in array order = axSign·arm (NOT the arm-
      // extension direction), so it stays aligned with the bound tangent — without
      // this the frame would slerp ~180° about the normal.
      _slerpFrame([Adir.x, Adir.y, Adir.z], [-f.bnRx, -f.bnRy, -f.bnRz], [axSign * aIX, axSign * aIY, axSign * aIZ], [uiX, uiY, uiZ], 1 - wj, itan, ibn, o)
    }
    if (_invader) _invader.update([{ pos: ipos, tan: itan, bn: ibn, role: 'invader' }])
    const updates = [], nowKeys = new Set()
    for (let i = 0; i < M; i++) {                       // overhang substrate rail — root-aligned
      const o = i * 3, on = b.ohNucs[i]
      updates.push({ helix_id: on.helix_id, bp_index: on.bp_index, direction: on.direction,
        backbone_position: [b.ohAxis[o] + f.ohR0 * f.ohRx, b.ohAxis[o + 1] + f.ohR0 * f.ohRy, b.ohAxis[o + 2] + f.ohR0 * f.ohRz],
        nx: -f.ohRx, ny: -f.ohRy, nz: -f.ohRz })
      nowKeys.add(_key(on))
    }
    for (let bk = 0; bk < b.Mb; bk++) {
      const o = bk * 3, bn = b.binderNucs[bk], oj = b.bnToOh[bk]
      if (oj < 0) { const ap = bn.backbone_position, an = bn.base_normal; const u = { helix_id: bn.helix_id, bp_index: bn.bp_index, direction: bn.direction, backbone_position: [ap[0], ap[1], ap[2]] }; if (an) { u.nx = an[0]; u.ny = an[1]; u.nz = an[2] } updates.push(u); nowKeys.add(_key(bn)); continue }
      const d = b.dOf[oj], df = _sstep((bfB - d) / meltSafe + 0.5), oo = oj * 3
      const pcx = b.ohAxis[oo] + f.bnR0 * f.bnRx, pcy = b.ohAxis[oo + 1] + f.bnR0 * f.bnRy, pcz = b.ohAxis[oo + 2] + f.bnR0 * f.bnRz
      const s = (bfB - d) * armStep
      const bx = pcx * (1 - df) + (_fB[0] + s * aBX) * df, by = pcy * (1 - df) + (_fB[1] + s * aBY) * df, bz = pcz * (1 - df) + (_fB[2] + s * aBZ) * df
      const inw = _inwardAxis(b, bx, by, bz)          // displaced-strand slab → toward axis center
      updates.push({ helix_id: bn.helix_id, bp_index: bn.bp_index, direction: bn.direction,
        backbone_position: [bx, by, bz], nx: inw[0], ny: inw[1], nz: inw[2] })
      nowKeys.add(_key(bn))
    }
    for (const key of _movedKeys) { if (nowKeys.has(key)) continue; const u = _authoredUpdate(key, _lastGeometry); if (u) updates.push(u) }
    helixCtrl.setBeadOverrides(updates)
    _movedKeys = nowKeys
  }

  function _authoredUpdate(key, geometry) {
    if (!geometry) return null
    for (const n of geometry) {
      if (_key(n) === key) {
        const p = n.backbone_position, bnv = n.base_normal
        const u = { helix_id: n.helix_id, bp_index: n.bp_index, direction: n.direction,
          backbone_position: [p[0], p[1], p[2]] }
        if (bnv) { u.nx = bnv[0]; u.ny = bnv[1]; u.nz = bnv[2] }  // restore slab orientation
        return u
      }
    }
    return null
  }

  function clear() {
    const helixCtrl = getHelixCtrl?.()
    if (helixCtrl?.setBeadOverrides && _movedKeys.size && _lastGeometry) {
      const updates = []
      for (const key of _movedKeys) {
        const u = _authoredUpdate(key, _lastGeometry)
        if (u) updates.push(u)
      }
      if (updates.length) helixCtrl.setBeadOverrides(updates)
    }
    if (_invader) _invader.update([])           // hide the synthetic invader
    _movedKeys = new Set()
    _bound = null
  }

  function getFrame() { return _bound }
  function isBound() { return _bound != null }
  function dispose() { clear(); if (_invader) { _invader.dispose(); _invader = null } }

  return { bind, setPhi, getFrame, isBound, clear, dispose }
}
