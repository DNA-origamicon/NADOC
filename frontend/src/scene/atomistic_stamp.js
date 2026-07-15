/**
 * atomistic_stamp.js — client-side CG→atomistic expansion (ChimeraX-speed rep switch).
 *
 * The relaxed-display all-atom set is, per nucleotide, a fixed local template rigidly
 * stamped by that nucleotide's frame (`world = origin + R·local`), except a small
 * "non-rigid" minority (backbone-closure linkers, crossover/skip bridges, extra-base
 * inserts, extension tails) whose positions the backend ships directly.
 *
 * Instead of the backend re-serialising every atom's XYZ per frame, it ships:
 *   • ONCE per job — the descriptor: which serial is rigid, its template-local coord,
 *     which nucleotide it belongs to (GET .../atomistic-stamp).
 *   • per frame — the compact frames payload: per-nucleotide (origin, R) + the non-rigid
 *     XYZ (POST .../display-atomistic-frames).
 *
 * This module expands those into the flat serial-indexed XYZ array the atomistic
 * renderer already consumes (`applyPositionLerp(flat, flat, 0)`) — pure, no Three.js,
 * so a representation switch does one vectorised pass with no per-atom network cost.
 *
 * Wire shapes (snake_case, straight from the JSON routes):
 *   descriptor  = { atom_nuc:[int|-1], atom_local:[3·nAtoms], nonrigid_serials:[int],
 *                   topology_hash, n_atoms }
 *   framePayload = { frames:[12·nNuc]  (origin[3]+R[9] row-major, nuc order),
 *                    nonrigid_xyz:[3·k] (in nonrigid_serials order), topology_hash }
 */

/**
 * Expand (descriptor + frame payload) into a flat Float32 XYZ array indexed by atom
 * serial (`out[serial*3 + {0,1,2}]`).  Returns null on missing/!ready input.
 */
export function expandStampFrames(descriptor, framePayload) {
  if (!descriptor || !framePayload || framePayload.ready === false) return null
  const atomNuc = descriptor.atom_nuc
  const atomLocal = descriptor.atom_local
  const nonrigidSerials = descriptor.nonrigid_serials
  const frames = framePayload.frames
  const nonrigidXyz = framePayload.nonrigid_xyz
  if (!atomNuc || !atomLocal || !frames) return null

  const nAtoms = atomNuc.length
  const out = new Float32Array(nAtoms * 3)

  // Rigid majority: world = origin + R·local  (R row-major, 9 floats after origin's 3).
  for (let s = 0; s < nAtoms; s++) {
    const ni = atomNuc[s]
    if (ni < 0) continue
    const f = ni * 12
    const l = s * 3
    const lx = atomLocal[l], ly = atomLocal[l + 1], lz = atomLocal[l + 2]
    out[l]     = frames[f]     + frames[f + 3] * lx + frames[f + 4] * ly + frames[f + 5] * lz
    out[l + 1] = frames[f + 1] + frames[f + 6] * lx + frames[f + 7] * ly + frames[f + 8] * lz
    out[l + 2] = frames[f + 2] + frames[f + 9] * lx + frames[f + 10] * ly + frames[f + 11] * lz
  }

  // Non-rigid minority: copied straight through (byte-exact from the backend build).
  if (nonrigidSerials && nonrigidXyz) {
    for (let j = 0; j < nonrigidSerials.length; j++) {
      const s3 = nonrigidSerials[j] * 3
      const j3 = j * 3
      out[s3]     = nonrigidXyz[j3]
      out[s3 + 1] = nonrigidXyz[j3 + 1]
      out[s3 + 2] = nonrigidXyz[j3 + 2]
    }
  }
  return out
}

/** True when the descriptor and per-frame payload describe the same JOB topology (so the
 *  serial-indexed frames line up with the atoms the renderer holds). */
export function stampTopologyMatches(descriptor, framePayload) {
  return !!descriptor && !!framePayload
    && descriptor.topology_hash === framePayload.topology_hash
}
