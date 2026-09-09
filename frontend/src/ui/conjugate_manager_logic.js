// Pure helpers for the Conjugate Manager — color/label/summary of azide-oligo
// conjugation candidate residues. No THREE, no DOM, no fetch → unit-testable.
//
// Candidate chemistries (the surface handles used for two-step SPAAC conjugation
// of an azide-modified oligo): lysine ε-amine, cysteine thiol, N-terminal α-amine.

export const CHEMISTRY_META = {
  lys:   { name: 'Lysine',     site: 'ε-amine', color: 0x39ff14 }, // green
  cys:   { name: 'Cysteine',   site: 'thiol',   color: 0xff7f0e }, // orange
  nterm: { name: 'N-terminus', site: 'α-amine', color: 0xff2fd0 }, // magenta
}

const _UNKNOWN = { name: 'Unknown', site: '', color: 0x999999 }

/** Marker color (hex int) for a chemistry key; grey fallback for unknown. */
export function chemistryColor(chemistry) {
  return (CHEMISTRY_META[chemistry] ?? _UNKNOWN).color
}

/** Marker color as a CSS `#rrggbb` string (for legend swatches / list dots). */
export function chemistryCss(chemistry) {
  return '#' + chemistryColor(chemistry).toString(16).padStart(6, '0')
}

/** Human label for one candidate, e.g. "LYS A:142 — ε-amine". */
export function candidateLabel(c) {
  const meta = CHEMISTRY_META[c.chemistry] ?? _UNKNOWN
  return `${c.res_name} ${c.chain_id}:${c.res_seq} — ${meta.site}`
}

// ── ssDNA handle helpers ─────────────────────────────────────────────────────

export const SSDNA_PREVIEW_RISE_NM = 0.334
export const SSDNA_PREVIEW_RADIUS_NM = 1.0
export const SSDNA_PREVIEW_TWIST_RAD = 34.3 * Math.PI / 180

const _COMPLEMENT = { A: 'T', T: 'A', G: 'C', C: 'G', N: 'N' }

/** Reverse complement of a DNA sequence (the handle that hybridizes an overhang).
 *  Unknown / lowercase bases map to 'N'; empty/nullish → ''. */
export function reverseComplement(seq) {
  if (!seq) return ''
  let out = ''
  for (const ch of seq.toUpperCase()) out = (_COMPLEMENT[ch] ?? 'N') + out
  return out
}

/** Display label for an overhang row: its label or id, with sequence length. */
export function overhangLabel(ovhg) {
  const name = ovhg.label || ovhg.id
  const n = (ovhg.sequence || '').length
  return n ? `${name} (${n} nt)` : `${name} (no seq)`
}

/** Unit vector from `centroid` toward `point` (radially outward from the body).
 *  Falls back to +Z if the two coincide. */
export function radialOutward(point, centroid) {
  const dx = point.x - centroid.x, dy = point.y - centroid.y, dz = point.z - centroid.z
  const len = Math.sqrt(dx * dx + dy * dy + dz * dz)
  if (len < 1e-9) return { x: 0, y: 0, z: 1 }
  return { x: dx / len, y: dy / len, z: dz / len }
}

/** A unit vector perpendicular to `dir` (used as the base-normal for slabs on a
 *  straight ssDNA handle). Deterministic: crosses `dir` with whichever world axis
 *  it is least parallel to. Assumes `dir` is already unit-length. */
export function perpendicular(dir) {
  const ax = Math.abs(dir.x) < 0.9 ? { x: 1, y: 0, z: 0 } : { x: 0, y: 1, z: 0 }
  // cross(dir, ax)
  let x = dir.y * ax.z - dir.z * ax.y
  let y = dir.z * ax.x - dir.x * ax.z
  let z = dir.x * ax.y - dir.y * ax.x
  const len = Math.sqrt(x * x + y * y + z * z) || 1
  return { x: x / len, y: y / len, z: z / len }
}

/** Backbone bead positions for an ssDNA handle of `count` nt: start at `start`
 *  and step `rise` nm along unit `dir`. First bead = the (azide-anchored) tip on
 *  the surface; the strand extends outward. Returns [{x,y,z}, …]. */
export function ssdnaBackbonePoints(start, dir, count, rise = 0.5) {
  const pts = []
  const n = Math.max(1, count | 0)
  for (let i = 0; i < n; i++) {
    pts.push({ x: start.x + dir.x * rise * i, y: start.y + dir.y * rise * i, z: start.z + dir.z * rise * i })
  }
  return pts
}

/** B-form frames for an ssDNA preview around an arbitrary axis.  These are the
 * same rise, radius, phase, and twist used by the overhang/surface preview. */
export function ssdnaHelixFrames(start, dir, count, {
  rise = SSDNA_PREVIEW_RISE_NM,
  radius = SSDNA_PREVIEW_RADIUS_NM,
  twist = SSDNA_PREVIEW_TWIST_RAD,
  phase = Math.PI / 2 + SSDNA_PREVIEW_TWIST_RAD / 2,
} = {}) {
  const n = Math.max(1, count | 0)
  const u = perpendicular(dir)
  const v = {
    x: dir.y * u.z - dir.z * u.y,
    y: dir.z * u.x - dir.x * u.z,
    z: dir.x * u.y - dir.y * u.x,
  }
  const out = []
  for (let i = 0; i < n; i++) {
    const angle = phase + i * twist
    const ca = Math.cos(angle), sa = Math.sin(angle)
    const rx = u.x * ca + v.x * sa
    const ry = u.y * ca + v.y * sa
    const rz = u.z * ca + v.z * sa
    out.push({
      position: {
        x: start.x + dir.x * rise * i + radius * rx,
        y: start.y + dir.y * rise * i + radius * ry,
        z: start.z + dir.z * rise * i + radius * rz,
      },
      baseNormal: { x: -rx, y: -ry, z: -rz },
      axisTangent: { x: dir.x, y: dir.y, z: dir.z },
    })
  }
  return out
}

/** Counts per chemistry for the legend: [{chemistry, name, site, color, css, count}]
 *  in a stable order (lys, cys, nterm), omitting chemistries with no candidates. */
export function summarizeCandidates(candidates = []) {
  const counts = new Map()
  for (const c of candidates) counts.set(c.chemistry, (counts.get(c.chemistry) ?? 0) + 1)
  return Object.keys(CHEMISTRY_META)
    .filter(k => counts.has(k))
    .map(k => ({
      chemistry: k,
      name: CHEMISTRY_META[k].name,
      site: CHEMISTRY_META[k].site,
      color: CHEMISTRY_META[k].color,
      css: chemistryCss(k),
      count: counts.get(k),
    }))
}
